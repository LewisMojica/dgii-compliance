import frappe
from lxml import etree
from lxml.builder import E
import datetime
import json
from frappe.utils import flt
from .signer import sign_ecf

def validate_xml_schema(xml_object, eNCF_type):
	"""
	Validates an XML document against an XSD schema.

	Args:
		xml_object (lxml.etree.Element): The XML object to validate.
		eNCF_type (str): The type of eNCF to validate against.

	Returns:
		bool: True if the XML is valid, False otherwise.
	"""
	xsd_name_map = {
		'E31': 'e-CF 31 v.1.0.xsd',
		'E32': 'e-CF 32 v.1.0.xsd',
	}
	xsd_path = frappe.get_app_path('dgii_compliance', 'dgii_compliance') + '/xsd/' + xsd_name_map[eNCF_type]
	print(xsd_path)
	try:
		with open(xsd_path, 'rb') as xsd_file:
			xsd_content = xsd_file.read()
		# Parse the XML and XSD
		xsd_object = etree.fromstring(xsd_content)

		# Create an XML Schema object
		schema = etree.XMLSchema(xsd_object)
		print('schema valid')
		# Validate the XML document
		if schema.validate(xml_object):
			return True

		error_msgs = []
		for error in schema.error_log:
			err_msg = f"Line {error.line}: {error.message} (Domain: {error.domain_name})"
			print(err_msg)
		return False
	except etree.ParseError as e:
		print(f"XML Parse Error: {str(e)}")
		return False

def new_ecf(doc, eNCF_type):
	"""
	Creates a new eCF document based on the provided reference document.

	Args:
		doc (frappe.model.document.Document): The reference document (e.g., Invoice) to link the eCF to.
		eNCF_type (str): The type of eNCF to validate against. e.g. 'E31' or 'E32' , etc

	Returns:
		frappe.model.document.Document: The newly created and inserted eCF document.
	"""


# Helper for current time in DGII format
	current_time = datetime.datetime.now().strftime("%d-%m-%Y %H:%M:%S")
	today_date = datetime.datetime.now().strftime("%d-%m-%Y")

	if eNCF_type == 'E31':
		xml_object = build_xml_ecf_E31(doc)
	elif eNCF_type == 'E32':
		xml_object = build_xml_ecf_E32(doc)
	else:
		frappe.throw(f'No existe un generador XML para el tipo de eNCF {eNCF_type}')

	"""
	if not validate_xml_schema(xml_object, eNCF_type):
		print(validate_xml_schema(xml_object, eNCF_type))
		frappe.throw('XML Schema validation failed')
	"""
	signed_xml_object = sign_ecf(xml_object)

	if not validate_xml_schema(signed_xml_object, eNCF_type):
		frappe.throw('XML Schema validation failed after sign')

	xml_string = etree.tostring(
		signed_xml_object, encoding="utf-8", xml_declaration=True
	).decode("utf-8")

	ecf = frappe.get_doc({
		'doctype': 'eCF',
		'ref_doctype': doc.doctype,
		'ref_name': doc.name,
		'xml': xml_string,
	})
	ecf.insert()
	return ecf


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
	return doc.tax_id or frappe.db.get_value('Customer', doc.customer, 'custom_rnc')


# --- Shared DGII tax helpers (used by every e-CF builder) ---
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


def compute_dgii_tax_totals(doc):
	"""Builds the DGII tax buckets and totals from the invoice taxes.

	Returns a dict with per-line indicators, the taxable base per ITBIS rate,
	the ITBIS amount per rate and the header totals.
	"""
	rates, has_detail, default_rate = get_item_itbis_rates(doc)

	itbis_incluido = any(
		tax.get("included_in_print_rate") for tax in (doc.get("taxes") or []) if is_itbis_tax(tax)
	)

	# Bucket every line by its IndicadorFacturacion so header totals reconcile
	buckets = {"1": 0.0, "2": 0.0, "3": 0.0, "4": 0.0}
	line_indicators = []
	for item in doc.items:
		indicador = get_indicador_facturacion(item, rates, has_detail, default_rate)
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
	if tax_totals["total_itbis_sum"]:
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


