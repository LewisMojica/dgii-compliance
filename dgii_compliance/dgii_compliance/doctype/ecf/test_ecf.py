# Copyright (c) 2025, Lewis Mojica and Contributors
# See license.txt

import datetime

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from frappe.tests.utils import FrappeTestCase
from lxml import etree

from dgii_compliance.dgii_compliance.doctype.ecf.new_ecf import (
	build_xml_rfce,
	compute_security_code,
)
from dgii_compliance.dgii_compliance.doctype.ecf.signer import (
	check_certificate_validity,
	sign_xml,
)

DS = {"ds": "http://www.w3.org/2000/09/xmldsig#"}


def generate_key_and_cert(valid_from_days=-1, valid_to_days=365):
	"""Generates a throwaway RSA key and self-signed certificate for tests."""
	key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
	name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "DGII Test")])
	now = datetime.datetime.now(datetime.timezone.utc)
	cert = (
		x509.CertificateBuilder()
		.subject_name(name)
		.issuer_name(name)
		.public_key(key.public_key())
		.serial_number(x509.random_serial_number())
		.not_valid_before(now + datetime.timedelta(days=valid_from_days))
		.not_valid_after(now + datetime.timedelta(days=valid_to_days))
		.sign(key, hashes.SHA256())
	)
	key_pem = key.private_bytes(
		serialization.Encoding.PEM,
		serialization.PrivateFormat.PKCS8,
		serialization.NoEncryption(),
	)
	return key_pem, cert.public_bytes(serialization.Encoding.PEM)


class TesteCF(FrappeTestCase):
	def test_signature_structure_matches_dgii_spec(self):
		key_pem, cert_pem = generate_key_and_cert()
		root = etree.fromstring(b"<ECF><Value>1</Value></ECF>")

		signed = sign_xml(root, key_pem, cert_pem)  # verifies the signature internally

		sig = signed.find("ds:Signature", DS)
		self.assertIsNotNone(sig)
		self.assertEqual(
			sig.find("ds:SignedInfo/ds:SignatureMethod", DS).get("Algorithm"),
			"http://www.w3.org/2001/04/xmldsig-more#rsa-sha256",
		)
		self.assertEqual(
			sig.find("ds:SignedInfo/ds:Reference/ds:DigestMethod", DS).get("Algorithm"),
			"http://www.w3.org/2001/04/xmlenc#sha256",
		)
		self.assertEqual(
			sig.find("ds:SignedInfo/ds:CanonicalizationMethod", DS).get("Algorithm"),
			"http://www.w3.org/TR/2001/REC-xml-c14n-20010315",
		)
		self.assertEqual(sig.find("ds:SignedInfo/ds:Reference", DS).get("URI"), "")
		self.assertIsNotNone(sig.find("ds:KeyInfo/ds:X509Data/ds:X509Certificate", DS))
		self.assertIsNone(sig.find("ds:KeyInfo/ds:KeyValue", DS))

	def test_expired_certificate_is_rejected(self):
		_, cert_pem = generate_key_and_cert(valid_from_days=-10, valid_to_days=-1)
		self.assertRaises(Exception, check_certificate_validity, cert_pem)

	def test_sign_xml_accepts_openssl_bag_attributes(self):
		key_pem, cert_pem = generate_key_and_cert()
		bagged_cert = b"Bag Attributes\n    localKeyID: 01\ntrusted: No\n" + cert_pem
		root = etree.fromstring(b"<ECF><Value>1</Value></ECF>")

		signed = sign_xml(root, key_pem, bagged_cert)

		self.assertIsNotNone(signed.find("ds:Signature", DS))

	def test_sign_xml_strips_insignificant_whitespace(self):
		key_pem, cert_pem = generate_key_and_cert()
		root = etree.fromstring(b"<ECF>\n  <Value>1</Value>\n  <Other>2</Other>\n</ECF>")

		signed = sign_xml(root, key_pem, cert_pem)

		for element in signed.iter():
			if not isinstance(element.tag, str):
				continue
			self.assertFalse(element.text and not element.text.strip())
			self.assertFalse(element.tail and not element.tail.strip())
		self.assertEqual(signed.findtext("Value"), "1")

	def test_compute_security_code_is_six_chars(self):
		code = compute_security_code("some-signature-value")
		self.assertEqual(len(code), 6)
		self.assertEqual(code, compute_security_code("some-signature-value"))

	def test_build_xml_rfce_from_signed_ecf(self):
		ecf = etree.fromstring(
			b"<ECF>"
			b"<Encabezado>"
			b"<IdDoc><TipoeCF>32</TipoeCF><eNCF>E320000000001</eNCF>"
			b"<IndicadorMontoGravado>0</IndicadorMontoGravado>"
			b"<TipoIngresos>01</TipoIngresos><TipoPago>1</TipoPago></IdDoc>"
			b"<Emisor><RNCEmisor>101010101</RNCEmisor>"
			b"<RazonSocialEmisor>Emisora</RazonSocialEmisor>"
			b"<FechaEmision>10-10-2026</FechaEmision></Emisor>"
			b"<Comprador><RazonSocialComprador>Consumidor Final</RazonSocialComprador></Comprador>"
			b"<Totales><MontoGravadoTotal>1000.00</MontoGravadoTotal>"
			b"<TotalITBIS>180.00</TotalITBIS><MontoTotal>1180.00</MontoTotal></Totales>"
			b"</Encabezado>"
			b'<ds:Signature xmlns:ds="http://www.w3.org/2000/09/xmldsig#">'
			b"<ds:SignatureValue>ABC123==</ds:SignatureValue></ds:Signature>"
			b"</ECF>"
		)

		rfce = build_xml_rfce(ecf)

		self.assertEqual(rfce.tag, "RFCE")
		self.assertEqual(rfce.findtext("Encabezado/IdDoc/TipoeCF"), "32")
		self.assertEqual(rfce.findtext("Encabezado/IdDoc/TipoPago"), "1")
		self.assertIsNone(rfce.find("Encabezado/IdDoc/IndicadorMontoGravado"))
		self.assertEqual(rfce.findtext("Encabezado/Totales/MontoTotal"), "1180.00")
		self.assertEqual(
			rfce.findtext("Encabezado/CodigoSeguridadeCF"),
			compute_security_code("ABC123=="),
		)
