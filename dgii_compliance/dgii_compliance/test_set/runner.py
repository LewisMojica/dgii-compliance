"""Orchestrates parsing, invoice creation and reconciliation for the test set."""

import frappe
from lxml import etree

from dgii_compliance.dgii_compliance.doctype.ecf.new_ecf import validate_xml_schema
from dgii_compliance.dgii_compliance.test_set import importer, parser, xml_reconcile
from dgii_compliance.dgii_compliance.test_set.reconcile import reconcile_case

MODES = ("parse", "invoices", "reconcile", "xml")
DS_SIGNATURE = "{http://www.w3.org/2000/09/xmldsig#}Signature"


def _filter(cases, only=None, limit=None):
	if only:
		wanted = {value.strip() for value in only.split(",")} if isinstance(only, str) else set(only)
		cases = [case for case in cases if case["encf"] in wanted]
	if limit:
		cases = cases[: int(limit)]
	return cases


def _xml_check(case, invoice_name):
	"""XSD-validates the built XML and reconciles it against the workbook."""
	document = frappe.get_doc("Sales Invoice", invoice_name)
	xml = xml_reconcile.build(case, document)
	etree.SubElement(xml, DS_SIGNATURE)
	valid = validate_xml_schema(xml, case["tipo"])
	return {"schema_valid": bool(valid), "mismatches": xml_reconcile.reconcile(case, invoice_name)}


@frappe.whitelist()
def run(path, sheet="ECF", mode="invoices", company=None, limit=None, only=None, reset=True):
	"""Parses ``path`` and (depending on ``mode``) creates/reconciles invoices.

	Modes:
		parse     -> only summarize the workbook
		invoices  -> create draft invoices
		reconcile -> create draft invoices and compare them to the workbook
		xml       -> create draft invoices, generate the XML and reconcile it
	"""
	if mode not in MODES:
		frappe.throw(f"Modo inválido '{mode}'. Use uno de {MODES}.")

	cases = _filter(parser.dedupe(parser.load_cases(path, sheet)), only=only, limit=limit)
	summary = parser.summarize(cases)
	result = {"mode": mode, "summary": summary}

	if mode == "parse":
		result["cases"] = [
			{"encf": case["encf"], "tipo": case["tipo"], "lines": len(importer._line_numbers(case))}
			for case in cases
		]
		return result

	report = importer.import_cases(cases, company=company, reset=bool(reset))
	by_encf = {case["encf"]: case for case in cases}

	for entry in report:
		if not entry["invoice"]:
			continue
		if mode == "reconcile":
			entry["mismatches"] = reconcile_case(by_encf[entry["encf"]], entry["invoice"])
		elif mode == "xml":
			if case_builder := by_encf.get(entry["encf"]):
				entry.update(_xml_check(case_builder, entry["invoice"]))

	result["report"] = report
	result["created"] = sum(1 for entry in report if entry["invoice"])
	result["failed"] = sum(1 for entry in report if entry["error"])
	if mode in ("reconcile", "xml"):
		result["mismatched"] = sum(1 for entry in report if entry.get("mismatches"))
	return result

