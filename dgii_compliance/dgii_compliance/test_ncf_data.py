# Copyright (c) 2026, Lewis Mojica and Contributors
# See license.txt

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from dgii_compliance.dgii_compliance import add_ncf_data


def _invoice(**overrides):
	values = {
		"doctype": "Sales Invoice",
		"name": "ACC-SINV-2026-00001",
		"amended_from": None,
		"customer": "CUST-001",
		"is_pos": 0,
		"is_consolidated": 0,
		"custom_factura_de_valor_fiscal": 1,
		"custom_ncf": None,
		"custom_ncf_vencimiento": None,
		"custom_ecf_type": None,
		"custom_ecf_certification": 0,
	}
	values.update(overrides)
	return frappe._dict(values)


def _sequence_get_value(original_ncf=None, next_ncf=5):
	def fake_get_value(doctype, name=None, field=None, *args, **kwargs):
		if doctype == "Sales Invoice" and field == "custom_ncf":
			return original_ncf
		if doctype != "Secuencia NCF":
			return None
		if field == "end":
			return 10
		if field == "next_ncf":
			return next_ncf
		if field == "start":
			return 1
		if field == "expiration_date":
			return None
		if isinstance(field, list):
			return frappe._dict(end=10, next_ncf=next_ncf, start=1)
		return None

	return fake_get_value


class TestNCFData(FrappeTestCase):
	def _run(self, doc, method="NCF", reuse=True, original_ncf=None, next_ncf=5):
		with (
			patch.object(add_ncf_data, "_get_invoicing_method", return_value=method),
			patch.object(add_ncf_data, "_reuse_ncf_on_amendment", return_value=reuse),
			patch.object(
				add_ncf_data.frappe,
				"get_doc",
				return_value=frappe._dict(customer_type="Company", customer_group=""),
			),
			patch.object(add_ncf_data.frappe, "get_all", return_value=["NCF-SEQ-1"]),
			patch.object(
				add_ncf_data.frappe.db,
				"get_value",
				side_effect=_sequence_get_value(original_ncf, next_ncf),
			),
			patch.object(add_ncf_data.frappe.db, "set_value"),
			patch.object(add_ncf_data, "get_ncf_type", return_value="B01"),
			patch.object(add_ncf_data, "new_ecf") as new_ecf,
		):
			add_ncf_data.main(doc, None)
		return new_ecf

	def test_reuses_original_ncf_for_amended_ncf_invoice(self):
		doc = _invoice(
			name="ACC-SINV-2026-00001-1",
			amended_from="ACC-SINV-2026-00001",
		)
		new_ecf = self._run(doc, method="NCF", reuse=True, original_ncf="B0100000001")
		self.assertEqual(doc.custom_ncf, "B0100000001")
		new_ecf.assert_not_called()

	def test_assigns_new_ncf_when_reuse_setting_is_disabled(self):
		doc = _invoice(
			name="ACC-SINV-2026-00001-1",
			amended_from="ACC-SINV-2026-00001",
		)
		new_ecf = self._run(
			doc, method="NCF", reuse=False, original_ncf="B0100000001", next_ncf=5
		)
		self.assertEqual(doc.custom_ncf, "B0100000005")
		new_ecf.assert_not_called()

	def test_amended_ecf_never_reuses_the_original_enCf(self):
		doc = _invoice(
			name="ACC-SINV-2026-00001-1",
			amended_from="ACC-SINV-2026-00001",
			custom_ncf="E310000000099",
			custom_ecf_type="E31",
		)
		new_ecf = self._run(doc, method="eNCF", reuse=True, original_ncf="E310000000099", next_ncf=1)
		self.assertEqual(doc.custom_ncf, "E310000000001")
		new_ecf.assert_called_once()

	def test_ncf_mode_ignores_ecf_fields(self):
		doc = _invoice(
			name="ACC-SINV-2026-00002",
			custom_ecf_type="E31",
			custom_ecf_certification=1,
		)
		new_ecf = self._run(doc, method="NCF", reuse=True, next_ncf=7)
		self.assertEqual(doc.custom_ncf, "B0100000007")
		new_ecf.assert_not_called()
