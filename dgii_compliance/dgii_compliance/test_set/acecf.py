"""DGII certification set for Aprobaciones o Rechazos Comerciales (ACECF).

Unlike the e-CF workbook, the ACECF set is a flat sheet (one case per row, one
value per column, no repeating groups). Each row references an e-CF issued by a
*simulated* counterparty; we act as the receptor and generate the response.

Columns (``ACEECF_Generadas`` sheet):

	Version, RNCEmisor, eNCF, FechaEmision, MontoTotal, RNCComprador, Estado,
	DetalleMotivoRechazo, FechaHoraAprobacionComercial
"""

import frappe
import openpyxl
from frappe import _
from frappe.utils import flt
from lxml import etree

from dgii_compliance.dgii_compliance.doctype.ecf.builders.common import format_dgii_date
from dgii_compliance.dgii_compliance.doctype.ecf.new_ecf import validate_xml_schema
from dgii_compliance.dgii_compliance.doctype.ecf_aprobacion_comercial import acecf
from dgii_compliance.dgii_compliance.test_set import parser

DOCTYPE = "eCF Aprobacion Comercial"
DEFAULT_SHEET = "ACEECF_Generadas"
DS_SIGNATURE = "{http://www.w3.org/2000/09/xmldsig#}Signature"
MODES = ("parse", "docs", "reconcile", "xml", "sign")

# Workbook column -> (doctype fieldname, type)
COLUMN_MAP = {
	"RNCEmisor": ("rnc_emisor", "str"),
	"eNCF": ("encf", "str"),
	"FechaEmision": ("fecha_emision", "str"),
	"MontoTotal": ("monto_total", "float"),
	"RNCComprador": ("rnc_comprador", "str"),
	"Estado": ("estado_acecf", "code"),
	"DetalleMotivoRechazo": ("detalle_motivo_rechazo", "str"),
	"FechaHoraAprobacionComercial": ("fecha_hora_aprobacion_comercial", "str"),
}

# XML tag (in schema order) -> how to derive the expected value from a case
XML_EXPECTED = (
	("Version", lambda case: "1.0"),
	("RNCEmisor", lambda case: parser._clean(case.get("RNCEmisor"))),
	("eNCF", lambda case: parser._clean(case.get("eNCF"))),
	("FechaEmision", lambda case: format_dgii_date(case.get("FechaEmision"))),
	("MontoTotal", lambda case: f"{flt(case.get('MontoTotal')):.2f}"),
	("RNCComprador", lambda case: parser._clean(case.get("RNCComprador"))),
	("Estado", lambda case: str(parser.to_int(case.get("Estado")))),
	("DetalleMotivoRechazo", lambda case: parser._clean(case.get("DetalleMotivoRechazo"))),
	(
		"FechaHoraAprobacionComercial",
		lambda case: parser._clean(case.get("FechaHoraAprobacionComercial")),
	),
)

SENT_STATUSES = ("sent", "ok", "error")


def convert(value, kind):
	if kind == "float":
		return parser.to_float(value)
	if kind == "code":
		return str(parser.to_int(value))
	return parser._clean(value)


def _key(case):
	return (parser._clean(case.get("RNCEmisor")), parser._clean(case.get("eNCF")))


def load_cases(path, sheet=DEFAULT_SHEET):
	"""Reads the ACECF workbook into a list of flat case dicts."""
	worksheet = openpyxl.load_workbook(path, data_only=True, read_only=True)[sheet]
	rows = worksheet.iter_rows(values_only=True)
	header = next(rows, None) or []
	cases = []
	for row in rows:
		if not any(cell not in parser.EMPTY_VALUES for cell in row):
			continue
		case = {}
		for column, value in zip(header, row):
			if column is None:
				continue
			clean = parser._clean(value)
			if clean is not None:
				case[str(column).strip()] = clean
		if case.get("eNCF"):
			cases.append(case)
	return dedupe(cases)


def dedupe(cases):
	seen = {}
	for case in cases:
		seen.setdefault(_key(case), case)
	return list(seen.values())


def summarize(cases):
	approvals = sum(1 for case in cases if str(parser.to_int(case.get("Estado"))) == "1")
	return {"total": len(cases), "aprobados": approvals, "rechazados": len(cases) - approvals}


def _ever_sent(acecf_doc):
	return bool(acecf_doc.get("sent_at") or acecf_doc.get("respuesta_estado"))


def reset_case(rnc_emisor, encf):
	"""Deletes any ACECF previously created for (RNCEmisor, eNCF).

	Refuses to reset one that was already sent to DGII.
	"""
	names = frappe.get_all(
		DOCTYPE, filters={"rnc_emisor": rnc_emisor, "encf": encf}, pluck="name"
	)
	if not names:
		return []
	sent = frappe.get_all(
		DOCTYPE,
		filters={"name": ["in", names], "status": ["in", SENT_STATUSES]},
		fields=["name", "status"],
	)
	if sent:
		frappe.throw(
			_("La aprobación comercial de {0} ya fue enviada a DGII (estado: {1}).").format(
				encf, sent[0].get("status") or "desconocido"
			)
		)
	for name in names:
		frappe.delete_doc(DOCTYPE, name, force=True, ignore_permissions=True)
	return names


def build_doc(case):
	doc = frappe.new_doc(DOCTYPE)
	for column, (fieldname, kind) in COLUMN_MAP.items():
		value = case.get(column)
		if value is None:
			continue
		doc.set(fieldname, convert(value, kind))
	return doc


