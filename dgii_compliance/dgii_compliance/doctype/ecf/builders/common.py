"""Shared helpers for the per-type e-CF XML builders.

Only *pure* helpers live here (date formatting, tax math, value access and the
common `<Totales>` / `<DetallesItems>` emission). Each e-CF type owns its own
module and its own XML structure/order.
"""

import datetime
import json

import frappe
from frappe.utils import flt
from lxml import etree

# --- Date ---


def format_dgii_date(value):
	"""Formats a date value to the DD-MM-YYYY format required by the DGII XSD."""
	if not value:
		return None
	if isinstance(value, str):
		value = value[:10]
		for date_format in ("%Y-%m-%d", "%d-%m-%Y"):
			try:
				value = datetime.datetime.strptime(value, date_format)
				break
			except ValueError:
				continue
	return value.strftime("%d-%m-%Y") if hasattr(value, "strftime") else str(value)


def get_comprador_rnc(doc):
	"""Returns the buyer's RNC, falling back to the linked Customer's RNC."""
	return doc.tax_id or frappe.db.get_value("Customer", doc.customer, "custom_rnc")


# --- Tax helpers (used by every e-CF builder) ---
# IndicadorFacturacion codes: 1=ITBIS 18%, 2=ITBIS 16%, 3=ITBIS 0%, 4=Exento
INDICADOR_FACTURACION_BY_RATE = {18: "1", 16: "2", 0: "3"}
ITBIS_RATE_BY_INDICADOR = {"1": 18.0, "2": 16.0, "3": 0.0}


def is_itbis_tax(tax):
	"""True when a Sales Taxes and Charges row represents ITBIS."""
	label = f"{tax.get('description') or ''} {tax.get('account_head') or ''}"
	return "ITBIS" in label.upper()


def get_item_itbis_rates(doc):
	"""Resolves the ITBIS rate applied to each invoice line.

	ERPNext stores per-item tax detail (``item_wise_tax_detail``) on each Sales
	Taxes and Charges row. Items absent from that detail are exempt. An invoice
	with no ITBIS row is rejected so an all-exempt document is never emitted by
	accident.

	Returns:
		tuple: (rates_by_item, has_detail, default_rate)
	"""
	rates = {}
	has_detail = False
	default_rate = None
	found_itbis = False
	for tax in doc.get("taxes") or []:
		if not is_itbis_tax(tax):
			continue
		found_itbis = True
		default_rate = flt(tax.get("rate"))
		detail = tax.get("item_wise_tax_detail")
		if not detail:
			continue
		try:
			detail = json.loads(detail)
		except (TypeError, ValueError):
			continue
		has_detail = True
		for key, value in detail.items():
			rates[key] = flt(value[0] if isinstance(value, (list, tuple)) else value)

	if not found_itbis:
		frappe.throw(
			"No se encontró la fila de ITBIS en los impuestos de la factura. "
			"Agregue el ITBIS (18%, 16% o 0%) en la factura o en el template de "
			"impuestos por defecto antes de generar el e-CF."
		)

	return rates, has_detail, default_rate


def get_indicador_facturacion(item, rates, has_detail, default_rate):
	"""Returns the DGII IndicadorFacturacion code for an invoice line."""
	if has_detail:
		rate = rates.get(item.item_code or item.item_name)
	else:
		rate = default_rate
	if rate is None:
		return "4"
	return INDICADOR_FACTURACION_BY_RATE.get(int(rate), "1")


def item_is_bien(item):
	"""Maps an item to Bien (1) or Servicio (2) using Item.is_stock_item."""
	if not item.item_code:
		return True
	try:
		return bool(frappe.get_cached_value("Item", item.item_code, "is_stock_item"))
	except Exception:
		return True


