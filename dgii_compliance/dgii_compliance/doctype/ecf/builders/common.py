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


# --- Canonical section emitters -------------------------------------------------
# The e-CF types share the same Encabezado/Item element vocabulary with per-type
# subsets, so these emitters walk the canonical (E31) order and simply skip
# absent values. Each type module declares which tags apply to it and composes
# the sections; XSD validation catches anything a type does not allow.

_ID_DOC_FIXED = {
	"TipoCuentaPago": "custom_ecf_tipo_cuenta_pago",
	"NumeroCuentaPago": "custom_ecf_numero_cuenta_pago",
	"BancoPago": "custom_ecf_banco_pago",
}


def _indicador_monto_gravado(doc, tax_totals):
	value = opt(doc, "custom_ecf_indicador_monto_gravado")
	if value is None and not is_certification(doc) and (tax_totals or {}).get("monto_gravado_total", 0) > 0:
		value = "1" if tax_totals.get("itbis_incluido") else "0"
	return value


def emit_id_doc(parent, doc, tipo, tags, tax_totals):
	iddoc = etree.SubElement(parent, "IdDoc")
	for tag in tags:
		if tag == "TipoeCF":
			add(iddoc, tag, tipo[1:])
		elif tag == "eNCF":
			add(iddoc, tag, doc.custom_ncf)
		elif tag == "FechaVencimientoSecuencia":
			add_date(iddoc, tag, doc.custom_ncf_vencimiento)
		elif tag == "IndicadorNotaCredito":
			add(iddoc, tag, opt(doc, "custom_ecf_indicador_nota_credito"))
		elif tag == "IndicadorMontoGravado":
			add(iddoc, tag, _indicador_monto_gravado(doc, tax_totals))
		elif tag == "TipoIngresos":
			add(iddoc, tag, should_use(doc, "custom_ecf_tipo_ingresos", "01"))
		elif tag == "TipoPago":
			add(iddoc, tag, should_use(doc, "custom_ecf_tipo_pago", "1"))
		elif tag == "FechaLimitePago":
			add_date(iddoc, tag, opt(doc, "custom_ecf_fecha_limite_pago"))
		elif tag == "TerminoPago":
			add(iddoc, tag, opt(doc, "custom_ecf_termino_pago"))
		elif tag == "TablaFormasPago":
			emit_formas_pago(iddoc, doc)
		elif tag in _ID_DOC_FIXED:
			add(iddoc, tag, opt(doc, _ID_DOC_FIXED[tag]))
		elif tag == "FechaDesde":
			add_date(iddoc, tag, opt(doc, "custom_ecf_fecha_desde"))
		elif tag == "FechaHasta":
			add_date(iddoc, tag, opt(doc, "custom_ecf_fecha_hasta"))
		elif tag == "TotalPaginas":
			add_int(iddoc, tag, opt(doc, "custom_ecf_total_paginas"))
	return iddoc


def emit_formas_pago(iddoc, doc):
	rows = doc.get("custom_ecf_formas_pago") or []
	if not rows:
		return None
	tabla = etree.SubElement(iddoc, "TablaFormasPago")
	for row in rows:
		forma = etree.SubElement(tabla, "FormaDePago")
		add(forma, "FormaPago", row.forma_pago or "1")
		add_amount_force(forma, "MontoPago", row.monto_pago)
	return tabla


