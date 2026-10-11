"""E31 - Factura de Crédito Fiscal Electrónica.

Emits every element the E31 XSD allows, in XSD order. Values come from the
``custom_ecf_*`` overrides; for regular (non-certification) invoices the values
are derived from the company/customer/invoice exactly as before.
"""

import datetime

import frappe
from frappe.utils import flt
from lxml import etree

from . import common
from .common import (
	NSMAP,
	append_totales,
	compute_dgii_tax_totals,
	format_dgii_date,
	is_certification,
	item_is_bien,
	item_rows,
	num,
	opt,
	should_use,
)


_EMPTY_TOTALS = {
	"line_indicators": [],
	"buckets": {},
	"monto_gravado": {},
	"total_itbis": {},
	"monto_gravado_total": 0.0,
	"total_itbis_sum": 0.0,
	"itbis_incluido": False,
}


def build(doc):
	cert = is_certification(doc)
	rows = item_rows(doc)
	# Certification invoices are fully override-driven, so the tax-derived
	# totals are only needed for regular invoices.
	tax_totals = (
		_EMPTY_TOTALS
		if cert
		else compute_dgii_tax_totals(doc)
	)
	present = _present_indicators(rows, tax_totals)

	ecf_root = etree.Element("ECF", nsmap=NSMAP)
	encabezado = etree.SubElement(ecf_root, "Encabezado")
	common.add(encabezado, "Version", "1.0")

	_iddoc(encabezado, doc, tax_totals)
	_emisor(encabezado, doc)
	_comprador(encabezado, doc)
	_embarque(encabezado, doc)
	_transporte(encabezado, doc)
	_totales(encabezado, doc, tax_totals, present)
	_otra_moneda(encabezado, doc)

	_items(ecf_root, doc, rows, tax_totals)
	_referencia(ecf_root, doc)
	common.append_firma(ecf_root)
	return ecf_root


def _present_indicators(rows, tax_totals):
	indicators = {
		str(row.indicador_facturacion).strip()
		for row in rows.values()
		if row.get("indicador_facturacion")
	}
	return indicators or set(tax_totals.get("line_indicators") or [])


# --- IdDoc ---


def _id_doc_indicador(doc, tax_totals):
	value = opt(doc, "custom_ecf_indicador_monto_gravado")
	if value is None and not is_certification(doc) and tax_totals["monto_gravado_total"] > 0:
		value = "1" if tax_totals["itbis_incluido"] else "0"
	return value


def _iddoc(encabezado, doc, tax_totals):
	iddoc = etree.SubElement(encabezado, "IdDoc")
	common.add(iddoc, "TipoeCF", "31")
	common.add(iddoc, "eNCF", doc.custom_ncf)
	common.add_date(iddoc, "FechaVencimientoSecuencia", doc.custom_ncf_vencimiento)
	common.add(iddoc, "IndicadorMontoGravado", _id_doc_indicador(doc, tax_totals))
	common.add(iddoc, "TipoIngresos", should_use(doc, "custom_ecf_tipo_ingresos", "01"))
	common.add(iddoc, "TipoPago", should_use(doc, "custom_ecf_tipo_pago", "1"))
	common.add_date(iddoc, "FechaLimitePago", opt(doc, "custom_ecf_fecha_limite_pago"))
	common.add(iddoc, "TerminoPago", opt(doc, "custom_ecf_termino_pago"))
	_formas_pago(iddoc, doc)
	common.add(iddoc, "TipoCuentaPago", opt(doc, "custom_ecf_tipo_cuenta_pago"))
	common.add(iddoc, "NumeroCuentaPago", opt(doc, "custom_ecf_numero_cuenta_pago"))
	common.add(iddoc, "BancoPago", opt(doc, "custom_ecf_banco_pago"))
	common.add_date(iddoc, "FechaDesde", opt(doc, "custom_ecf_fecha_desde"))
	common.add_date(iddoc, "FechaHasta", opt(doc, "custom_ecf_fecha_hasta"))
	common.add_int(iddoc, "TotalPaginas", opt(doc, "custom_ecf_total_paginas"))


