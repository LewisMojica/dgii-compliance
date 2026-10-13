import frappe
from lxml import etree

from .builders import (
	BUILDERS,
	build_xml_ecf_E31,
	build_xml_ecf_E32,
	build_xml_ecf_E43,
	build_xml_ecf_E44,
	build_xml_ecf_E45,
	build_xml_ecf_E46,
)
from .signer import sign_ecf

__all__ = [
	"validate_xml_schema",
	"new_ecf",
	"build_xml_ecf_E31",
	"build_xml_ecf_E32",
	"build_xml_ecf_E43",
	"build_xml_ecf_E44",
	"build_xml_ecf_E45",
	"build_xml_ecf_E46",
	"build_xml_rfce",
	"compute_security_code",
	"DS_NS",
]


def validate_xml_schema(xml_object, eNCF_type, raise_on_error=False):
	"""Validates an XML document against the XSD for its type.

	``eNCF_type`` is an e-CF type (``E31``..``E47``) or ``ACECF`` (Aprobación
	Comercial). Returns True when valid. When invalid, returns False, or raises
	with the schema errors if ``raise_on_error`` is set.
	"""
	xsd_name_map = {
		"ACECF": "ACECF v.1.0.xsd",
		"E31": "e-CF 31 v.1.0.xsd",
		"E32": "e-CF 32 v.1.0.xsd",
		"E33": "e-CF 33 v.1.0.xsd",
		"E34": "e-CF 34 v.1.0.xsd",
		"E41": "e-CF 41 v.1.0.xsd",
		"E43": "e-CF 43 v.1.0.xsd",
		"E44": "e-CF 44 v.1.0.xsd",
		"E45": "e-CF 45 v.1.0.xsd",
		"E46": "e-CF 46 v.1.0.xsd",
		"E47": "e-CF 47 v.1.0.xsd",
	}
	xsd_path = frappe.get_app_path("dgii_compliance", "dgii_compliance") + "/xsd/" + xsd_name_map[eNCF_type]
	with open(xsd_path, "rb") as xsd_file:
		schema = etree.XMLSchema(etree.fromstring(xsd_file.read()))

	if schema.validate(xml_object):
		return True

	errors = " | ".join(f"Línea {e.line}: {e.message}" for e in schema.error_log) or "desconocido"
	if raise_on_error:
		frappe.throw(f"El XML {eNCF_type} no cumple el esquema: {errors}")
	return False


def new_ecf(doc, eNCF_type):
	"""Creates a new eCF document from ``doc`` for the given e-NCF type.

	Builds the XML, signs it, validates it against the type's XSD and stores it
	as an ``eCF`` document linked to ``doc``.
	"""
	if eNCF_type not in BUILDERS:
		frappe.throw(f"No existe un generador XML para el tipo de eNCF {eNCF_type}")

	xml_object = BUILDERS[eNCF_type](doc)
	signed_xml_object = sign_ecf(xml_object)

	validate_xml_schema(signed_xml_object, eNCF_type, raise_on_error=True)

	xml_string = etree.tostring(
		signed_xml_object, encoding="utf-8", xml_declaration=True
	).decode("utf-8")

	ecf = frappe.get_doc(
		{
			"doctype": "eCF",
			"ref_doctype": doc.doctype,
			"ref_name": doc.name,
			"xml": xml_string,
		}
	)
	ecf.insert()
	return ecf


DS_NS = "http://www.w3.org/2000/09/xmldsig#"


def compute_security_code(signature_value):
	"""First 6 characters of the e-CF's ``SignatureValue``.

	Used as ``CodigoSeguridadeCF`` in the RFCE (Resumen). DGII cross-checks it
	against the first 6 characters of the signature of the full e-CF, so it must
	be the raw signature prefix (not a hash of it).
	"""
	if not signature_value:
		return None
	return signature_value[:6]


def build_xml_rfce(signed_ecf_root):
	"""Builds an RFCE (Resumen Factura de Consumo < RD$250,000) from a signed e-CF.

	DGII does not receive the full e-CF for consumption invoices below
	RD$250,000; it receives this summary instead, carrying the original e-CF's
	``CodigoSeguridadeCF``.
	"""
	encabezado_src = signed_ecf_root.find("Encabezado")

	ns_map = {"xsi": "http://www.w3.org/2001/XMLSchema-instance"}
	rfce = etree.Element("RFCE", nsmap=ns_map)
	encabezado = etree.SubElement(rfce, "Encabezado")
	etree.SubElement(encabezado, "Version").text = "1.0"

	iddoc = etree.SubElement(encabezado, "IdDoc")
	src_iddoc = encabezado_src.find("IdDoc")
	for tag in ("TipoeCF", "eNCF", "TipoIngresos", "TipoPago"):
		value = src_iddoc.findtext(tag)
		if value is not None:
			etree.SubElement(iddoc, tag).text = value

	emisor = etree.SubElement(encabezado, "Emisor")
	src_emisor = encabezado_src.find("Emisor")
	for tag in ("RNCEmisor", "RazonSocialEmisor", "FechaEmision"):
		etree.SubElement(emisor, tag).text = src_emisor.findtext(tag)

	src_comprador = encabezado_src.find("Comprador")
	if src_comprador is not None and len(src_comprador):
		comprador = etree.SubElement(encabezado, "Comprador")
		for tag in ("RNCComprador", "IdentificadorExtranjero", "RazonSocialComprador"):
			value = src_comprador.findtext(tag)
			if value:
				etree.SubElement(comprador, tag).text = value

	totales = etree.SubElement(encabezado, "Totales")
	src_totales = encabezado_src.find("Totales")
	for tag in (
		"MontoGravadoTotal",
		"MontoGravadoI1",
		"MontoGravadoI2",
		"MontoGravadoI3",
		"MontoExento",
		"TotalITBIS",
		"TotalITBIS1",
		"TotalITBIS2",
		"TotalITBIS3",
		"MontoImpuestoAdicional",
		"MontoTotal",
	):
		value = src_totales.findtext(tag)
		if value is not None:
			etree.SubElement(totales, tag).text = value

	signature_value = signed_ecf_root.findtext(f".//{{{DS_NS}}}SignatureValue")
	etree.SubElement(encabezado, "CodigoSeguridadeCF").text = compute_security_code(signature_value)

	return rfce