def emit_emisor(parent, doc):
	emisor = etree.SubElement(parent, "Emisor")
	add(emisor, "RNCEmisor", doc.company_tax_id)
	add(emisor, "RazonSocialEmisor", should_use(doc, "custom_ecf_razon_social_emisor", doc.company))
	add(emisor, "NombreComercial", opt(doc, "custom_ecf_nombre_comercial"))
	add(emisor, "Sucursal", opt(doc, "custom_ecf_sucursal"))
	add(emisor, "DireccionEmisor", should_use(doc, "custom_ecf_direccion_emisor", doc.company_address_display))
	add(emisor, "Municipio", opt(doc, "custom_ecf_municipio"))
	add(emisor, "Provincia", opt(doc, "custom_ecf_provincia"))
	phones = [opt(doc, f"custom_ecf_telefono_emisor_{idx}") for idx in (1, 2, 3)]
	phones = [phone for phone in phones if phone]
	if phones:
		tabla = etree.SubElement(emisor, "TablaTelefonoEmisor")
		for phone in phones:
			add(tabla, "TelefonoEmisor", phone)
	add(emisor, "CorreoEmisor", opt(doc, "custom_ecf_correo_emisor"))
	add(emisor, "WebSite", opt(doc, "custom_ecf_web_site"))
	add(emisor, "ActividadEconomica", opt(doc, "custom_ecf_actividad_economica"))
	add(emisor, "CodigoVendedor", opt(doc, "custom_ecf_codigo_vendedor"))
	add(emisor, "NumeroFacturaInterna", opt(doc, "custom_ecf_numero_factura_interna"))
	add(emisor, "NumeroPedidoInterno", opt(doc, "custom_ecf_numero_pedido_interno"))
	add(emisor, "ZonaVenta", opt(doc, "custom_ecf_zona_venta"))
	add(emisor, "RutaVenta", opt(doc, "custom_ecf_ruta_venta"))
	add(emisor, "InformacionAdicionalEmisor", opt(doc, "custom_ecf_informacion_adicional_emisor"))
	emission = opt(doc, "custom_ecf_fecha_emision") or datetime.datetime.today().strftime("%d-%m-%Y")
	add_date(emisor, "FechaEmision", emission)
	return emisor


def emit_comprador(parent, doc, require_rnc_message, require_rnc=False):
	comprador = etree.SubElement(parent, "Comprador")
	rnc = should_use(doc, "custom_ecf_rnc_comprador", get_comprador_rnc(doc))
	if require_rnc and not rnc and not is_certification(doc):
		frappe.throw(require_rnc_message)
	add(comprador, "RNCComprador", rnc)
	add(comprador, "IdentificadorExtranjero", opt(doc, "custom_ecf_identificador_extranjero"))
	add(
		comprador,
		"RazonSocialComprador",
		should_use(doc, "custom_ecf_razon_social_comprador", doc.customer_name or "Consumidor Final"),
	)
	add(comprador, "ContactoComprador", opt(doc, "custom_ecf_contacto_comprador"))
	add(comprador, "CorreoComprador", opt(doc, "custom_ecf_correo_comprador"))
	add(comprador, "DireccionComprador", opt(doc, "custom_ecf_direccion_comprador"))
	add(comprador, "MunicipioComprador", opt(doc, "custom_ecf_municipio_comprador"))
	add(comprador, "ProvinciaComprador", opt(doc, "custom_ecf_provincia_comprador"))
	add(comprador, "PaisComprador", opt(doc, "custom_ecf_pais_comprador"))
	add_date(comprador, "FechaEntrega", opt(doc, "custom_ecf_fecha_entrega"))
	add(comprador, "ContactoEntrega", opt(doc, "custom_ecf_contacto_entrega"))
	add(comprador, "DireccionEntrega", opt(doc, "custom_ecf_direccion_entrega"))
	add(comprador, "TelefonoAdicional", opt(doc, "custom_ecf_telefono_adicional"))
	add_date(comprador, "FechaOrdenCompra", opt(doc, "custom_ecf_fecha_orden_compra"))
	add(comprador, "NumeroOrdenCompra", opt(doc, "custom_ecf_numero_orden_compra"))
	add(comprador, "CodigoInternoComprador", opt(doc, "custom_ecf_codigo_interno_comprador"))
	add(comprador, "ResponsablePago", opt(doc, "custom_ecf_responsable_pago"))
	add(comprador, "InformacionAdicionalComprador", opt(doc, "custom_ecf_informacion_adicional_comprador"))
	return comprador


