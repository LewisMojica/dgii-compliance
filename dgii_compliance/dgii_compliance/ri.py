"""Representación Impresa (RI) data for a Sales Invoice's e-CF.

Reads the stored, signed e-CF XML (so the RI reflects exactly what was sent)
and exposes the values the print format needs, plus the DGII timbre QR.

The QR URL and its ``CodigoSeguridad`` (first 6 chars of the raw
``SignatureValue``) were validated against the DGII ConsultaTimbre services.

Exposed to Jinja via the ``jinja.methods`` hook so the print format can call
``get_ri_data(doc)``.
"""

import base64
import io
from urllib.parse import quote

import frappe
from lxml import etree

DS_NS = "{http://www.w3.org/2000/09/xmldsig#}"

TIPOS = {
	"31": "Factura de Crédito Fiscal Electrónica",
	"32": "Factura de Consumo Electrónica",
	"33": "Nota de Débito Electrónica",
	"34": "Nota de Crédito Electrónica",
	"41": "Comprobante Electrónico de Compras",
	"43": "Comprobante Electrónico para Gastos Menores",
	"44": "Comprobante Electrónico para Regímenes Especiales",
	"45": "Comprobante Electrónico Gubernamental",
	"46": "Comprobante Electrónico para Exportaciones",
	"47": "Comprobante Electrónico para Pagos al Exterior",
}

CODIGOS_MODIFICACION = {
	"1": "Anula el NCF modificado",
	"2": "Corrige Texto del Comprobante Fiscal modificado",
	"3": "Corrige montos del NCF modificado",
	"4": "Reemplazo NCF emitido en contingencia",
	"5": "Referencia Factura Consumo Electrónica",
}

INDICADOR_DESC = {
	"1": "ITBIS 18%",
	"2": "ITBIS 16%",
	"3": "ITBIS 0%",
	"4": "Exento",
}

# DGII "Tabla IV. Codificación Unidad de Medida" (codes 1..62).
UNIDAD_MEDIDA = {
	1: "Barril",
	2: "Bolsa",
	3: "Bote",
	4: "Bultos",
	5: "Botella",
	6: "Caja/Cajón",
	7: "Cajetilla",
	8: "Centímetro",
	9: "Cilindro",
	10: "Conjunto",
	11: "Contenedor",
	12: "Día",
	13: "Docena",
	14: "Fardo",
	15: "Galones",
	16: "Grado",
	17: "Gramo",
	18: "Granel",
	19: "Hora",
	20: "Huacal",
	21: "Kilogramo",
	22: "Kilovatio Hora",
	23: "Libra",
	24: "Litro",
	25: "Lote",
	26: "Metro",
	27: "Metro Cuadrado",
	28: "Metro Cúbico",
	29: "Millones de Unidades Térmicas",
	30: "Minuto",
	31: "Paquete",
	32: "Par",
	33: "Pie",
	34: "Pieza",
	35: "Rollo",
	36: "Sobre",
	37: "Segundo",
	38: "Tanque",
	39: "Tonelada",
	40: "Tubo",
	41: "Yarda",
	42: "Yarda cuadrada",
	43: "Unidad",
	44: "Elemento",
	45: "Millar",
	46: "Saco",
	47: "Lata",
	48: "Display",
	49: "Bidón",
	50: "Ración",
	51: "Quintal",
	52: "Gross Register Tonnage (Toneladas de registro bruto)",
	53: "Pie cuadrado",
	54: "Pasajero",
	55: "Pulgadas",
	56: "Parqueo barcos en muelle",
	57: "Bandeja",
	58: "Hectárea",
	59: "Mililitro",
	60: "Miligramo",
	61: "Onzas",
	62: "Onzas Troy",
}


def _uom(unidad):
	"""Returns the DGII unit-of-measure code as its word (Tabla IV)."""
	if not unidad:
		return None
	try:
		return UNIDAD_MEDIDA.get(int(unidad), unidad)
	except (TypeError, ValueError):
		return unidad