def _formas_pago(iddoc, doc):
	rows = doc.get("custom_ecf_formas_pago") or []
	if not rows:
		return
	tabla = etree.SubElement(iddoc, "TablaFormasPago")
	for row in rows:
		forma = etree.SubElement(tabla, "FormaDePago")
		common.add(forma, "FormaPago", row.forma_pago or "1")
		common.add_amount_force(forma, "MontoPago", row.monto_pago)


# --- Emisor ---


def _emisor(encabezado, doc):
	emisor = etree.SubElement(encabezado, "Emisor")
	common.add(emisor, "RNCEmisor", doc.company_tax_id)
	common.add(
		emisor,
		"RazonSocialEmisor",
		should_use(doc, "custom_ecf_razon_social_emisor", doc.company),
	)
	common.add(emisor, "NombreComercial", opt(doc, "custom_ecf_nombre_comercial"))
	common.add(emisor, "Sucursal", opt(doc, "custom_ecf_sucursal"))
	common.add(
		emisor,
		"DireccionEmisor",
		should_use(doc, "custom_ecf_direccion_emisor", doc.company_address_display),
	)
	common.add(emisor, "Municipio", opt(doc, "custom_ecf_municipio"))
	common.add(emisor, "Provincia", opt(doc, "custom_ecf_provincia"))
	_telefonos(emisor, doc)
	common.add(emisor, "CorreoEmisor", opt(doc, "custom_ecf_correo_emisor"))
	common.add(emisor, "WebSite", opt(doc, "custom_ecf_web_site"))
	common.add(emisor, "ActividadEconomica", opt(doc, "custom_ecf_actividad_economica"))
	common.add(emisor, "CodigoVendedor", opt(doc, "custom_ecf_codigo_vendedor"))
	common.add(emisor, "NumeroFacturaInterna", opt(doc, "custom_ecf_numero_factura_interna"))
	common.add(emisor, "NumeroPedidoInterno", opt(doc, "custom_ecf_numero_pedido_interno"))
	common.add(emisor, "ZonaVenta", opt(doc, "custom_ecf_zona_venta"))
	common.add(emisor, "RutaVenta", opt(doc, "custom_ecf_ruta_venta"))
	common.add(emisor, "InformacionAdicionalEmisor", opt(doc, "custom_ecf_informacion_adicional_emisor"))
	fecha = opt(doc, "custom_ecf_fecha_emision") or datetime.datetime.today().strftime("%d-%m-%Y")
	common.add_date(emisor, "FechaEmision", fecha)


def _telefonos(emisor, doc):
	phones = [opt(doc, f"custom_ecf_telefono_emisor_{idx}") for idx in (1, 2, 3)]
	phones = [phone for phone in phones if phone]
	if not phones:
		return
	tabla = etree.SubElement(emisor, "TablaTelefonoEmisor")
	for phone in phones:
		common.add(tabla, "TelefonoEmisor", phone)


# --- Comprador ---


