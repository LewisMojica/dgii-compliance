"""Maps workbook columns to e-CF model fields (the single source of truth)."""

from dgii_compliance.dgii_compliance.test_set import parser

# Header column -> (target fieldname, type)
#   type: str | float | int | date | type | skip
# "skip" columns are intentionally derived (company/customer/constants).
HEADER_MAP = {
	"CasoPrueba": ("skip", None),
	"Version": ("skip", None),
	"TipoeCF": ("custom_ecf_type", "type"),
	"ENCF": ("custom_ncf", "str"),
	"FechaVencimientoSecuencia": ("custom_ncf_vencimiento", "date"),
	"IndicadorNotaCredito": ("custom_ecf_indicador_nota_credito", "str"),
	"IndicadorEnvioDiferido": ("skip", None),
	"IndicadorMontoGravado": ("custom_ecf_indicador_monto_gravado", "str"),
	"TipoIngresos": ("custom_ecf_tipo_ingresos", "str"),
	"TipoPago": ("custom_ecf_tipo_pago", "str"),
	"FechaLimitePago": ("custom_ecf_fecha_limite_pago", "date"),
	"TerminoPago": ("custom_ecf_termino_pago", "str"),
	"TipoCuentaPago": ("custom_ecf_tipo_cuenta_pago", "str"),
	"NumeroCuentaPago": ("custom_ecf_numero_cuenta_pago", "str"),
	"BancoPago": ("custom_ecf_banco_pago", "str"),
	"FechaDesde": ("custom_ecf_fecha_desde", "date"),
	"FechaHasta": ("custom_ecf_fecha_hasta", "date"),
	"TotalPaginas": ("custom_ecf_total_paginas", "int"),
	"RNCEmisor": ("skip", None),
	"RazonSocialEmisor": ("custom_ecf_razon_social_emisor", "str"),
	"NombreComercial": ("custom_ecf_nombre_comercial", "str"),
	"Sucursal": ("custom_ecf_sucursal", "str"),
	"DireccionEmisor": ("custom_ecf_direccion_emisor", "str"),
	"Municipio": ("custom_ecf_municipio", "str"),
	"Provincia": ("custom_ecf_provincia", "str"),
	"CorreoEmisor": ("custom_ecf_correo_emisor", "str"),
	"WebSite": ("custom_ecf_web_site", "str"),
	"ActividadEconomica": ("custom_ecf_actividad_economica", "str"),
	"CodigoVendedor": ("custom_ecf_codigo_vendedor", "str"),
	"NumeroFacturaInterna": ("custom_ecf_numero_factura_interna", "str"),
	"NumeroPedidoInterno": ("custom_ecf_numero_pedido_interno", "str"),
	"ZonaVenta": ("custom_ecf_zona_venta", "str"),
	"RutaVenta": ("custom_ecf_ruta_venta", "str"),
	"InformacionAdicionalEmisor": ("custom_ecf_informacion_adicional_emisor", "str"),
	"FechaEmision": ("custom_ecf_fecha_emision", "date"),
	"RNCComprador": ("custom_ecf_rnc_comprador", "str"),
	"IdentificadorExtranjero": ("custom_ecf_identificador_extranjero", "str"),
	"RazonSocialComprador": ("custom_ecf_razon_social_comprador", "str"),
	"ContactoComprador": ("custom_ecf_contacto_comprador", "str"),
	"CorreoComprador": ("custom_ecf_correo_comprador", "str"),
	"DireccionComprador": ("custom_ecf_direccion_comprador", "str"),
	"MunicipioComprador": ("custom_ecf_municipio_comprador", "str"),
	"ProvinciaComprador": ("custom_ecf_provincia_comprador", "str"),
	"PaisComprador": ("custom_ecf_pais_comprador", "str"),
	"FechaEntrega": ("custom_ecf_fecha_entrega", "date"),
	"ContactoEntrega": ("custom_ecf_contacto_entrega", "str"),
	"DireccionEntrega": ("custom_ecf_direccion_entrega", "str"),
	"TelefonoAdicional": ("custom_ecf_telefono_adicional", "str"),
	"FechaOrdenCompra": ("custom_ecf_fecha_orden_compra", "date"),
	"NumeroOrdenCompra": ("custom_ecf_numero_orden_compra", "str"),
	"CodigoInternoComprador": ("custom_ecf_codigo_interno_comprador", "str"),
	"ResponsablePago": ("custom_ecf_responsable_pago", "str"),
	"InformacionAdicionalComprador": ("custom_ecf_informacion_adicional_comprador", "str"),
	"FechaEmbarque": ("custom_ecf_fecha_embarque", "date"),
	"NumeroEmbarque": ("custom_ecf_numero_embarque", "str"),
	"NumeroContenedor": ("custom_ecf_numero_contenedor", "str"),
	"NumeroReferencia": ("custom_ecf_numero_referencia", "str"),
	"PesoBruto": ("custom_ecf_peso_bruto", "float"),
	"PesoNeto": ("custom_ecf_peso_neto", "float"),
	"UnidadPesoBruto": ("custom_ecf_unidad_peso_bruto", "str"),
	"UnidadPesoNeto": ("custom_ecf_unidad_peso_neto", "str"),
	"CantidadBulto": ("custom_ecf_cantidad_bulto", "float"),
	"UnidadBulto": ("custom_ecf_unidad_bulto", "str"),
	"VolumenBulto": ("custom_ecf_volumen_bulto", "float"),
	"UnidadVolumen": ("custom_ecf_unidad_volumen", "str"),
	"Conductor": ("custom_ecf_conductor", "str"),
	"DocumentoTransporte": ("custom_ecf_documento_transporte", "str"),
	"Ficha": ("custom_ecf_ficha", "str"),
	"Placa": ("custom_ecf_placa", "str"),
	"RutaTransporte": ("custom_ecf_ruta_transporte", "str"),
	"ZonaTransporte": ("custom_ecf_zona_transporte", "str"),
	"NumeroAlbaran": ("custom_ecf_numero_albaran", "str"),
	"MontoGravadoTotal": ("custom_ecf_monto_gravado_total", "float"),
	"MontoGravadoI1": ("custom_ecf_monto_gravado_i1", "float"),
	"MontoGravadoI2": ("custom_ecf_monto_gravado_i2", "float"),
	"MontoGravadoI3": ("custom_ecf_monto_gravado_i3", "float"),
	"MontoExento": ("custom_ecf_monto_exento", "float"),
	"ITBIS1": ("custom_ecf_itbis1", "int"),
	"ITBIS2": ("custom_ecf_itbis2", "int"),
	"ITBIS3": ("custom_ecf_itbis3", "int"),
	"TotalITBIS": ("custom_ecf_total_itbis", "float"),
	"TotalITBIS1": ("custom_ecf_total_itbis1", "float"),
	"TotalITBIS2": ("custom_ecf_total_itbis2", "float"),
	"TotalITBIS3": ("custom_ecf_total_itbis3", "float"),
	"MontoImpuestoAdicional": ("custom_ecf_monto_impuesto_adicional", "float"),
	"MontoTotal": ("custom_ecf_monto_total", "float"),
	"MontoNoFacturable": ("custom_ecf_monto_no_facturable", "float"),
	"MontoPeriodo": ("custom_ecf_monto_periodo", "float"),
	"SaldoAnterior": ("custom_ecf_saldo_anterior", "float"),
	"MontoAvancePago": ("custom_ecf_monto_avance_pago", "float"),
	"ValorPagar": ("custom_ecf_valor_pagar", "float"),
	"TotalITBISRetenido": ("custom_ecf_total_itbis_retenido", "float"),
	"TotalISRRetencion": ("custom_ecf_total_isr_retencion", "float"),
	"TotalITBISPercepcion": ("custom_ecf_total_itbis_percepcion", "float"),
	"TotalISRPercepcion": ("custom_ecf_total_isr_percepcion", "float"),
	"TipoMoneda": ("custom_ecf_tipo_moneda", "str"),
	"TipoCambio": ("custom_ecf_tipo_cambio", "str"),
	"MontoGravadoTotalOtraMoneda": ("custom_ecf_monto_gravado_total_otra_moneda", "float"),
	"MontoGravado1OtraMoneda": ("custom_ecf_monto_gravado1_otra_moneda", "float"),
	"MontoGravado2OtraMoneda": ("custom_ecf_monto_gravado2_otra_moneda", "float"),
	"MontoGravado3OtraMoneda": ("custom_ecf_monto_gravado3_otra_moneda", "float"),
	"MontoExentoOtraMoneda": ("custom_ecf_monto_exento_otra_moneda", "float"),
	"TotalITBISOtraMoneda": ("custom_ecf_total_itbis_otra_moneda", "float"),
	"TotalITBIS1OtraMoneda": ("custom_ecf_total_itbis1_otra_moneda", "float"),
	"TotalITBIS2OtraMoneda": ("custom_ecf_total_itbis2_otra_moneda", "float"),
	"TotalITBIS3OtraMoneda": ("custom_ecf_total_itbis3_otra_moneda", "float"),
	"MontoImpuestoAdicionalOtraMoneda": ("custom_ecf_monto_impuesto_adicional_otra_moneda", "float"),
	"MontoTotalOtraMoneda": ("custom_ecf_monto_total_otra_moneda", "float"),
	"NCFModificado": ("custom_ecf_ncf_modificado", "str"),
	"RNCOtroContribuyente": ("custom_ecf_rnc_otro_contribuyente", "str"),
	"FechaNCFModificado": ("custom_ecf_fecha_ncf_modificado", "date"),
	"CodigoModificacion": ("custom_ecf_codigo_modificacion", "str"),
	"RazonModificacion": ("custom_ecf_razon_modificacion", "str"),
}

