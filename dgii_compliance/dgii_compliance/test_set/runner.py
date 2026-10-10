"""Orchestrates parsing, invoice creation and reconciliation for the test set."""

import frappe

from dgii_compliance.dgii_compliance.test_set import importer, parser
from dgii_compliance.dgii_compliance.test_set.reconcile import reconcile_case

MODES = ("parse", "invoices", "reconcile")


def _filter(cases, only=None, limit=None):
	if only:
		wanted = {value.strip() for value in only.split(",")} if isinstance(only, str) else set(only)
		cases = [case for case in cases if case["encf"] in wanted]
	if limit:
		cases = cases[: int(limit)]
	return cases


@frappe.whitelist()
def run(path, sheet="ECF", mode="invoices", company=None, limit=None, only=None, reset=True):
	"""Parses ``path`` and (depending on ``mode``) creates/reconciles invoices.

	Modes:
		parse     -> only summarize the workbook
		invoices  -> create draft invoices
		reconcile -> create draft invoices and compare them to the workbook
	"""
	if mode not in MODES:
		frappe.throw(f"Modo inválido '{mode}'. Use uno de {MODES}.")

	cases = _filter(parser.dedupe(parser.parse_workbook(path, sheet)), only=only, limit=limit)
	summary = parser.summarize(cases)
	result = {"mode": mode, "summary": summary}

	if mode == "parse":
		result["cases"] = [
			{"encf": case["encf"], "tipo": case["tipo"], "lines": len(importer._line_numbers(case))}
			for case in cases
		]
		return result

	report = importer.import_cases(cases, company=company, reset=bool(reset))

	if mode == "reconcile":
		by_encf = {case["encf"]: case for case in cases}
		for entry in report:
			if not entry["invoice"]:
				continue
			entry["mismatches"] = reconcile_case(by_encf[entry["encf"]], entry["invoice"])

	result["report"] = report
	result["created"] = sum(1 for entry in report if entry["invoice"])
	result["failed"] = sum(1 for entry in report if entry["error"])
	if mode == "reconcile":
		result["mismatched"] = sum(1 for entry in report if entry.get("mismatches"))
	return result