def compute_dgii_tax_totals(doc, forced_indicador=None):
	"""Builds the DGII tax buckets and totals from the invoice taxes.

	Some e-CF types force a single IndicadorFacturacion on every line regardless
	of the invoice taxes (E43/E44/E47 = 4 "Exento", E46 = 3 "tasa cero"); pass
	``forced_indicador`` for those.

	Returns a dict with per-line indicators, the taxable base per ITBIS rate,
	the ITBIS amount per rate and the header totals.
	"""
	if forced_indicador:
		rates, has_detail, default_rate = {}, False, None
	else:
		rates, has_detail, default_rate = get_item_itbis_rates(doc)

	itbis_incluido = any(
		tax.get("included_in_print_rate") for tax in (doc.get("taxes") or []) if is_itbis_tax(tax)
	)

	# Bucket every line by its IndicadorFacturacion so header totals reconcile
	buckets = {"1": 0.0, "2": 0.0, "3": 0.0, "4": 0.0}
	line_indicators = []
	for item in doc.items:
		indicador = forced_indicador or get_indicador_facturacion(item, rates, has_detail, default_rate)
		line_indicators.append(indicador)
		buckets[indicador] += flt(item.amount)

	# When line amounts already include ITBIS, the taxable base is the line total
	# divided by (1 + rate) per the DGII format specification.
	monto_gravado = {}
	for code, rate in ITBIS_RATE_BY_INDICADOR.items():
		base = buckets[code]
		if itbis_incluido and rate:
			base = base / (1 + rate / 100.0)
		monto_gravado[code] = round(base, 2)

	total_itbis = {
		code: round(monto_gravado[code] * ITBIS_RATE_BY_INDICADOR[code] / 100.0, 2)
		for code in ITBIS_RATE_BY_INDICADOR
	}

	return {
		"line_indicators": line_indicators,
		"buckets": buckets,
		"monto_gravado": monto_gravado,
		"total_itbis": total_itbis,
		"monto_gravado_total": round(sum(monto_gravado.values()), 2),
		"total_itbis_sum": round(sum(total_itbis.values()), 2),
		"itbis_incluido": itbis_incluido,
	}


# --- Shared section emitters ---


def append_totales(encabezado, doc, tax_totals):
	"""Appends the shared <Totales> section in the order required by the XSD."""
	buckets = tax_totals["buckets"]
	monto_gravado = tax_totals["monto_gravado"]
	total_itbis = tax_totals["total_itbis"]

	totales = etree.SubElement(encabezado, "Totales")
	if tax_totals["monto_gravado_total"]:
		etree.SubElement(totales, "MontoGravadoTotal").text = f"{tax_totals['monto_gravado_total']:.2f}"
	if buckets["1"]:
		etree.SubElement(totales, "MontoGravadoI1").text = f"{monto_gravado['1']:.2f}"
	if buckets["2"]:
		etree.SubElement(totales, "MontoGravadoI2").text = f"{monto_gravado['2']:.2f}"
	if buckets["3"]:
		etree.SubElement(totales, "MontoGravadoI3").text = f"{monto_gravado['3']:.2f}"
	if buckets["4"]:
		etree.SubElement(totales, "MontoExento").text = f"{buckets['4']:.2f}"
	if buckets["1"]:
		etree.SubElement(totales, "ITBIS1").text = "18"
	if buckets["2"]:
		etree.SubElement(totales, "ITBIS2").text = "16"
	if buckets["3"]:
		etree.SubElement(totales, "ITBIS3").text = "0"
	if tax_totals["monto_gravado_total"] or tax_totals["total_itbis_sum"]:
		etree.SubElement(totales, "TotalITBIS").text = f"{tax_totals['total_itbis_sum']:.2f}"
	if buckets["1"]:
		etree.SubElement(totales, "TotalITBIS1").text = f"{total_itbis['1']:.2f}"
	if buckets["2"]:
		etree.SubElement(totales, "TotalITBIS2").text = f"{total_itbis['2']:.2f}"
	if buckets["3"]:
		etree.SubElement(totales, "TotalITBIS3").text = f"{total_itbis['3']:.2f}"
	etree.SubElement(totales, "MontoTotal").text = f"{flt(doc.grand_total):.2f}"


def append_detalles_items(ecf_root, doc, tax_totals):
	"""Appends the shared <DetallesItems> section."""
	detalles = etree.SubElement(ecf_root, "DetallesItems")
	for idx, item in enumerate(doc.items):
		item_node = etree.SubElement(detalles, "Item")
		etree.SubElement(item_node, "NumeroLinea").text = str(idx + 1)
		etree.SubElement(item_node, "IndicadorFacturacion").text = tax_totals["line_indicators"][idx]
		etree.SubElement(item_node, "NombreItem").text = item.item_name
		etree.SubElement(item_node, "IndicadorBienoServicio").text = "1" if item_is_bien(item) else "2"
		etree.SubElement(item_node, "CantidadItem").text = f"{item.qty:.2f}"
		etree.SubElement(item_node, "PrecioUnitarioItem").text = f"{item.rate:.2f}"
		etree.SubElement(item_node, "MontoItem").text = f"{item.amount:.2f}"


