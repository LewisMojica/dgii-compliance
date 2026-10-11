"""E46 - Comprobante de Exportaciones Electrónico."""

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
	"""E46 Exportaciones: every line ITBIS tasa cero; RazonSocialComprador required."""
	tax_totals = compute_dgii_tax_totals(doc, forced_indicador="3")

	ecf_root = etree.Element("ECF", nsmap=NSMAP)
	encabezado = etree.SubElement(ecf_root, "Encabezado")
	etree.SubElement(encabezado, "Version").text = "1.0"

	iddoc = etree.SubElement(encabezado, "IdDoc")
	etree.SubElement(iddoc, "TipoeCF").text = "46"
	etree.SubElement(iddoc, "eNCF").text = doc.custom_ncf
	etree.SubElement(iddoc, "FechaVencimientoSecuencia").text = format_dgii_date(doc.custom_ncf_vencimiento)
	etree.SubElement(iddoc, "TipoIngresos").text = "01"
	etree.SubElement(iddoc, "TipoPago").text = "1"

	append_emisor(encabezado, doc)

	comprador = etree.SubElement(encabezado, "Comprador")
	comprador_rnc = get_comprador_rnc(doc)
	if comprador_rnc:
		etree.SubElement(comprador, "RNCComprador").text = comprador_rnc
	etree.SubElement(comprador, "RazonSocialComprador").text = doc.customer_name or "Consumidor Final"

	append_totales(encabezado, doc, tax_totals)
	append_detalles_items(ecf_root, doc, tax_totals)
	append_firma(ecf_root)
	return ecf_root
