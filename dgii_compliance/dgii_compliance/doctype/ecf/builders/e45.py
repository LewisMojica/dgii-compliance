"""E45 - Comprobante Gubernamental Electrónico."""

import frappe
from lxml import etree

from .common import (
	NSMAP,
	append_detalles_items,
	append_emisor,
	append_firma,
	append_totales,
	compute_dgii_tax_totals,
	format_dgii_date,
	get_comprador_rnc,
)


def build(doc):
	"""E45 Gubernamental: like E31 (gravado; RNCComprador + RazonSocial required)."""
	tax_totals = compute_dgii_tax_totals(doc)

	ecf_root = etree.Element("ECF", nsmap=NSMAP)
	encabezado = etree.SubElement(ecf_root, "Encabezado")
	etree.SubElement(encabezado, "Version").text = "1.0"

	iddoc = etree.SubElement(encabezado, "IdDoc")
	etree.SubElement(iddoc, "TipoeCF").text = "45"
	etree.SubElement(iddoc, "eNCF").text = doc.custom_ncf
	etree.SubElement(iddoc, "FechaVencimientoSecuencia").text = format_dgii_date(doc.custom_ncf_vencimiento)
	if tax_totals["monto_gravado_total"] > 0:
		etree.SubElement(iddoc, "IndicadorMontoGravado").text = "1" if tax_totals["itbis_incluido"] else "0"
	etree.SubElement(iddoc, "TipoIngresos").text = "01"
	etree.SubElement(iddoc, "TipoPago").text = "1"

	append_emisor(encabezado, doc)

	comprador_rnc = get_comprador_rnc(doc)
	if not comprador_rnc:
		frappe.throw(
			"El RNC del comprador es requerido para el Comprobante Gubernamental "
			"Electrónico (E45). Verifique el RNC del cliente."
		)
	comprador = etree.SubElement(encabezado, "Comprador")
	etree.SubElement(comprador, "RNCComprador").text = comprador_rnc
	etree.SubElement(comprador, "RazonSocialComprador").text = doc.customer_name

	append_totales(encabezado, doc, tax_totals)
	append_detalles_items(ecf_root, doc, tax_totals)
	append_firma(ecf_root)
	return ecf_root