def _comprador(encabezado, doc):
	comprador = etree.SubElement(encabezado, "Comprador")
	rnc = should_use(doc, "custom_ecf_rnc_comprador", common.get_comprador_rnc(doc))
	if not rnc and not is_certification(doc):
		frappe.throw(
			"El RNC del comprador es requerido para la Factura de Crédito "
			"Fiscal Electrónica (E31). Verifique el RNC del cliente."
		)
	common.add(comprador, "RNCComprador", rnc)
	common.add(
		comprador,
		"RazonSocialComprador",
		should_use(doc, "custom_ecf_razon_social_comprador", doc.customer_name),
	)
	common.add(comprador, "ContactoComprador", opt(doc, "custom_ecf_contacto_comprador"))
	common.add(comprador, "CorreoComprador", opt(doc, "custom_ecf_correo_comprador"))
	common.add(comprador, "DireccionComprador", opt(doc, "custom_ecf_direccion_comprador"))
	common.add(comprador, "MunicipioComprador", opt(doc, "custom_ecf_municipio_comprador"))
	common.add(comprador, "ProvinciaComprador", opt(doc, "custom_ecf_provincia_comprador"))
	common.add_date(comprador, "FechaEntrega", opt(doc, "custom_ecf_fecha_entrega"))
	common.add(comprador, "ContactoEntrega", opt(doc, "custom_ecf_contacto_entrega"))
	common.add(comprador, "DireccionEntrega", opt(doc, "custom_ecf_direccion_entrega"))
	common.add(comprador, "TelefonoAdicional", opt(doc, "custom_ecf_telefono_adicional"))
	common.add_date(comprador, "FechaOrdenCompra", opt(doc, "custom_ecf_fecha_orden_compra"))
	common.add(comprador, "NumeroOrdenCompra", opt(doc, "custom_ecf_numero_orden_compra"))
	common.add(comprador, "CodigoInternoComprador", opt(doc, "custom_ecf_codigo_interno_comprador"))
	common.add(comprador, "ResponsablePago", opt(doc, "custom_ecf_responsable_pago"))
	common.add(comprador, "InformacionAdicionalComprador", opt(doc, "custom_ecf_informacion_adicional_comprador"))


# --- Informaciones adicionales / transporte ---


