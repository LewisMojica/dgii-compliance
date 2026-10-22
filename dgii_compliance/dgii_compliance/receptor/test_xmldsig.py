# Copyright (c) 2026, Lewis Mojica and Contributors
# See license.txt

from pathlib import Path
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from lxml import etree

from dgii_compliance.dgii_compliance.doctype.ecf.signer import sign_xml
from dgii_compliance.dgii_compliance.doctype.ecf.test_ecf import generate_key_and_cert
from dgii_compliance.dgii_compliance.doctype.ecf_aprobacion_comercial.acecf import build as build_acecf
from dgii_compliance.dgii_compliance.receptor import endpoints
from dgii_compliance.dgii_compliance.receptor.xmldsig import verify_signature

DGII_FIXTURE = Path(__file__).with_name("test_data") / "dgii_exclusive_c14n.xml"


class _Doc:
	def __init__(self, **kwargs):
		self.__dict__.update(kwargs)


class TestXmlDSigVerification(FrappeTestCase):
	def test_standard_signxml_signature(self):
		key_pem, cert_pem = generate_key_and_cert()
		signed = sign_xml(etree.fromstring(b"<ECF><Value>1</Value></ECF>"), key_pem, cert_pem)
		result = verify_signature(signed)
		self.assertTrue(result.ok)
		self.assertEqual(result.method, "signxml")

	def test_dgii_exclusive_c14n_signed_info_fallback(self):
		root = etree.parse(str(DGII_FIXTURE)).getroot()
		result = verify_signature(root)
		self.assertTrue(result.ok)
		self.assertEqual(result.method, "c14n-exclusive")

	def test_fallback_rejects_tampered_document(self):
		root = etree.parse(str(DGII_FIXTURE)).getroot()
		root.find(".//RazonSocialEmisor").text = "TAMPERED"
		result = verify_signature(root)
		self.assertFalse(result.ok)
		self.assertIn("digest", (result.error or "").lower())


class TestAprobacionProcessing(FrappeTestCase):
	def _signed_acecf(self, tamper=False):
		doc = _Doc(
			rnc_emisor="131880681",
			encf="E310000000008",
			fecha_emision="01-04-2020",
			monto_total=1505.0,
			rnc_comprador="133424959",
			estado_acecf="1",
			detalle_motivo_rechazo=None,
			fecha_hora_aprobacion_comercial="12-10-2026 00:49:54",
		)
		key_pem, cert_pem = generate_key_and_cert()
		root = sign_xml(build_acecf(doc), key_pem, cert_pem)
		if tamper:
			root.find("DetalleAprobacionComercial/MontoTotal").text = "9999.99"
		return etree.tostring(root)

	def test_accepts_valid_signed_acecf(self):
		result = endpoints.process_aprobacion(self._signed_acecf())
		self.assertTrue(result["ok"])
		self.assertEqual(result["signature_method"], "signxml")
		self.assertEqual(result["fields"]["encf"], "E310000000008")

	def test_soft_accepts_tampered_acecf_when_enabled(self):
		with patch.object(endpoints, "_soft_signature_enabled", return_value=True):
			result = endpoints.process_aprobacion(self._signed_acecf(tamper=True))
		self.assertTrue(result["ok"])
		self.assertTrue(result["soft_accepted"])
		self.assertEqual(result["signature_method"], "soft")
		self.assertFalse(result["signature_ok"])

	def test_rejects_tampered_acecf_when_soft_disabled(self):
		with patch.object(endpoints, "_soft_signature_enabled", return_value=False):
			result = endpoints.process_aprobacion(self._signed_acecf(tamper=True))
		self.assertFalse(result["ok"])
		self.assertFalse(result["signature_ok"])

	def test_stores_received_acecf(self):
		raw = self._signed_acecf()
		result = endpoints.process_aprobacion(raw)
		result["raw"] = raw
		name = endpoints._store_aprobacion(result)
		self.assertIsNotNone(name)

		doc = frappe.get_doc("eCF Aprobacion Comercial", name)
		self.assertEqual(doc.direction, "Recibido")
		self.assertEqual(doc.encf, "E310000000008")
		self.assertEqual(doc.rnc_emisor, "131880681")
		self.assertEqual(doc.rnc_comprador, "133424959")
		self.assertEqual(doc.status, "received")
		self.assertEqual(doc.verification_method, "signxml")
		self.assertIn("firma verificada", doc.respuesta_mensaje)
