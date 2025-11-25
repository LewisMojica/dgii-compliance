import frappe
from lxml import etree
from signxml import XMLSigner, methods
import os

def get_dgii_file_path(file):
	return frappe.get_site_path("private", "files", "dgii_compliance",file)

def sign_ecf(xml_root):
	key_pem = open(get_dgii_file_path("key.pem"), "rb").read()
	cert_pem = open(get_dgii_file_path("certificate.pem"), "rb").read()
	signer = XMLSigner(
	method=methods.enveloped,  # Exclude the signature from the hash
	signature_algorithm="rsa-sha256",
	digest_algorithm="sha256",
	c14n_algorithm="http://www.w3.org/TR/2001/REC-xml-c14n-20010315"
	)

	signed_xml_root = signer.sign(
	xml_root,
	key=key_pem,
	cert=cert_pem
	)

	print(etree.tostring(signed_xml_root))
	return signed_xml_root

