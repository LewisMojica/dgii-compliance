# Copyright (c) 2026, Lewis Mojica and Contributors
# See license.txt

from frappe.tests.utils import FrappeTestCase
from lxml import etree

from dgii_compliance.dgii_compliance.doctype.ecf.new_ecf import validate_xml_schema
from dgii_compliance.dgii_compliance.doctype.ecf_aprobacion_comercial.acecf import (
	build,
	extract_rnc_and_encf,
)

DS_SIGNATURE = "{http://www.w3.org/2000/09/xmldsig#}Signature"


class _Doc:
	def __init__(self, **kw):
		self.__dict__.update(kw)


class TestAcecfBuilder(FrappeTestCase):
	def _doc(self, **overrides):
		values = {
			"rnc_emisor": "131880681",
			"encf": "E310000000008",
			"fecha_emision": "01-04-2020",
			"monto_total": 1505.0,
			"rnc_comprador": "133424959",
			"estado_acecf": "1",
			"detalle_motivo_rechazo": None,
			"fecha_hora_aprobacion_comercial": "12-10-2026 00:49:54",
		}
		values.update(overrides)
		return _Doc(**values)

	def _validate(self, xml):
		etree.SubElement(xml, DS_SIGNATURE)
		self.assertTrue(validate_xml_schema(xml, "ACECF"))

	def test_structure_matches_spec(self):
		xml = build(self._doc())
		detalle = xml.find("DetalleAprobacionComercial")

		self.assertEqual(xml.tag, "ACECF")
		self.assertEqual(detalle.findtext("Version"), "1.0")
		self.assertEqual(detalle.findtext("RNCEmisor"), "131880681")
		self.assertEqual(detalle.findtext("eNCF"), "E310000000008")
		self.assertEqual(detalle.findtext("FechaEmision"), "01-04-2020")
		self.assertEqual(detalle.findtext("MontoTotal"), "1505.00")
		self.assertEqual(detalle.findtext("RNCComprador"), "133424959")
		self.assertEqual(detalle.findtext("Estado"), "1")
		self.assertIsNone(detalle.find("DetalleMotivoRechazo"))
		self.assertEqual(detalle.findtext("FechaHoraAprobacionComercial"), "12-10-2026 00:49:54")
		self._validate(xml)

	def test_monto_total_forces_two_decimals(self):
		xml = build(self._doc(monto_total=96365.3))
		self.assertEqual(xml.findtext("DetalleAprobacionComercial/MontoTotal"), "96365.30")
		self._validate(xml)

	def test_monto_total_zero_is_emitted(self):
		xml = build(self._doc(monto_total=0))
		self.assertEqual(xml.findtext("DetalleAprobacionComercial/MontoTotal"), "0.00")
		self._validate(xml)

	def test_rejection_includes_motive(self):
		xml = build(self._doc(estado_acecf="2", detalle_motivo_rechazo="No conforme"))
		self.assertEqual(xml.findtext("DetalleAprobacionComercial/Estado"), "2")
		self.assertEqual(
			xml.findtext("DetalleAprobacionComercial/DetalleMotivoRechazo"), "No conforme"
		)
		self._validate(xml)

	def test_extract_rnc_and_encf(self):
		xml = etree.tostring(build(self._doc()))
		self.assertEqual(extract_rnc_and_encf(xml), ("133424959", "E310000000008"))
