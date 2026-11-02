"""ARECF - Acuse de Recibo Electrónico.

The receptor returns this signed document in the HTTP response of the e-CF
reception service (``POST /fe/recepcion/api/ecf``).

	<ARECF>
	  <DetalleAcusedeRecibo>
	    <Version>1.0</Version>
	    <RNCEmisor/>              (the e-CF issuer)
	    <RNCComprador/>           (us, the receptor that issues the acuse)
	    <eNCF/>
	    <Estado/>                 0 = e-CF Recibido, 1 = e-CF No Recibido
	    <CodigoMotivoNoRecibido/> (solo si Estado = 1)
	    <FechaHoraAcuseRecibo/>
	  </DetalleAcusedeRecibo>
	  <Signature/>
	</ARECF>
"""

import datetime

from lxml import etree

from dgii_compliance.dgii_compliance.doctype.ecf.builders.common import add, add_int
from dgii_compliance.dgii_compliance.doctype.ecf.new_ecf import validate_xml_schema
from dgii_compliance.dgii_compliance.doctype.ecf.signer import sign_ecf

SCHEMA_KEY = "ARECF"

# CodigoMotivoNoRecibido (XSD): 1 especificación, 2 firma, 3 duplicado, 4 RNC.
MOTIVO_ERROR_ESPECIFICACION = 1
MOTIVO_ERROR_FIRMA = 2
MOTIVO_ENVIO_DUPLICADO = 3
MOTIVO_RNC_COMPRADOR = 4


def build(rnc_emisor, encf, rnc_comprador, estado=0, motivo=None, fecha_hora=None):
	"""Builds the unsigned ARECF."""
	root = etree.Element("ARECF")
	detalle = etree.SubElement(root, "DetalleAcusedeRecibo")
	add(detalle, "Version", "1.0")
	add(detalle, "RNCEmisor", rnc_emisor)
	add(detalle, "RNCComprador", rnc_comprador)
	add(detalle, "eNCF", encf)
	add_int(detalle, "Estado", estado)
	if int(estado) == 1 and motivo:
		add_int(detalle, "CodigoMotivoNoRecibido", motivo)
	add(
		detalle,
		"FechaHoraAcuseRecibo",
		fecha_hora or datetime.datetime.now().strftime("%d-%m-%Y %H:%M:%S"),
	)
	return root


def build_signed(rnc_emisor, encf, rnc_comprador, estado=0, motivo=None, fecha_hora=None):
	"""Builds, signs and XSD-validates the ARECF, returning the XML string."""
	signed = sign_ecf(
		build(rnc_emisor, encf, rnc_comprador, estado=estado, motivo=motivo, fecha_hora=fecha_hora)
	)
	validate_xml_schema(signed, SCHEMA_KEY, raise_on_error=True)
	return etree.tostring(signed, encoding="utf-8", xml_declaration=True).decode("utf-8")
