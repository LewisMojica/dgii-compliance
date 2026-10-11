"""E31 - Factura de Crédito Fiscal Electrónica."""

import datetime

import frappe
from lxml import etree

from .common import (
	NSMAP,
	append_detalles_items,
	append_totales,
	compute_dgii_tax_totals,
	format_dgii_date,
	get_comprador_rnc,
)


def build(doc):
	"""Builds the XML for an E31 (Factura de Crédito Fiscal Electrónica).

	E31 requires IdDoc/FechaVencimientoSecuencia and the buyer's
	RNCComprador/RazonSocialComprador, both mandatory in the E31 XSD.
	"""
	tax_totals = compute_dgii_tax_totals(doc)

	ecf_root = etree.Element("ECF", nsmap=NSMAP)

	encabezado = etree.SubElement(ecf_root, "Encabezado")
	etree.SubElement(encabezado, "Version").text = "1.0"

	# --- IdDoc Section ---
	iddoc = etree.SubElement(encabezado, "IdDoc")
	etree.SubElement(iddoc, "TipoeCF").text = "31"
	etree.SubElement(iddoc, "eNCF").text = doc.custom_ncf
	etree.SubElement(iddoc, "FechaVencimientoSecuencia").text = format_dgii_date(doc.custom_ncf_vencimiento)
	if tax_totals["monto_gravado_total"] > 0:
		# 1 when line amounts already include ITBIS, 0 when it is added on top
		etree.SubElement(iddoc, "IndicadorMontoGravado").text = "1" if tax_totals["itbis_incluido"] else "0"
	etree.SubElement(iddoc, "TipoIngresos").text = "01"
	etree.SubElement(iddoc, "TipoPago").text = "1"

	# --- Emisor Section ---
	emisor = etree.SubElement(encabezado, "Emisor")
	etree.SubElement(emisor, "RNCEmisor").text = doc.company_tax_id
	etree.SubElement(emisor, "RazonSocialEmisor").text = doc.company
	etree.SubElement(emisor, "DireccionEmisor").text = doc.company_address_display
	etree.SubElement(emisor, "FechaEmision").text = datetime.datetime.today().strftime("%d-%m-%Y")

	# --- Comprador Section ---
	comprador_rnc = get_comprador_rnc(doc)
	if not comprador_rnc:
		frappe.throw(
			"El RNC del comprador es requerido para la Factura de Crédito "
			"Fiscal Electrónica (E31). Verifique el RNC del cliente."
		)
	comprador = etree.SubElement(encabezado, "Comprador")
	etree.SubElement(comprador, "RNCComprador").text = comprador_rnc
	etree.SubElement(comprador, "RazonSocialComprador").text = doc.customer_name

	# --- Totales Section ---
	append_totales(encabezado, doc, tax_totals)

	# --- DetallesItems ---
	append_detalles_items(ecf_root, doc, tax_totals)

	# --- Footer & Signature ---
	current_time = datetime.datetime.now().strftime("%d-%m-%Y %H:%M:%S")
	etree.SubElement(ecf_root, "FechaHoraFirma").text = current_time

	return ecf_root