# Per-line scalar columns -> (eCF Detalle Item fieldname, type)
ITEM_SCALARS = {
	"NumeroLinea": ("numero_linea", "int"),
	"IndicadorFacturacion": ("indicador_facturacion", "str"),
	"IndicadorAgenteRetencionoPercepcion": ("indicador_agente_retencion", "str"),
	"MontoITBISRetenido": ("monto_itbis_retenido", "str"),
	"MontoISRRetenido": ("monto_isr_retenido", "str"),
	"NombreItem": ("nombre_item", "str"),
	"IndicadorBienoServicio": ("indicador_bieno_servicio", "str"),
	"DescripcionItem": ("descripcion_item", "str"),
	"CantidadItem": ("cantidad_item", "str"),
	"UnidadMedida": ("unidad_medida", "str"),
	"FechaElaboracion": ("fecha_elaboracion", "date"),
	"FechaVencimientoItem": ("fecha_vencimiento_item", "date"),
	"PrecioUnitarioItem": ("precio_unitario_item", "str"),
	"DescuentoMonto": ("descuento_monto", "str"),
	"RecargoMonto": ("recargo_monto", "str"),
	"PrecioOtraMoneda": ("precio_otra_moneda", "str"),
	"MontoItemOtraMoneda": ("monto_item_otra_moneda", "str"),
	"MontoItem": ("monto_item", "str"),
}

