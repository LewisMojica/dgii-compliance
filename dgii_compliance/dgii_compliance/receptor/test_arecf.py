# Copyright (c) 2026, Lewis Mojica and Contributors
# See license.txt

from frappe.tests.utils import FrappeTestCase
from lxml import etree

from dgii_compliance.dgii_compliance.doctype.ecf.new_ecf import validate_xml_schema
from dgii_compliance.dgii_compliance.receptor import arecf

DS_SIGNATURE = "{http://www.w3.org/2000/09/xmldsig#}Signature"


class TestArecfBuilder(FrappeTestCase):
	def _validate(self, xml):
		etree.SubElement(xml, DS_SIGNATURE)
		self.assertTrue(validate_xml_schema(xml, "ARECF"))

	def test_recibido(self):
		xml = arecf.build("131880681", "E310000004001", "133424959")
		detalle = xml.find("DetalleAcusedeRecibo")
		self.assertEqual(xml.tag, "ARECF")
		self.assertEqual(detalle.findtext("Version"), "1.0")
		self.assertEqual(detalle.findtext("RNCEmisor"), "131880681")
		self.assertEqual(detalle.findtext("RNCComprador"), "133424959")
		self.assertEqual(detalle.findtext("eNCF"), "E310000004001")
		self.assertEqual(detalle.findtext("Estado"), "0")
		self.assertIsNone(detalle.find("CodigoMotivoNoRecibido"))
		self.assertIsNotNone(detalle.findtext("FechaHoraAcuseRecibo"))
		self._validate(xml)

	def test_no_recibido_requires_motivo(self):
		xml = arecf.build(
			"131880681", "E310000004001", "133424959", estado=1, motivo=arecf.MOTIVO_ERROR_FIRMA
		)
		detalle = xml.find("DetalleAcusedeRecibo")
		self.assertEqual(detalle.findtext("Estado"), "1")
		self.assertEqual(detalle.findtext("CodigoMotivoNoRecibido"), "2")
		self._validate(xml)
