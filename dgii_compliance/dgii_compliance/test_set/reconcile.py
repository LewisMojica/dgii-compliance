"""Reconciles stored Sales Invoices against the source workbook values."""

import frappe
from frappe.utils import flt

from dgii_compliance.dgii_compliance.test_set import importer, mapping


def _matches(expected, actual):
	if expected is None:
		return actual in (None, "", 0, 0.0)
	if isinstance(expected, (int, float)) and not isinstance(expected, bool):
		return abs(flt(actual) - flt(expected)) < 0.005
	return str(actual or "").strip() == str(expected).strip()


def _check(mismatches, label, expected, actual):
	if not _matches(expected, actual):
		mismatches.append({"field": label, "expected": str(expected), "actual": str(actual)})


def _empty(value):
	return value in (None, "") or (isinstance(value, str) and not value.strip())


NUMERIC_FIELDTYPES = {"Float", "Currency", "Int", "Percent", "Long Int"}


def _check_empty(mismatches, label, actual, fieldtype=None):
	# Numeric custom fields are NOT NULL DEFAULT 0 in MariaDB, so 0 is "unset".
	if fieldtype in NUMERIC_FIELDTYPES:
		return
	if not _empty(actual):
		mismatches.append({"field": label + " (debe estar vacío)", "expected": "", "actual": str(actual)})


def reconcile_case(case, invoice_name):
	"""Returns a list of ``{field, expected, actual}`` mismatches."""
	doc = frappe.get_doc("Sales Invoice", invoice_name)
	meta = frappe.get_meta("Sales Invoice")
	detalle_meta = frappe.get_meta("eCF Detalle Item")
	mismatches = []

	# Header fields
	for column, (fieldname, kind) in mapping.HEADER_MAP.items():
		if fieldname == "skip":
			continue
		expected = case["header"].get(column)
		if expected is None:
			fieldtype = meta.get_field(fieldname).fieldtype if meta.get_field(fieldname) else None
			_check_empty(mismatches, fieldname, doc.get(fieldname), fieldtype)
			continue
		_check(mismatches, fieldname, mapping.convert(expected, kind), doc.get(fieldname))

	# Derived emitter RNC (company tax id)
	company = frappe.db.get_value("Company", doc.company, "tax_id")
	_check(mismatches, "RNCEmisor", case["header"].get("RNCEmisor"), company)

	# Per-line details
	detalle = {row.numero_linea: row for row in doc.custom_ecf_detalle_items}
	for line in importer._line_numbers(case):
		row = detalle.get(line)
		if row is None:
			mismatches.append({"field": f"linea[{line}]", "expected": "present", "actual": "missing"})
			continue
		for base, (fieldname, kind) in mapping.ITEM_SCALARS.items():
			expected = importer._item_scalar(case, base, line)
			if expected is None:
				df = detalle_meta.get_field(fieldname)
				_check_empty(mismatches, f"linea[{line}].{fieldname}", row.get(fieldname), df.fieldtype if df else None)
				continue
			_check(mismatches, f"linea[{line}].{fieldname}", mapping.convert(expected, kind), row.get(fieldname))

	# Repeated child groups
	_check_group(mismatches, case, doc, mapping.CODIGO_GROUP, "custom_ecf_codigos_item")
	_check_group(mismatches, case, doc, mapping.SUBDESCUENTO_GROUP, "custom_ecf_sub_descuentos")
	_check_group(mismatches, case, doc, mapping.SUBRECARGO_GROUP, "custom_ecf_sub_recargos")

	return mismatches


def _norm_group_value(fieldname, value):
	if fieldname in importer._FLOAT_CHILD:
		return f"{flt(value or 0):.2f}"
	return str(value or "").strip()


def _check_group(mismatches, case, doc, group, child_field):
	expected = _group_tuples(case, group)
	actual = []
	for row in doc.get(child_field) or []:
		actual.append(
			(row.numero_linea, tuple(_norm_group_value(f, row.get(f)) for f in group.values()))
		)
	actual = sorted(actual)
	expected = sorted(expected)
	if expected != actual:
		mismatches.append({"field": child_field, "expected": str(expected), "actual": str(actual)})


def _group_tuples(case, group):
	bases = list(group)
	rows = []
	for line, subs in importer._rows_by_line(case, bases).items():
		for sub in sorted(subs):
			values = []
			for base, fieldname in group.items():
				value = case["sub"].get(base, {}).get(line, {}).get(sub)
				values.append(_norm_group_value(fieldname, value))
			rows.append((line, tuple(values)))
	return rows
