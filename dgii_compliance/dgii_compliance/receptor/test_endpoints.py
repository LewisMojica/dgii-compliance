# Copyright (c) 2026, Lewis Mojica and Contributors
# See license.txt

import unittest
from unittest.mock import patch

from frappe.tests.utils import FrappeTestCase
from lxml import etree

from dgii_compliance.dgii_compliance.doctype.ecf.signer import sign_xml
from dgii_compliance.dgii_compliance.doctype.ecf.test_ecf import generate_key_and_cert
from dgii_compliance.dgii_compliance.receptor import endpoints
from dgii_compliance.dgii_compliance.receptor.page_renderer import ReceptorPageRenderer

ECF = (
	b"<ECF><Encabezado><IdDoc><TipoeCF>31</TipoeCF><eNCF>E310000004001</eNCF></IdDoc>"
	b"<Emisor><RNCEmisor>131880681</RNCEmisor></Emisor>"
	b"<Comprador><RNCComprador>133424959</RNCComprador></Comprador></Encabezado></ECF>"
)


def _signed_ecf():
	key_pem, cert_pem = generate_key_and_cert()
	signed = sign_xml(etree.fromstring(ECF), key_pem, cert_pem)
	return etree.tostring(signed)


class TestReceptor(unittest.TestCase):
	def test_verify_signature(self):
		self.assertTrue(endpoints._verify_signature(etree.fromstring(_signed_ecf())))

	def test_verify_signature_rejects_tampered(self):
		root = etree.fromstring(_signed_ecf())
		root.find(".//RNCEmisor").text = "999999999"
		self.assertFalse(endpoints._verify_signature(root))

	def test_renderer_can_render(self):
		self.assertTrue(ReceptorPageRenderer("fe/recepcion/api/ecf").can_render())
		self.assertTrue(ReceptorPageRenderer("fe/aprobacioncomercial/api/ecf").can_render())
		self.assertFalse(ReceptorPageRenderer("api/method/other").can_render())


class TestProcessRecepcion(FrappeTestCase):
	def test_accepts_valid_signed_ecf(self):
		raw = _signed_ecf()
		with patch.object(endpoints, "get_xml_schema_errors", return_value=[]), patch.object(
			endpoints.arecf, "build_signed", return_value="<ARECF/>"
		):
			result = endpoints.process_recepcion(raw)
		self.assertEqual(result["estado"], 0)
		self.assertEqual(result["encf"], "E310000004001")
		self.assertEqual(result["arecf"], "<ARECF/>")
		self.assertTrue(result["signature_ok"])

	def test_rejects_bad_signature(self):
		root = etree.fromstring(_signed_ecf())
		root.find(".//RNCEmisor").text = "999999999"
		with patch.object(endpoints, "get_xml_schema_errors", return_value=[]), patch.object(
			endpoints.arecf, "build_signed", return_value="<ARECF/>"
		):
			result = endpoints.process_recepcion(etree.tostring(root))
		self.assertEqual(result["estado"], 1)
		self.assertEqual(result["motivo"], 2)
		self.assertFalse(result["signature_ok"])
		self.assertTrue(result["signature_error"])

	def test_soft_signature_accepts_when_enabled(self):
		root = etree.fromstring(_signed_ecf())
		root.find(".//RNCEmisor").text = "999999999"
		with (
			patch.object(endpoints, "get_xml_schema_errors", return_value=[]),
			patch.object(endpoints, "_conf_flag", return_value=True),
			patch.object(endpoints.arecf, "build_signed", return_value="<ARECF/>"),
		):
			result = endpoints.process_recepcion(etree.tostring(root))
		self.assertEqual(result["estado"], 0)
		self.assertTrue(result["soft_signature"])
		self.assertFalse(result["signature_ok"])

	def test_uses_configured_receptor_rnc_when_buyer_missing(self):
		root = etree.fromstring(ECF)
		buyer = root.find(".//RNCComprador")
		buyer.getparent().remove(buyer)
		root.find(".//RNCEmisor").text = "131880682"
		root.find(".//eNCF").text = "E310000004099"
		key_pem, cert_pem = generate_key_and_cert()
		raw = etree.tostring(sign_xml(root, key_pem, cert_pem))
		with (
			patch.object(endpoints, "get_xml_schema_errors", return_value=[]),
			patch.object(endpoints, "_receptor_rnc", return_value="133424959"),
			patch.object(endpoints.arecf, "build_signed", return_value="<ARECF/>") as build,
		):
			result = endpoints.process_recepcion(raw)
		self.assertEqual(result["estado"], 0)
		self.assertEqual(result["rnc_comprador"], "")
		self.assertEqual(result["rnc_receptor"], "133424959")
		build.assert_called_once()
		self.assertEqual(build.call_args.args[2], "133424959")

	def test_rejects_duplicate(self):
		frappe_doc = endpoints.frappe.get_doc(
			{
				"doctype": "eCF",
				"direction": "Recibido",
				"rnc_emisor": "131880681",
				"rnc_comprador": "133424959",
				"encf": "E310000004001",
				"status": "accepted",
				"xml": "<ECF/>",
			}
		)
		frappe_doc.insert(ignore_permissions=True)
		with patch.object(endpoints, "get_xml_schema_errors", return_value=[]), patch.object(
			endpoints.arecf, "build_signed", return_value="<ARECF/>"
		):
			result = endpoints.process_recepcion(_signed_ecf())
		self.assertEqual(result["estado"], 1)
		self.assertEqual(result["motivo"], 3)