def append_emisor(encabezado, doc):
	emisor = etree.SubElement(encabezado, "Emisor")
	etree.SubElement(emisor, "RNCEmisor").text = doc.company_tax_id
	etree.SubElement(emisor, "RazonSocialEmisor").text = doc.company
	etree.SubElement(emisor, "DireccionEmisor").text = doc.company_address_display
	etree.SubElement(emisor, "FechaEmision").text = datetime.datetime.today().strftime("%d-%m-%Y")


def append_firma(ecf_root):
	current_time = datetime.datetime.now().strftime("%d-%m-%Y %H:%M:%S")
	etree.SubElement(ecf_root, "FechaHoraFirma").text = current_time


NSMAP = {"xsi": "http://www.w3.org/2001/XMLSchema-instance"}


# --- Value accessors (centralized so storage can change in one place) ---


def opt(doc, fieldname):
	"""Returns a stripped value, or ``None`` when empty (covers Select '' too)."""
	value = doc.get(fieldname)
	if isinstance(value, str):
		value = value.strip()
	return value or None


def num(doc, fieldname):
	"""Returns a float, or ``None`` when empty or zero (numeric 0 == absent)."""
	value = flt(doc.get(fieldname))
	return value or None


def intval(doc, fieldname):
	value = doc.get(fieldname)
	if value in (None, ""):
		return None
	return int(flt(value))


def should_use(doc, fieldname, fallback=None):
	"""Override if present; otherwise the fallback (unless certification).

	Certification invoices must not invent values, so when the override is empty
	the element is omitted rather than derived.
	"""
	value = opt(doc, fieldname)
	if value is not None:
		return value
	return None if is_certification(doc) else fallback


def is_certification(doc):
	"""True for invoices created from the DGII certification test set.

	Certification invoices carry every value as an override, so builders must
	not fall back to derived/production values (which may emit elements the
	workbook omits).
	"""
	return bool(doc.get("custom_ecf_certification"))


def item_rows(doc):
	"""Maps ``numero_linea`` -> eCF Detalle Item row."""
	return {row.numero_linea: row for row in (doc.get("custom_ecf_detalle_items") or [])}


# --- Emission helpers (skip absent values so #e stays omitted) ---


def add(parent, tag, value):
	if value in (None, ""):
		return None
	element = etree.SubElement(parent, tag)
	element.text = str(value)
	return element


def add_amount(parent, tag, value):
	if value in (None, ""):
		return None
	amount = flt(value)
	if not amount:
		return None
	element = etree.SubElement(parent, tag)
	element.text = f"{amount:.2f}"
	return element


def add_amount_force(parent, tag, value, decimals=2):
	"""Emits a numeric element even when it is zero (e.g. mandatory ITBIS3=0)."""
	element = etree.SubElement(parent, tag)
	element.text = f"{flt(value):.{decimals}f}"
	return element


def add_int(parent, tag, value):
	if value in (None, ""):
		return None
	element = etree.SubElement(parent, tag)
	element.text = str(int(flt(value)))
	return element


def add_date(parent, tag, value):
	if not value:
		return None
	element = etree.SubElement(parent, tag)
	element.text = format_dgii_date(value)
	return element


def add_container(parent, tag, children):
	"""Appends ``tag`` only when at least one child value is present.

	``children`` is a list of ``(child_tag, value, kind)`` with kind in
	``text | amount | date | int``.
	"""
	values = [(child_tag, value, kind) for child_tag, value, kind in children if value not in (None, "")]
	if not values:
		return None
	container = etree.SubElement(parent, tag)
	for child_tag, value, kind in values:
		if kind == "amount":
			add_amount(container, child_tag, value)
		elif kind == "date":
			add_date(container, child_tag, value)
		elif kind == "int":
			add_int(container, child_tag, value)
		else:
			add(container, child_tag, value)
	return container