# DGII "Tabla III. Codificación Provincias y Municipios" (subset used here).
PROVINCIAS = {
	"010000": "Distrito Nacional",
	"320000": "Santo Domingo",
}

MUNICIPIOS = {
	"010100": "Santo Domingo de Guzmán",
	"320100": "Santo Domingo Este",
	"320200": "Santo Domingo Oeste",
	"320300": "Santo Domingo Norte",
	"320400": "Boca Chica",
}


def _provincia(value):
	return PROVINCIAS.get(value, value)


def _municipio(value):
	return MUNICIPIOS.get(value, value)


def _text(root, path):
	value = root.findtext(path)
	return value.strip() if value and value.strip() else None


def _amount(value):
	if value in (None, ""):
		return None
	try:
		return f"{float(value):,.2f}"
	except (TypeError, ValueError):
		return value


def _items(root):
	items = []
	for node in root.findall("DetallesItems/Item"):
		indicador = _text(node, "IndicadorFacturacion")
		unidad = _text(node, "UnidadMedida")
		items.append(
			{
				"linea": _text(node, "NumeroLinea"),
				"indicador": indicador,
				"indicador_desc": INDICADOR_DESC.get(indicador, ""),
				"exento": indicador == "4",
				"descripcion": _text(node, "NombreItem"),
				"unidad": unidad,
				"unidad_desc": _uom(unidad),
				"cantidad": _text(node, "CantidadItem"),
				"precio": _amount(_text(node, "PrecioUnitarioItem")),
				"descuento": _amount(_text(node, "DescuentoMonto")),
				"recargo": _amount(_text(node, "RecargoMonto")),
				"valor": _amount(_text(node, "MontoItem")),
			}
		)
	return items


def _parse_amount(value):
	try:
		return float(value or 0)
	except (TypeError, ValueError):
		return 0.0


def _totales(root):
	return {
		"monto_gravado_total": _amount(_text(root, "Encabezado/Totales/MontoGravadoTotal")),
		"monto_gravado_i1": _amount(_text(root, "Encabezado/Totales/MontoGravadoI1")),
		"monto_gravado_i2": _amount(_text(root, "Encabezado/Totales/MontoGravadoI2")),
		"monto_gravado_i3": _amount(_text(root, "Encabezado/Totales/MontoGravadoI3")),
		"monto_exento": _amount(_text(root, "Encabezado/Totales/MontoExento")),
		"total_itbis": _amount(_text(root, "Encabezado/Totales/TotalITBIS")),
		"total_itbis1": _amount(_text(root, "Encabezado/Totales/TotalITBIS1")),
		"total_itbis2": _amount(_text(root, "Encabezado/Totales/TotalITBIS2")),
		"total_itbis3": _amount(_text(root, "Encabezado/Totales/TotalITBIS3")),
		"monto_impuesto_adicional": _amount(_text(root, "Encabezado/Totales/MontoImpuestoAdicional")),
		"monto_total": _amount(_text(root, "Encabezado/Totales/MontoTotal")),
	}


def _qr_data_uri(url):
	import segno

	qr = segno.make(url, error="m")
	buffer = io.BytesIO()
	qr.save(buffer, kind="png", scale=10, border=0)
	return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()