def import_case(case, reset=True):
	rnc_emisor, encf = _key(case)
	if reset:
		reset_case(rnc_emisor, encf)
	doc = build_doc(case)
	doc.insert(ignore_permissions=True)
	return doc.name


def import_cases(cases, reset=True):
	report = []
	for case in cases:
		rnc_emisor, encf = _key(case)
		entry = {"rnc_emisor": rnc_emisor, "encf": encf, "acecf": None, "error": None}
		try:
			entry["acecf"] = import_case(case, reset=reset)
			frappe.db.commit()
		except Exception as exc:
			frappe.db.rollback()
			entry["error"] = str(exc)
		report.append(entry)
	return report


def _matches(expected, actual):
	if expected is None:
		return actual in (None, "")
	if isinstance(expected, float):
		return abs(flt(actual) - expected) < 0.005
	return str(actual or "").strip() == str(expected).strip()


def reconcile_case(case, name):
	"""Compares an ACECF document's stored fields to the workbook row."""
	doc = frappe.get_doc(DOCTYPE, name)
	mismatches = []
	if "Version" in case and str(case["Version"]) != "1.0":
		mismatches.append({"field": "Version", "expected": "1.0", "actual": str(case["Version"])})
	for column, (fieldname, kind) in COLUMN_MAP.items():
		expected = case.get(column)
		actual = doc.get(fieldname)
		if expected is None:
			if not _matches(None, actual) and actual not in (None, "", 0, 0.0):
				mismatches.append(
					{"field": fieldname + " (debe estar vacío)", "expected": "", "actual": str(actual)}
				)
			continue
		converted = convert(expected, kind)
		if not _matches(converted, actual):
			mismatches.append(
				{"field": fieldname, "expected": str(converted), "actual": str(actual)}
			)
	return mismatches


def _check(mismatches, label, expected, actual):
	if not _matches(expected, actual):
		mismatches.append({"field": label, "expected": str(expected), "actual": str(actual)})


def _check_absent(mismatches, label, actual):
	if actual not in (None, ""):
		mismatches.append({"field": label + " (debe estar ausente)", "expected": "", "actual": str(actual)})


def reconcile_xml(case, name):
	"""Compares the built ACECF XML to the workbook row, field by field."""
	doc = frappe.get_doc(DOCTYPE, name)
	detalle = acecf.build(doc).find("DetalleAprobacionComercial")
	mismatches = []
	for tag, expected_of in XML_EXPECTED:
		expected = expected_of(case)
		actual = detalle.findtext(tag)
		if expected is None:
			_check_absent(mismatches, tag, actual)
		else:
			_check(mismatches, tag, expected, actual)
	return mismatches


def _xml_check(case, name):
	"""XSD-validates the unsigned XML (with a placeholder signature) and reconciles it."""
	doc = frappe.get_doc(DOCTYPE, name)
	xml = acecf.build(doc)
	etree.SubElement(xml, DS_SIGNATURE)
	valid = validate_xml_schema(xml, acecf.SCHEMA_KEY)
	return {"schema_valid": bool(valid), "mismatches": reconcile_xml(case, name)}


def _sign(case, name):
	doc = frappe.get_doc(DOCTYPE, name)
	doc.xml = acecf.sign_and_validate(doc)
	doc.save(ignore_permissions=True)
	return doc.xml


def _filter(cases, only=None, limit=None):
	if only:
		wanted = {value.strip() for value in only.split(",")} if isinstance(only, str) else set(only)
		cases = [case for case in cases if case.get("eNCF") in wanted]
	if limit:
		cases = cases[: int(limit)]
	return cases


@frappe.whitelist()
def run(path, sheet=DEFAULT_SHEET, mode="docs", limit=None, only=None, reset=True):
	"""Parses the ACECF workbook and (depending on ``mode``) imports/reconciles.

	Modes:
		parse     -> summarize the workbook
		docs      -> create ACECF documents
		reconcile -> create documents and compare their fields to the workbook
		xml       -> create documents, generate the XML and reconcile it
		sign      -> create documents and generate + store the signed XML
	"""
	if mode not in MODES:
		frappe.throw(_("Modo inválido '{0}'. Use uno de {1}.").format(mode, MODES))

	cases = _filter(load_cases(path, sheet), only=only, limit=limit)
	result = {"mode": mode, "summary": summarize(cases)}

	if mode == "parse":
		result["cases"] = [
			{"rnc_emisor": _key(case)[0], "encf": case.get("eNCF"), "estado": case.get("Estado")}
			for case in cases
		]
		return result

	report = import_cases(cases, reset=bool(reset))
	by_key = {_key(case): case for case in cases}

	for entry in report:
		if not entry["acecf"]:
			continue
		case = by_key[(entry["rnc_emisor"], entry["encf"])]
		if mode == "reconcile":
			entry["mismatches"] = reconcile_case(case, entry["acecf"])
		elif mode == "xml":
			entry.update(_xml_check(case, entry["acecf"]))
		elif mode == "sign":
			try:
				entry["xml_len"] = len(_sign(case, entry["acecf"]))
			except Exception as exc:
				entry["error"] = str(exc)

	result["report"] = report
	result["created"] = sum(1 for entry in report if entry["acecf"])
	result["failed"] = sum(1 for entry in report if entry["error"])
	if mode in ("reconcile", "xml"):
		result["mismatched"] = sum(1 for entry in report if entry.get("mismatches"))
	return result
