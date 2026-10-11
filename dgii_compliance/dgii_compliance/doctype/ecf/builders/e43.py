"""E43 - Gastos Menores Electrónico."""

from lxml import etree

from .common import (
	NSMAP,
	append_detalles_items,
	append_emisor,
	append_firma,
	append_totales,
	compute_dgii_tax_totals,
	format_dgii_date,
)


def build(doc):
	"""E43 Gastos Menores: every line Exento, no Comprador, no TipoIngresos."""
	tax_totals = compute_dgii_tax_totals(doc, forced_indicador="4")

	ecf_root = etree.Element("ECF", nsmap=NSMAP)
	encabezado = etree.SubElement(ecf_root, "Encabezado")
	etree.SubElement(encabezado, "Version").text = "1.0"

	iddoc = etree.SubElement(encabezado, "IdDoc")
	etree.SubElement(iddoc, "TipoeCF").text = "43"
	etree.SubElement(iddoc, "eNCF").text = doc.custom_ncf
	etree.SubElement(iddoc, "FechaVencimientoSecuencia").text = format_dgii_date(doc.custom_ncf_vencimiento)
	etree.SubElement(iddoc, "TipoPago").text = "1"

	append_emisor(encabezado, doc)
	append_totales(encabezado, doc, tax_totals)
	append_detalles_items(ecf_root, doc, tax_totals)
	append_firma(ecf_root)
	return ecf_root