def build_xml_ecf_E31(doc):
	"""Builds the XML for an E31 (Factura de Crédito Fiscal Electrónica).

	E31 requires IdDoc/FechaVencimientoSecuencia and the buyer's
	RNCComprador/RazonSocialComprador, both mandatory in the E31 XSD.
	"""
	tax_totals = compute_dgii_tax_totals(doc)

	ns_map = {'xsi': "http://www.w3.org/2001/XMLSchema-instance"}
	ecf_root = etree.Element("ECF", nsmap=ns_map)

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
	etree.SubElement(iddoc, "TipoPago").text = "01"

	# --- Emisor Section ---
	emisor = etree.SubElement(encabezado, "Emisor")
	etree.SubElement(emisor, "RNCEmisor").text = doc.company_tax_id
	etree.SubElement(emisor, "RazonSocialEmisor").text = doc.company
	etree.SubElement(emisor, "DireccionEmisor").text = doc.company_address_display
	etree.SubElement(emisor, "FechaEmision").text = datetime.datetime.today().strftime("%d-%m-%Y")

	# --- Comprador Section ---
	comprador = etree.SubElement(encabezado, "Comprador")
	etree.SubElement(comprador, "RNCComprador").text = get_comprador_rnc(doc)
	etree.SubElement(comprador, "RazonSocialComprador").text = doc.customer_name

	# --- Totales Section ---
	append_totales(encabezado, doc, tax_totals)

	# --- DetallesItems ---
	append_detalles_items(ecf_root, doc, tax_totals)

	# --- Footer & Signature ---
	current_time = datetime.datetime.now().strftime("%d-%m-%Y %H:%M:%S")
	etree.SubElement(ecf_root, "FechaHoraFirma").text = current_time

	return ecf_root


def build_xml_ecf_E32(doc):
	"""Builds the XML for an E32 (Factura de Consumo Electrónica)."""
	tax_totals = compute_dgii_tax_totals(doc)

	ns_map = {'xsi': "http://www.w3.org/2001/XMLSchema-instance"}
	ecf_root = etree.Element("ECF", nsmap=ns_map)

	encabezado = etree.SubElement(ecf_root, "Encabezado")
	etree.SubElement(encabezado, "Version").text = "1.0"

	# --- IdDoc Section ---
	iddoc = etree.SubElement(encabezado, "IdDoc")
	etree.SubElement(iddoc, "TipoeCF").text = "32"
	etree.SubElement(iddoc, "eNCF").text = doc.custom_ncf
	if tax_totals["monto_gravado_total"] > 0:
		# 1 when line amounts already include ITBIS, 0 when it is added on top
		etree.SubElement(iddoc, "IndicadorMontoGravado").text = "1" if tax_totals["itbis_incluido"] else "0"
	etree.SubElement(iddoc, "TipoIngresos").text = "01"
	etree.SubElement(iddoc, "TipoPago").text = "01"

	# --- Emisor Section ---
	emisor = etree.SubElement(encabezado, "Emisor")
	etree.SubElement(emisor, "RNCEmisor").text = doc.company_tax_id
	etree.SubElement(emisor, "RazonSocialEmisor").text = doc.company
	etree.SubElement(emisor, "DireccionEmisor").text = doc.company_address_display
	etree.SubElement(emisor, "FechaEmision").text = datetime.datetime.today().strftime("%d-%m-%Y")

	# --- Comprador Section ---
	# DGII rejects an empty <Comprador>, so RazonSocial is always sent.
	# RNC is mandatory only for consumption invoices >= RD$250,000.
	comprador = etree.SubElement(encabezado, "Comprador")
	if flt(doc.grand_total) >= 250000:
		etree.SubElement(comprador, "RNCComprador").text = get_comprador_rnc(doc)
	etree.SubElement(comprador, "RazonSocialComprador").text = doc.customer_name or "Consumidor Final"

	# --- Totales Section ---
	append_totales(encabezado, doc, tax_totals)

	# --- DetallesItems ---
	append_detalles_items(ecf_root, doc, tax_totals)

	# --- Footer & Signature ---
	current_time = datetime.datetime.now().strftime("%d-%m-%Y %H:%M:%S")
	etree.SubElement(ecf_root, "FechaHoraFirma").text = current_time

	return ecf_root