def emit_embarque(parent, doc):
	return add_container(
		parent,
		"InformacionesAdicionales",
		[
			("FechaEmbarque", opt(doc, "custom_ecf_fecha_embarque"), "date"),
			("NumeroEmbarque", opt(doc, "custom_ecf_numero_embarque"), "text"),
			("NumeroContenedor", opt(doc, "custom_ecf_numero_contenedor"), "text"),
			("NumeroReferencia", opt(doc, "custom_ecf_numero_referencia"), "text"),
			("PesoBruto", num(doc, "custom_ecf_peso_bruto"), "amount"),
			("PesoNeto", num(doc, "custom_ecf_peso_neto"), "amount"),
			("UnidadPesoBruto", opt(doc, "custom_ecf_unidad_peso_bruto"), "text"),
			("UnidadPesoNeto", opt(doc, "custom_ecf_unidad_peso_neto"), "text"),
			("CantidadBulto", num(doc, "custom_ecf_cantidad_bulto"), "amount"),
			("UnidadBulto", opt(doc, "custom_ecf_unidad_bulto"), "text"),
			("VolumenBulto", num(doc, "custom_ecf_volumen_bulto"), "amount"),
			("UnidadVolumen", opt(doc, "custom_ecf_unidad_volumen"), "text"),
		],
	)


def emit_transporte(parent, doc):
	return add_container(
		parent,
		"Transporte",
		[
			("Conductor", opt(doc, "custom_ecf_conductor"), "text"),
			("DocumentoTransporte", opt(doc, "custom_ecf_documento_transporte"), "text"),
			("Ficha", opt(doc, "custom_ecf_ficha"), "text"),
			("Placa", opt(doc, "custom_ecf_placa"), "text"),
			("RutaTransporte", opt(doc, "custom_ecf_ruta_transporte"), "text"),
			("ZonaTransporte", opt(doc, "custom_ecf_zona_transporte"), "text"),
			("NumeroAlbaran", opt(doc, "custom_ecf_numero_albaran"), "text"),
		],
	)


EMPTY_TOTALS = {
	"line_indicators": [],
	"buckets": {},
	"monto_gravado": {},
	"total_itbis": {},
	"monto_gravado_total": 0.0,
	"total_itbis_sum": 0.0,
	"itbis_incluido": False,
}


def present_indicators(rows, tax_totals):
	indicators = {
		str(row.indicador_facturacion).strip()
		for row in rows.values()
		if row.get("indicador_facturacion")
	}
	return indicators or set((tax_totals or {}).get("line_indicators") or [])


def emit_totales(parent, doc, present, tax_totals, cert):
	if not cert:
		append_totales(parent, doc, tax_totals)
		return

	totales = etree.SubElement(parent, "Totales")
	add_amount(totales, "MontoGravadoTotal", num(doc, "custom_ecf_monto_gravado_total"))
	for code, tag in (("1", "MontoGravadoI1"), ("2", "MontoGravadoI2"), ("3", "MontoGravadoI3")):
		if code in present:
			add_amount(totales, tag, num(doc, f"custom_ecf_monto_gravado_i{code}"))
	if "4" in present:
		add_amount(totales, "MontoExento", num(doc, "custom_ecf_monto_exento"))
	for code, tag, rate in (("1", "ITBIS1", "18"), ("2", "ITBIS2", "16"), ("3", "ITBIS3", "0")):
		if code in present:
			add(totales, tag, rate)
	if present & {"1", "2", "3"}:
		add_amount_force(totales, "TotalITBIS", num(doc, "custom_ecf_total_itbis") or 0)
	for code, tag in (("1", "TotalITBIS1"), ("2", "TotalITBIS2"), ("3", "TotalITBIS3")):
		if code in present:
			add_amount_force(totales, tag, num(doc, f"custom_ecf_total_itbis{code}") or 0)
	add_amount(totales, "MontoImpuestoAdicional", num(doc, "custom_ecf_monto_impuesto_adicional"))
	# Certification always carries an explicit MontoTotal (even 0.00).
	add_amount_force(totales, "MontoTotal", flt(doc.get("custom_ecf_monto_total")))
	add_amount(totales, "MontoNoFacturable", num(doc, "custom_ecf_monto_no_facturable"))
	add_amount(totales, "MontoPeriodo", num(doc, "custom_ecf_monto_periodo"))
	add_amount(totales, "SaldoAnterior", num(doc, "custom_ecf_saldo_anterior"))
	add_amount(totales, "MontoAvancePago", num(doc, "custom_ecf_monto_avance_pago"))
	add_amount(totales, "ValorPagar", num(doc, "custom_ecf_valor_pagar"))
	add_amount(totales, "TotalITBISRetenido", num(doc, "custom_ecf_total_itbis_retenido"))
	add_amount(totales, "TotalISRRetencion", num(doc, "custom_ecf_total_isr_retencion"))
	add_amount(totales, "TotalITBISPercepcion", num(doc, "custom_ecf_total_itbis_percepcion"))
	add_amount(totales, "TotalISRPercepcion", num(doc, "custom_ecf_total_isr_percepcion"))
	return totales