def _qr_url(root, env):
	tipo = _text(root, "Encabezado/IdDoc/TipoeCF")
	encf = _text(root, "Encabezado/IdDoc/eNCF")
	monto = _text(root, "Encabezado/Totales/MontoTotal")
	rnc_emisor = _text(root, "Encabezado/Emisor/RNCEmisor")
	fecha_firma = _text(root, "FechaHoraFirma")
	signature = root.findtext(f".//{DS_NS}SignatureValue")
	codigo = (signature or "")[:6]

	if tipo == "32" and _parse_amount(monto) < 250000:
		return (
			f"https://fc.dgii.gov.do/{env}/consultatimbrefc"
			f"?rncemisor={rnc_emisor}&encf={quote(encf or '')}&montototal={monto}"
			f"&codigoseguridad={quote(codigo, safe='')}"
		)

	rnc_comprador = _text(root, "Encabezado/Comprador/RNCComprador") or ""
	fecha_emision = _text(root, "Encabezado/Emisor/FechaEmision") or ""
	# E43/E47 have no buyer. DGII rejects the query when rnccomprador is sent
	# empty, so only include it when present.
	comprador_param = f"&rnccomprador={rnc_comprador}" if rnc_comprador else ""
	return (
		f"https://ecf.dgii.gov.do/{env}/consultatimbre"
		f"?rncemisor={rnc_emisor}{comprador_param}&encf={quote(encf or '')}"
		f"&fechaemision={quote(fecha_emision, safe=':')}&montototal={monto}"
		f"&fechafirma={quote(fecha_firma or '', safe=':')}&codigoseguridad={quote(codigo, safe='')}"
	)


def get_ri_data(doc):
	"""Returns the RI values for a Sales Invoice's e-CF (Jinja method)."""
	if isinstance(doc, str):
		doc = frappe.get_doc("Sales Invoice", doc)

	xml = frappe.db.get_value("eCF", {"ref_doctype": doc.doctype, "ref_name": doc.name}, "xml")
	if not xml:
		frappe.throw(f"La factura {doc.name} no tiene un e-CF firmado.")
	root = etree.fromstring(xml.encode())

	env = frappe.db.get_single_value("DGII Compliance Settings", "dgii_environment") or "testecf"
	tipo = _text(root, "Encabezado/IdDoc/TipoeCF")
	codigo_modificacion = _text(root, ".//InformacionReferencia/CodigoModificacion")

	# The emisor's legal name must be the company's registered name. The e-CF may
	# carry a test-set override, so prefer the invoice's company.
	company_name = doc.get("company") if hasattr(doc, "get") else None

	return {
		"tipo": tipo,
		"tipo_desc": TIPOS.get(tipo, tipo),
		"encf": _text(root, "Encabezado/IdDoc/eNCF"),
		"fecha_vencimiento": _text(root, "Encabezado/IdDoc/FechaVencimientoSecuencia"),
		"ncf_modificado": _text(root, ".//InformacionReferencia/NCFModificado"),
		"fecha_ncf_modificado": _text(root, ".//InformacionReferencia/FechaNCFModificado"),
		"codigo_modificacion": codigo_modificacion,
		"codigo_modificacion_desc": CODIGOS_MODIFICACION.get(codigo_modificacion or "", ""),
		"rnc_emisor": _text(root, "Encabezado/Emisor/RNCEmisor"),
		"razon_social_emisor": company_name or _text(root, "Encabezado/Emisor/RazonSocialEmisor"),
		"nombre_comercial": None,
		"sucursal": _text(root, "Encabezado/Emisor/Sucursal"),
		"direccion_emisor": _text(root, "Encabezado/Emisor/DireccionEmisor"),
		"municipio": _text(root, "Encabezado/Emisor/Municipio"),
		"municipio_desc": _municipio(_text(root, "Encabezado/Emisor/Municipio")),
		"provincia": _text(root, "Encabezado/Emisor/Provincia"),
		"provincia_desc": _provincia(_text(root, "Encabezado/Emisor/Provincia")),
		"fecha_emision": _text(root, "Encabezado/Emisor/FechaEmision"),
		"rnc_comprador": _text(root, "Encabezado/Comprador/RNCComprador"),
		"razon_social_comprador": _text(root, "Encabezado/Comprador/RazonSocialComprador"),
		"lineas": _items(root),
		"totales": _totales(root),
		"fecha_firma": _text(root, "FechaHoraFirma"),
		"codigo_seguridad": (root.findtext(f".//{DS_NS}SignatureValue") or "")[:6],
		"qr_data_uri": _qr_data_uri(_qr_url(root, env)),
	}