# Per-line columns that also feed the ERPNext invoice line.
INVOICE_ITEM_FIELDS = {
	"NombreItem": "item_name",
	"CantidadItem": "qty",
	"PrecioUnitarioItem": "rate",
	"MontoItem": "amount",
}

# Nested groups: base column -> child fieldname (type fixed per group)
CODIGO_GROUP = {"TipoCodigo": "tipo_codigo", "CodigoItem": "codigo_item"}
SUBDESCUENTO_GROUP = {
	"TipoSubDescuento": "tipo_sub_descuento",
	"SubDescuentoPorcentaje": "sub_descuento_porcentaje",
	"MontoSubDescuento": "monto_sub_descuento",
}
SUBRECARGO_GROUP = {
	"TipoSubRecargo": "tipo_sub_recargo",
	"SubRecargoPorcentaje": "sub_recargo_porcentaje",
	"MontosubRecargo": "monto_sub_recargo",
}

# Header-level repeated tables
PAYMENT_FIELDS = {"FormaPago": "forma_pago", "MontoPago": "monto_pago"}
PHONE_BASE = "TelefonoEmisor"


def convert(value, kind):
	if kind == "float":
		return parser.to_float(value)
	if kind == "int":
		return parser.to_int(value)
	if kind == "date":
		return parser.to_date(value)
	if kind == "type":
		return f"E{value}"
	return parser._clean(value)