def emit_otra_moneda(parent, doc):
	if not opt(doc, "custom_ecf_tipo_moneda"):
		return None
	om = etree.SubElement(parent, "OtraMoneda")
	add(om, "TipoMoneda", opt(doc, "custom_ecf_tipo_moneda"))
	if is_certification(doc):
		add(om, "TipoCambio", opt(doc, "custom_ecf_tipo_cambio"))
	else:
		add_amount(om, "TipoCambio", num(doc, "custom_ecf_tipo_cambio"))
	add_amount(om, "MontoGravadoTotalOtraMoneda", num(doc, "custom_ecf_monto_gravado_total_otra_moneda"))
	add_amount(om, "MontoGravado1OtraMoneda", num(doc, "custom_ecf_monto_gravado1_otra_moneda"))
	add_amount(om, "MontoGravado2OtraMoneda", num(doc, "custom_ecf_monto_gravado2_otra_moneda"))
	add_amount(om, "MontoGravado3OtraMoneda", num(doc, "custom_ecf_monto_gravado3_otra_moneda"))
	add_amount(om, "MontoExentoOtraMoneda", num(doc, "custom_ecf_monto_exento_otra_moneda"))
	add_amount(om, "TotalITBISOtraMoneda", num(doc, "custom_ecf_total_itbis_otra_moneda"))
	add_amount(om, "TotalITBIS1OtraMoneda", num(doc, "custom_ecf_total_itbis1_otra_moneda"))
	add_amount(om, "TotalITBIS2OtraMoneda", num(doc, "custom_ecf_total_itbis2_otra_moneda"))
	add_amount(om, "TotalITBIS3OtraMoneda", num(doc, "custom_ecf_total_itbis3_otra_moneda"))
	add_amount(om, "MontoImpuestoAdicionalOtraMoneda", num(doc, "custom_ecf_monto_impuesto_adicional_otra_moneda"))
	add_amount(om, "MontoTotalOtraMoneda", num(doc, "custom_ecf_monto_total_otra_moneda"))
	return om


def emit_referencia(parent, doc):
	return add_container(
		parent,
		"InformacionReferencia",
		[
			("NCFModificado", opt(doc, "custom_ecf_ncf_modificado"), "text"),
			("RNCOtroContribuyente", opt(doc, "custom_ecf_rnc_otro_contribuyente"), "text"),
			("FechaNCFModificado", opt(doc, "custom_ecf_fecha_ncf_modificado"), "date"),
			("CodigoModificacion", opt(doc, "custom_ecf_codigo_modificacion"), "text"),
			("RazonModificacion", opt(doc, "custom_ecf_razon_modificacion"), "text"),
		],
	)


# --- DetallesItems ---

_CODIGO_GROUP = [("TipoCodigo", "tipo_codigo"), ("CodigoItem", "codigo_item")]
_SUBDESCUENTO_GROUP = [
	("TipoSubDescuento", "tipo_sub_descuento"),
	("SubDescuentoPorcentaje", "sub_descuento_porcentaje"),
	("MontoSubDescuento", "monto_sub_descuento"),
]
_SUBRECARGO_GROUP = [
	("TipoSubRecargo", "tipo_sub_recargo"),
	("SubRecargoPorcentaje", "sub_recargo_porcentaje"),
	("MontoSubRecargo", "monto_sub_recargo"),
]


