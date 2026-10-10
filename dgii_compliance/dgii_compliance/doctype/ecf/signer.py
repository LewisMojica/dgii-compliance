import datetime

import frappe
from signxml import XMLSigner, XMLVerifier, methods
from cryptography.x509 import load_pem_x509_certificate


def get_dgii_file_path(file):
	return frappe.get_site_path("private", "files", "dgii_compliance", file)


def check_certificate_validity(cert_pem):
	"""Raises if the signing certificate is not currently valid."""
	cert = load_pem_x509_certificate(cert_pem)
	now = datetime.datetime.now(datetime.timezone.utc)
	not_before = getattr(cert, "not_valid_before_utc", None) or cert.not_valid_before
	not_after = getattr(cert, "not_valid_after_utc", None) or cert.not_valid_after

	if now < not_before:
		frappe.throw("El certificado digital aún no es válido.")
	if now > not_after:
		frappe.throw("El certificado digital está vencido.")


def build_signer():
	return XMLSigner(
		method=methods.enveloped,  # Exclude the signature from the hash
		signature_algorithm="rsa-sha256",
		digest_algorithm="sha256",
		c14n_algorithm="http://www.w3.org/TR/2001/REC-xml-c14n-20010315",
	)


def sign_xml(xml_root, key_pem, cert_pem):
	"""Signs an XML tree and verifies the resulting signature."""
	signed_xml_root = build_signer().sign(xml_root, key=key_pem, cert=cert_pem)
	XMLVerifier().verify(signed_xml_root, x509_cert=cert_pem)
	return signed_xml_root


def sign_ecf(xml_root):
	"""Signs the e-CF with the configured DGII key/certificate."""
	key_pem = open(get_dgii_file_path("key.pem"), "rb").read()
	cert_pem = open(get_dgii_file_path("certificate.pem"), "rb").read()

	check_certificate_validity(cert_pem)
	return sign_xml(xml_root, key_pem, cert_pem)
