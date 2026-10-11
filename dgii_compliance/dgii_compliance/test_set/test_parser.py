# Copyright (c) 2026, Lewis Mojica and contributors
# See license.txt

import os
import tempfile
import unittest

import frappe
import openpyxl
from frappe.tests.utils import FrappeTestCase

from dgii_compliance.dgii_compliance.test_set import mapping, parser

HEADER = [
	"CasoPrueba",
	"TipoeCF",
	"ENCF",
	"MontoTotal",
	"RazonSocialEmisor",
	"TelefonoEmisor[1]",
	"TelefonoEmisor[2]",
	"NumeroLinea[1]",
	"NombreItem[1]",
	"CantidadItem[1]",
	"PrecioUnitarioItem[1]",
	"TipoCodigo[1][1]",
	"CodigoItem[1][1]",
	"TipoSubDescuento[1][1]",
	"MontoSubDescuento[1][1]",
	"NumeroLinea[2]",
	"NombreItem[2]",
	"CantidadItem[2]",
	"PrecioUnitarioItem[2]",
]

ROW = [
	"133424959E310000000001",
	31,
	"E310000000001",
	"1180.00",
	"EMISOR DE PRUEBA",
	"809-472-7676",
	"#e",
	1,
	"GALLETAS",
	"1.00",
	"1000.00",
	"Interno",
	"ITEM-1",
	"$",
	"500.00",
	2,
	"AGUA",
	"2.00",
	"90.00",
]


def _write_workbook(rows):
	wb = openpyxl.Workbook()
	ws = wb.active
	ws.title = "ECF"
	ws.append(HEADER)
	for row in rows:
		ws.append(row)
	path = os.path.join(tempfile.mkdtemp(), "test_set.xlsx")
	wb.save(path)
	return path


class TestParser(unittest.TestCase):
	def test_normalizes_header_indexed_and_sub_groups(self):
		case = parser.parse_workbook(_write_workbook([ROW]))[0]

		self.assertEqual(case["tipo"], "E31")
		self.assertEqual(case["encf"], "E310000000001")
		self.assertEqual(case["header"]["RazonSocialEmisor"], "EMISOR DE PRUEBA")
		self.assertNotIn("TelefonoEmisor[2]", case["header"])  # '#e' dropped

		self.assertEqual(case["indexed"]["TelefonoEmisor"], {1: "809-472-7676"})
		self.assertEqual(case["indexed"]["NombreItem"], {1: "GALLETAS", 2: "AGUA"})
		self.assertEqual(case["sub"]["CodigoItem"], {1: {1: "ITEM-1"}})
		self.assertEqual(case["sub"]["MontoSubDescuento"], {1: {1: "500.00"}})

	def test_dedupe_keeps_first_encf(self):
		cases = parser.parse_workbook(_write_workbook([ROW, ROW]))
		self.assertEqual(len(cases), 2)
		self.assertEqual(len(parser.dedupe(cases)), 1)

	def test_load_cases_cache_round_trip(self):
		path = _write_workbook([ROW])
		parser.load_cases(path)  # writes the JSON cache
		self.assertTrue(os.path.exists(parser._cache_path(path, "ECF")))
		case = parser.load_cases(path)[0]  # reads the cache
		self.assertEqual(case["encf"], "E310000000001")
		# integer keys survive the JSON round-trip
		self.assertIn(1, case["indexed"]["NombreItem"])
		self.assertIn(1, case["sub"]["CodigoItem"])

	def test_needs_rfce_only_for_small_e32(self):
		small = {"tipo": "E32", "header": {"MontoTotal": "100000.00"}}
		large = {"tipo": "E32", "header": {"MontoTotal": "300000.00"}}
		other = {"tipo": "E31", "header": {"MontoTotal": "100000.00"}}
		self.assertTrue(parser.needs_rfce(small))
		self.assertFalse(parser.needs_rfce(large))
		self.assertFalse(parser.needs_rfce(other))

	def test_summarize(self):
		cases = parser.parse_workbook(_write_workbook([ROW]))
		summary = parser.summarize(cases)
		self.assertEqual(summary["total"], 1)
		self.assertEqual(summary["by_type"], {"E31": 1})

	def test_ever_sent(self):
		from dgii_compliance.dgii_compliance.test_set import importer

		self.assertFalse(importer._ever_sent({"status": "pending"}))
		self.assertFalse(importer._ever_sent({}))
		self.assertTrue(importer._ever_sent({"status": "accepted"}))
		self.assertTrue(importer._ever_sent({"status": "rejected"}))
		self.assertTrue(importer._ever_sent({"status": "pending", "track_id": "t"}))
		self.assertTrue(importer._ever_sent({"status": None, "sent_at": "2026-10-10"}))


class TestMappingTargets(FrappeTestCase):
	def test_header_targets_exist(self):
		fields = {df.fieldname for df in frappe.get_meta("Sales Invoice").fields}
		for column, (fieldname, _kind) in mapping.HEADER_MAP.items():
			if fieldname == "skip":
				continue
			self.assertIn(fieldname, fields, f"{column} -> {fieldname}")

	def test_item_targets_exist(self):
		fields = {df.fieldname for df in frappe.get_meta("eCF Detalle Item").fields}
		for column, (fieldname, _kind) in mapping.ITEM_SCALARS.items():
			self.assertIn(fieldname, fields, f"{column} -> {fieldname}")

	def test_child_group_targets_exist(self):
		checks = {
			"eCF Codigo Item": mapping.CODIGO_GROUP,
			"eCF Sub Descuento": mapping.SUBDESCUENTO_GROUP,
			"eCF Sub Recargo": mapping.SUBRECARGO_GROUP,
			"eCF Forma de Pago": mapping.PAYMENT_FIELDS,
		}
		for doctype, group in checks.items():
			fields = {df.fieldname for df in frappe.get_meta(doctype).fields}
			for fieldname in group.values():
				self.assertIn(fieldname, fields, f"{doctype} -> {fieldname}")