def emit_items(ecf_root, doc, rows, tax_totals, cert):
	"""Emits <DetallesItems> for certification (values taken verbatim from rows)."""
	detalles = etree.SubElement(ecf_root, "DetallesItems")
	line_indicators = (tax_totals or {}).get("line_indicators") or []
	for idx, item in enumerate(doc.items):
		line = idx + 1
		row = rows.get(line)
		node = etree.SubElement(detalles, "Item")

		add(node, "NumeroLinea", line)
		_emit_child_group(node, doc, line, "custom_ecf_codigos_item", "TablaCodigosItem", "CodigosItem", _CODIGO_GROUP)
		indicador = _row_value(row, "indicador_facturacion") or (line_indicators[idx] if idx < len(line_indicators) else None)
		add(node, "IndicadorFacturacion", indicador)
		_emit_retencion(node, row)
		add(node, "NombreItem", _row_value(row, "nombre_item") or item.item_name)
		add(
			node,
			"IndicadorBienoServicio",
			_row_value(row, "indicador_bieno_servicio") or ("1" if item_is_bien(item) else "2"),
		)
		add(node, "DescripcionItem", _row_value(row, "descripcion_item"))
		add(node, "CantidadItem", _row_value(row, "cantidad_item") or f"{flt(item.qty):.2f}")
		add(node, "UnidadMedida", _row_value(row, "unidad_medida"))
		add(node, "CantidadReferencia", _row_value(row, "cantidad_referencia"))
		add(node, "UnidadReferencia", _row_value(row, "unidad_referencia"))
		add(node, "GradosAlcohol", _row_value(row, "grados_alcohol"))
		add(node, "PrecioUnitarioReferencia", _row_value(row, "precio_unitario_referencia"))
		add_date(node, "FechaElaboracion", _row_value(row, "fecha_elaboracion"))
		add_date(node, "FechaVencimientoItem", _row_value(row, "fecha_vencimiento_item"))
		add(node, "PrecioUnitarioItem", _row_value(row, "precio_unitario_item") or f"{flt(item.rate):.2f}")
		add(node, "DescuentoMonto", _row_value(row, "descuento_monto"))
		_emit_child_group(node, doc, line, "custom_ecf_sub_descuentos", "TablaSubDescuento", "SubDescuento", _SUBDESCUENTO_GROUP)
		add(node, "RecargoMonto", _row_value(row, "recargo_monto"))
		_emit_child_group(node, doc, line, "custom_ecf_sub_recargos", "TablaSubRecargo", "SubRecargo", _SUBRECARGO_GROUP)
		_emit_otra_moneda_detalle(node, row)
		add(node, "MontoItem", _row_value(row, "monto_item") or f"{flt(item.amount):.2f}")
	return detalles


def _row_value(row, fieldname):
	if row is None:
		return None
	return opt(row, fieldname)


def _emit_child_group(node, doc, line, parentfield, table_tag, row_tag, group):
	rows = [row for row in (doc.get(parentfield) or []) if row.numero_linea == line]
	if not rows:
		return None
	table = etree.SubElement(node, table_tag)
	for row in rows:
		child = etree.SubElement(table, row_tag)
		for tag, fieldname in group:
			add(child, tag, opt(row, fieldname))
	return table


def _emit_retencion(node, row):
	if row is None:
		return None
	return add_container(
		node,
		"Retencion",
		[
			("IndicadorAgenteRetencionoPercepcion", opt(row, "indicador_agente_retencion"), "text"),
			("MontoITBISRetenido", opt(row, "monto_itbis_retenido"), "text"),
			("MontoISRRetenido", opt(row, "monto_isr_retenido"), "text"),
		],
	)


def _emit_otra_moneda_detalle(node, row):
	if row is None:
		return None
	return add_container(
		node,
		"OtraMonedaDetalle",
		[
			("PrecioOtraMoneda", opt(row, "precio_otra_moneda"), "text"),
			("MontoItemOtraMoneda", opt(row, "monto_item_otra_moneda"), "text"),
		],
	)
