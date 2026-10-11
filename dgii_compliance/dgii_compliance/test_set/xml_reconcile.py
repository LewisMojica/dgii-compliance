"""Reconciles the generated e-CF XML against the source workbook values."""

import frappe
from frappe.utils import flt

from dgii_compliance.dgii_compliance.doctype.ecf.builders import BUILDERS
from dgii_compliance.dgii_compliance.test_set import importer, mapping
from dgii_compliance.dgii_compliance.test_set.reconcile import _group_tuples


def build(case, invoice):
	"""Builds the (unsigned) e-CF XML for a case's invoice."""
	return BUILDERS[case["tipo"]](invoice)


def _xml_tag(column):
	# Only a couple of workbook headers differ from the XML element name.
	return {"ENCF": "eNCF"}.get(column, column)


def _matches(expected, actual):
	if actual is None:
		return False
	if isinstance(expected, (int, float)) and not isinstance(expected, bool):
		return abs(flt(actual) - flt(expected)) < 0.005
	return str(actual).strip() == str(expected).strip()


def _check(mismatches, label, expected, actual):
	if not _matches(expected, actual):
		mismatches.append({"field": label, "expected": str(expected), "actual": str(actual)})


def _check_absent(mismatches, label, actual):
	if actual is not None:
		mismatches.append({"field": label + " (debe estar ausente)", "expected": "", "actual": str(actual)})


def reconcile(case, invoice_name):
	"""Returns ``{field, expected, actual}`` mismatches between XML and workbook."""
	doc = frappe.get_doc("Sales Invoice", invoice_name)
	xml = build(case, doc)
	encabezado = xml.find("Encabezado")
	mismatches = []

	_header(mismatches, case, xml, encabezado)
	_items(mismatches, case, xml)
	_payments(mismatches, case, xml)
	_phones(mismatches, case, xml)
	return mismatches


def _header(mismatches, case, xml, encabezado):
	for column, (fieldname, kind) in mapping.HEADER_MAP.items():
		if fieldname == "skip":
			continue
		tag = _xml_tag(column)
		actual = encabezado.findtext(f".//{tag}")
		expected = case["header"].get(column)
		if expected is None:
			_check_absent(mismatches, tag, actual)
			continue
		if column == "TipoeCF":
			_check(mismatches, tag, int(expected), actual)
			continue
		value = mapping.convert(expected, kind)
		if kind == "date":
			value = value.strftime("%d-%m-%Y")
		_check(mismatches, tag, value, actual)

	_check(mismatches, "RNCEmisor", case["header"].get("RNCEmisor"), encabezado.findtext(".//RNCEmisor"))


def _items(mismatches, case, xml):
	nodes = {}
	for node in xml.findall("DetallesItems/Item"):
		nodes[int(node.findtext("NumeroLinea"))] = node

	for line in importer._line_numbers(case):
		node = nodes.get(line)
		if node is None:
			mismatches.append({"field": f"item[{line}]", "expected": "present", "actual": "missing"})
			continue
		for base, (fieldname, kind) in mapping.ITEM_SCALARS.items():
			expected = importer._item_scalar(case, base, line)
			actual = node.findtext(f".//{base}")
			if expected is None:
				_check_absent(mismatches, f"item[{line}].{base}", actual)
				continue
			value = mapping.convert(expected, kind)
			if kind == "date":
				value = value.strftime("%d-%m-%Y")
			_check(mismatches, f"item[{line}].{base}", value, actual)

		_check_group(mismatches, case, node, line, "TablaCodigosItem", "CodigosItem", mapping.CODIGO_GROUP)
		_check_group(
			mismatches, case, node, line, "TablaSubDescuento", "SubDescuento", mapping.SUBDESCUENTO_GROUP
		)
		_check_group(
			mismatches, case, node, line, "TablaSubRecargo", "SubRecargo", mapping.SUBRECARGO_GROUP
		)


def _check_group(mismatches, case, node, line, table_tag, row_tag, group):
	# Some workbook headers differ from the XSD element names (e.g. the workbook
	# spells it "MontosubRecargo").
	tag_map = {"MontosubRecargo": "MontoSubRecargo"}
	table = node.find(table_tag)
	rows = table.findall(row_tag) if table is not None else []
	expected = [tuple(values) for ln, values in _group_tuples(case, group) if ln == line]
	actual = []
	for row in rows:
		values = []
		for base in group:
			text = row.findtext(tag_map.get(base, base))
			values.append("" if text is None else text)
		actual.append(tuple(values))
	if expected != actual:
		mismatches.append(
			{"field": f"item[{line}].{table_tag}", "expected": str(expected), "actual": str(actual)}
		)


def _payments(mismatches, case, xml):
	formas = case["indexed"].get("FormaPago", {})
	if not formas:
		return
	montos = case["indexed"].get("MontoPago", {})
	table = xml.find("Encabezado/IdDoc/TablaFormasPago")
	rows = table.findall("FormaDePago") if table is not None else []
	actual = [(row.findtext("FormaPago"), row.findtext("MontoPago")) for row in rows]
	expected = [(str(formas[idx]).strip(), f"{flt(montos.get(idx, 0)):.2f}") for idx in sorted(formas)]
	if expected != actual:
		mismatches.append({"field": "TablaFormasPago", "expected": str(expected), "actual": str(actual)})


def _phones(mismatches, case, xml):
	phones = case["indexed"].get("TelefonoEmisor", {})
	if not phones:
		return
	table = xml.find("Encabezado/Emisor/TablaTelefonoEmisor")
	actual = [el.text for el in table.findall("TelefonoEmisor")] if table is not None else []
	expected = [str(phones[idx]).strip() for idx in sorted(phones)]
	if expected != actual:
		mismatches.append({"field": "TablaTelefonoEmisor", "expected": str(expected), "actual": str(actual)})
