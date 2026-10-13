# Copyright (c) 2026, Lewis Mojica and contributors
# See license.txt

import os
import tempfile
import unittest

import frappe
import openpyxl
from frappe.tests.utils import FrappeTestCase

from dgii_compliance.dgii_compliance.test_set import acecf

HEADER = [
	"Version",
	"RNCEmisor",
	"eNCF",
	"FechaEmision",
	"MontoTotal",
	"RNCComprador",
	"Estado",
	"DetalleMotivoRechazo",
	"FechaHoraAprobacionComercial",
]

ROW = [
	"1.0",
	"131880681",
	"E310000000008",
	"01-04-2020",
	1505,
	"133424959",
	1,
	None,
	"12-10-2026 00:49:54",
]

ROW_REJECTED = [
	"1.0",
	"131880681",
	"E330000000001",
	"02-04-2020",
	400000,
	"133424959",
	2,
	"No conforme",
	"12-10-2026 00:49:55",
]


def _write_workbook(rows):
	wb = openpyxl.Workbook()
	ws = wb.active
	ws.title = acecf.DEFAULT_SHEET
	ws.append(HEADER)
	for row in rows:
		ws.append(row)
	path = os.path.join(tempfile.mkdtemp(), "acecf_set.xlsx")
	wb.save(path)
	return path


class TestAcecfParser(unittest.TestCase):
	def test_load_cases(self):
		cases = acecf.load_cases(_write_workbook([ROW, ROW_REJECTED]))
		self.assertEqual(len(cases), 2)

		first = cases[0]
		self.assertEqual(first["RNCEmisor"], "131880681")
		self.assertEqual(first["eNCF"], "E310000000008")
		self.assertEqual(first["MontoTotal"], 1505)
		self.assertEqual(first["Estado"], 1)
		self.assertNotIn("DetalleMotivoRechazo", first)  # empty cells are dropped

		second = cases[1]
		self.assertEqual(second["Estado"], 2)
		self.assertEqual(second["DetalleMotivoRechazo"], "No conforme")

	def test_dedupe_by_rnc_and_encf(self):
		cases = acecf.load_cases(_write_workbook([ROW, ROW]))
		self.assertEqual(len(cases), 1)

	def test_summarize(self):
		cases = acecf.load_cases(_write_workbook([ROW, ROW_REJECTED]))
		summary = acecf.summarize(cases)
		self.assertEqual(summary, {"total": 2, "aprobados": 1, "rechazados": 1})

	def test_convert_code(self):
		self.assertEqual(acecf.convert(1, "code"), "1")
		self.assertEqual(acecf.convert("2", "code"), "2")
		self.assertEqual(acecf.convert(96365.3, "float"), 96365.3)


class TestAcecfImporter(FrappeTestCase):
	def _case(self, row=ROW):
		return acecf.load_cases(_write_workbook([row]))[0]

	def test_build_doc_maps_columns(self):
		doc = acecf.build_doc(self._case())
		self.assertEqual(doc.rnc_emisor, "131880681")
		self.assertEqual(doc.encf, "E310000000008")
		self.assertEqual(doc.fecha_emision, "01-04-2020")
		self.assertEqual(doc.monto_total, 1505)
		self.assertEqual(doc.rnc_comprador, "133424959")
		self.assertEqual(doc.estado_acecf, "1")
		self.assertEqual(doc.fecha_hora_aprobacion_comercial, "12-10-2026 00:49:54")

	def test_import_and_reconcile_case(self):
		case = self._case()
		name = acecf.import_case(case)
		self.assertEqual(acecf.reconcile_case(case, name), [])

	def test_reconcile_case_detects_mismatch(self):
		case = self._case()
		name = acecf.import_case(case)
		case["MontoTotal"] = 999999
		self.assertTrue(acecf.reconcile_case(case, name))

	def test_reconcile_xml(self):
		case = self._case()
		name = acecf.import_case(case)
		self.assertEqual(acecf.reconcile_xml(case, name), [])

	def test_reconcile_xml_flags_unexpected_motive(self):
		case = self._case()
		name = acecf.import_case(case)
		frappe.db.set_value(acecf.DOCTYPE, name, "detalle_motivo_rechazo", "Sobrante")
		mismatches = acecf.reconcile_xml(case, name)
		self.assertEqual(
			[m["field"] for m in mismatches],
			["DetalleMotivoRechazo (debe estar ausente)"],
		)

	def test_reset_refuses_sent(self):
		case = self._case()
		name = acecf.import_case(case)
		frappe.db.set_value(acecf.DOCTYPE, name, "status", "ok")
		with self.assertRaises(Exception):
			acecf.reset_case(case["RNCEmisor"], case["eNCF"])

	def test_column_targets_exist(self):
		fields = {df.fieldname for df in frappe.get_meta(acecf.DOCTYPE).fields}
		for _column, (fieldname, _kind) in acecf.COLUMN_MAP.items():
			self.assertIn(fieldname, fields, fieldname)
