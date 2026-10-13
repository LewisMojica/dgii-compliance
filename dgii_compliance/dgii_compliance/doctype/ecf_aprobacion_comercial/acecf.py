"""ACECF - Aprobación o Rechazo Comercial (respuesta del receptor a un e-CF).

The root element follows ``ACECF v.1.0.xsd``:

	<ACECF>
	  <DetalleAprobacionComercial>
	    <Version>1.0</Version>
	    <RNCEmisor/>
	    <eNCF/>
	    <FechaEmision/>
	    <MontoTotal/>
	    <RNCComprador/>
	    <Estado/>
	    <DetalleMotivoRechazo/>            (solo si Estado = 2)
	    <FechaHoraAprobacionComercial/>
	  </DetalleAprobacionComercial>
	  <Signature/>                         (firma digital enveloped)
	</ACECF>

DGII receives it through the ``/aprobacioncomercial`` service and replies with
``<RespuestaAprobacionComercial>`` (mensaje/estado/codigo), not a TrackId.
"""

import frappe
from frappe import _
from lxml import etree

from dgii_compliance.dgii_compliance.doctype.ecf.builders.common import (
	add,
	add_amount_force,
	add_int,
	format_dgii_date,
)
from dgii_compliance.dgii_compliance.doctype.ecf.new_ecf import validate_xml_schema
from dgii_compliance.dgii_compliance.doctype.ecf.signer import sign_ecf

DOCTYPE = "eCF Aprobacion Comercial"
SCHEMA_KEY = "ACECF"

# Once sent, the signed XML must not be regenerated (it would change the
# signature while DGII keeps the original).
SENT_STATUSES = ("sent", "ok", "error")


def build(doc):
	"""Builds the unsigned ACECF XML for ``doc``."""
	root = etree.Element("ACECF")
	detalle = etree.SubElement(root, "DetalleAprobacionComercial")
	add(detalle, "Version", "1.0")
	add(detalle, "RNCEmisor", doc.rnc_emisor)
	add(detalle, "eNCF", doc.encf)
	add(detalle, "FechaEmision", format_dgii_date(doc.fecha_emision))
	add_amount_force(detalle, "MontoTotal", doc.monto_total)
	add(detalle, "RNCComprador", doc.rnc_comprador)
	add_int(detalle, "Estado", doc.estado_acecf)
	# Conditional: only present when Estado = 2 (Rechazado).
	add(detalle, "DetalleMotivoRechazo", doc.detalle_motivo_rechazo)
	add(detalle, "FechaHoraAprobacionComercial", doc.fecha_hora_aprobacion_comercial)
	return root


def sign_and_validate(doc):
	"""Builds, signs and XSD-validates the ACECF, returning the XML string."""
	signed = sign_ecf(build(doc))
	validate_xml_schema(signed, SCHEMA_KEY, raise_on_error=True)
	return etree.tostring(signed, encoding="utf-8", xml_declaration=True).decode("utf-8")


def extract_rnc_and_encf(xml):
	"""Returns (RNCComprador, eNCF) from a signed ACECF XML string."""
	root = etree.fromstring(xml.encode() if isinstance(xml, str) else xml)
	rnc = root.findtext(".//RNCComprador") or ""
	encf = root.findtext(".//eNCF") or ""
	return rnc.strip(), encf.strip()


@frappe.whitelist()
def generate_xml(name):
	"""Generates, signs and stores the XML for an ACECF document."""
	doc = frappe.get_doc(DOCTYPE, name)
	if doc.xml and doc.status in SENT_STATUSES:
		frappe.throw(_("La aprobación comercial ya fue enviada a DGII; no se regenera."))

	doc.xml = sign_and_validate(doc)
	doc.save(ignore_permissions=True)
	return {"xml": doc.xml}