def _embarque(encabezado, doc):
	common.add_container(
		encabezado,
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


def _transporte(encabezado, doc):
	common.add_container(
		encabezado,
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


# --- Totales ---


def _totales(encabezado, doc, tax_totals, present):
	if not is_certification(doc):
		append_totales(encabezado, doc, tax_totals)
		return

	totales = etree.SubElement(encabezado, "Totales")
	common.add_amount(totales, "MontoGravadoTotal", num(doc, "custom_ecf_monto_gravado_total"))
	for code, tag in (("1", "MontoGravadoI1"), ("2", "MontoGravadoI2"), ("3", "MontoGravadoI3")):
		if code in present:
			common.add_amount(totales, tag, num(doc, f"custom_ecf_monto_gravado_i{code}"))
	if "4" in present:
		common.add_amount(totales, "MontoExento", num(doc, "custom_ecf_monto_exento"))

	for code, tag, rate in (("1", "ITBIS1", "18"), ("2", "ITBIS2", "16"), ("3", "ITBIS3", "0")):
		if code in present:
			common.add(totales, tag, rate)
	if present & {"1", "2", "3"}:
		common.add_amount_force(totales, "TotalITBIS", num(doc, "custom_ecf_total_itbis") or 0)
	for code, tag in (("1", "TotalITBIS1"), ("2", "TotalITBIS2"), ("3", "TotalITBIS3")):
		if code in present:
			common.add_amount_force(totales, tag, num(doc, f"custom_ecf_total_itbis{code}") or 0)

	common.add_amount(totales, "MontoImpuestoAdicional", num(doc, "custom_ecf_monto_impuesto_adicional"))
	common.add_amount_force(totales, "MontoTotal", num(doc, "custom_ecf_monto_total") or doc.grand_total)
	common.add_amount(totales, "MontoNoFacturable", num(doc, "custom_ecf_monto_no_facturable"))
	common.add_amount(totales, "MontoPeriodo", num(doc, "custom_ecf_monto_periodo"))
	common.add_amount(totales, "SaldoAnterior", num(doc, "custom_ecf_saldo_anterior"))
	common.add_amount(totales, "MontoAvancePago", num(doc, "custom_ecf_monto_avance_pago"))
	common.add_amount(totales, "ValorPagar", num(doc, "custom_ecf_valor_pagar"))
	common.add_amount(totales, "TotalITBISRetenido", num(doc, "custom_ecf_total_itbis_retenido"))
	common.add_amount(totales, "TotalISRRetencion", num(doc, "custom_ecf_total_isr_retencion"))
	common.add_amount(totales, "TotalITBISPercepcion", num(doc, "custom_ecf_total_itbis_percepcion"))
	common.add_amount(totales, "TotalISRPercepcion", num(doc, "custom_ecf_total_isr_percepcion"))


# --- Otra moneda ---


def _otra_moneda(encabezado, doc):
	if not opt(doc, "custom_ecf_tipo_moneda"):
		return
	om = etree.SubElement(encabezado, "OtraMoneda")
	common.add(om, "TipoMoneda", opt(doc, "custom_ecf_tipo_moneda"))
	common.add_amount(om, "TipoCambio", num(doc, "custom_ecf_tipo_cambio"))
	common.add_amount(om, "MontoGravadoTotalOtraMoneda", num(doc, "custom_ecf_monto_gravado_total_otra_moneda"))
	common.add_amount(om, "MontoGravado1OtraMoneda", num(doc, "custom_ecf_monto_gravado1_otra_moneda"))
	common.add_amount(om, "MontoGravado2OtraMoneda", num(doc, "custom_ecf_monto_gravado2_otra_moneda"))
	common.add_amount(om, "MontoGravado3OtraMoneda", num(doc, "custom_ecf_monto_gravado3_otra_moneda"))
	common.add_amount(om, "MontoExentoOtraMoneda", num(doc, "custom_ecf_monto_exento_otra_moneda"))
	common.add_amount(om, "TotalITBISOtraMoneda", num(doc, "custom_ecf_total_itbis_otra_moneda"))
	common.add_amount(om, "TotalITBIS1OtraMoneda", num(doc, "custom_ecf_total_itbis1_otra_moneda"))
	common.add_amount(om, "TotalITBIS2OtraMoneda", num(doc, "custom_ecf_total_itbis2_otra_moneda"))
	common.add_amount(om, "TotalITBIS3OtraMoneda", num(doc, "custom_ecf_total_itbis3_otra_moneda"))
	common.add_amount(
		om, "MontoImpuestoAdicionalOtraMoneda", num(doc, "custom_ecf_monto_impuesto_adicional_otra_moneda")
	)
	common.add_amount(om, "MontoTotalOtraMoneda", num(doc, "custom_ecf_monto_total_otra_moneda"))


# --- DetallesItems ---


def _items(ecf_root, doc, rows, tax_totals):
	detalles = etree.SubElement(ecf_root, "DetallesItems")
	for idx, item in enumerate(doc.items):
		line = idx + 1
		row = rows.get(line)
		node = etree.SubElement(detalles, "Item")
		common.add(node, "NumeroLinea", line)
		_codigos(node, doc, line)
		indicador = _row_value(row, "indicador_facturacion") or tax_totals["line_indicators"][idx]
		common.add(node, "IndicadorFacturacion", indicador)
		_retencion(node, row)
		common.add(node, "NombreItem", _line_value(doc, row, "nombre_item", item.item_name))
		bien = _line_value(doc, row, "indicador_bieno_servicio", "1" if item_is_bien(item) else "2")
		common.add(node, "IndicadorBienoServicio", bien)
		common.add(node, "DescripcionItem", _row_value(row, "descripcion_item"))
		common.add_amount_force(
			node, "CantidadItem", _line_num(doc, row, "cantidad_item", item.qty)
		)
		common.add(node, "UnidadMedida", _row_value(row, "unidad_medida"))
		common.add_amount(node, "CantidadReferencia", _row_num(row, "cantidad_referencia"))
		common.add(node, "UnidadReferencia", _row_value(row, "unidad_referencia"))
		common.add_amount(node, "GradosAlcohol", _row_num(row, "grados_alcohol"))
		common.add_amount(node, "PrecioUnitarioReferencia", _row_num(row, "precio_unitario_referencia"))
		common.add_date(node, "FechaElaboracion", _row_value(row, "fecha_elaboracion"))
		common.add_date(node, "FechaVencimientoItem", _row_value(row, "fecha_vencimiento_item"))
		common.add_amount_force(
			node, "PrecioUnitarioItem", _line_num(doc, row, "precio_unitario_item", item.rate)
		)
		common.add_amount(node, "DescuentoMonto", _row_num(row, "descuento_monto"))
		_sub_descuentos(node, doc, line)
		common.add_amount(node, "RecargoMonto", _row_num(row, "recargo_monto"))
		_sub_recargos(node, doc, line)
		_otra_moneda_detalle(node, row)
		common.add_amount_force(node, "MontoItem", _line_num(doc, row, "monto_item", item.amount))


def _row_value(row, fieldname):
	if row is None:
		return None
	return opt(row, fieldname)


def _row_num(row, fieldname):
	if row is None:
		return None
	return num(row, fieldname)


def _line_value(doc, row, fieldname, fallback):
	value = _row_value(row, fieldname)
	if value is not None:
		return value
	return None if is_certification(doc) else fallback


def _line_num(doc, row, fieldname, fallback):
	value = _row_num(row, fieldname)
	if value is not None:
		return value
	return None if is_certification(doc) else fallback


def _codigos(node, doc, line):
	rows = [r for r in (doc.get("custom_ecf_codigos_item") or []) if r.numero_linea == line]
	if not rows:
		return
	tabla = etree.SubElement(node, "TablaCodigosItem")
	for row in rows:
		codigo = etree.SubElement(tabla, "CodigosItem")
		common.add(codigo, "TipoCodigo", row.tipo_codigo)
		common.add(codigo, "CodigoItem", row.codigo_item)


def _sub_descuentos(node, doc, line):
	rows = [r for r in (doc.get("custom_ecf_sub_descuentos") or []) if r.numero_linea == line]
	if not rows:
		return
	tabla = etree.SubElement(node, "TablaSubDescuento")
	for row in rows:
		sub = etree.SubElement(tabla, "SubDescuento")
		common.add(sub, "TipoSubDescuento", row.tipo_sub_descuento)
		common.add_amount(sub, "SubDescuentoPorcentaje", row.sub_descuento_porcentaje)
		common.add_amount(sub, "MontoSubDescuento", row.monto_sub_descuento)


def _sub_recargos(node, doc, line):
	rows = [r for r in (doc.get("custom_ecf_sub_recargos") or []) if r.numero_linea == line]
	if not rows:
		return
	tabla = etree.SubElement(node, "TablaSubRecargo")
	for row in rows:
		sub = etree.SubElement(tabla, "SubRecargo")
		common.add(sub, "TipoSubRecargo", row.tipo_sub_recargo)
		common.add_amount(sub, "SubRecargoPorcentaje", row.sub_recargo_porcentaje)
		common.add_amount(sub, "MontoSubRecargo", row.monto_sub_recargo)


def _retencion(node, row):
	if row is None:
		return
	common.add_container(
		node,
		"Retencion",
		[
			("IndicadorAgenteRetencionoPercepcion", opt(row, "indicador_agente_retencion"), "text"),
			("MontoITBISRetenido", num(row, "monto_itbis_retenido"), "amount"),
			("MontoISRRetenido", num(row, "monto_isr_retenido"), "amount"),
		],
	)


def _otra_moneda_detalle(node, row):
	if row is None:
		return
	common.add_container(
		node,
		"OtraMonedaDetalle",
		[
			("PrecioOtraMoneda", num(row, "precio_otra_moneda"), "amount"),
			("MontoItemOtraMoneda", num(row, "monto_item_otra_moneda"), "amount"),
		],
	)


# --- Informacion de referencia ---


def _referencia(ecf_root, doc):
	common.add_container(
		ecf_root,
		"InformacionReferencia",
		[
			("NCFModificado", opt(doc, "custom_ecf_ncf_modificado"), "text"),
			("RNCOtroContribuyente", opt(doc, "custom_ecf_rnc_otro_contribuyente"), "text"),
			("FechaNCFModificado", opt(doc, "custom_ecf_fecha_ncf_modificado"), "date"),
			("CodigoModificacion", opt(doc, "custom_ecf_codigo_modificacion"), "text"),
		],
	)
