import frappe
from lxml import etree
from lxml.builder import E
import datetime
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
	xml_string = etree.tostring(xml_object)

	signed_xml_object = sign_ecf(xml_object)

	if not validate_xml_schema(signed_xml_object, eNCF_type):
		frappe.throw('XML Schema validation failed after sign')


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


def build_xml_ecf_E31(doc):
	"""Builds the XML for an E31 (Factura de Crédito Fiscal Electrónica).

	E31 requires IdDoc/FechaVencimientoSecuencia and the buyer's
	RNCComprador/RazonSocialComprador, both mandatory in the E31 XSD.
	"""
	ns_map = {'xsi': "http://www.w3.org/2001/XMLSchema-instance"}
	ecf_root = etree.Element("ECF", nsmap=ns_map)

	encabezado = etree.SubElement(ecf_root, "Encabezado")
	etree.SubElement(encabezado, "Version").text = "1.0"

	# --- IdDoc Section ---
	iddoc = etree.SubElement(encabezado, "IdDoc")
	etree.SubElement(iddoc, "TipoeCF").text = "31"
	etree.SubElement(iddoc, "eNCF").text = doc.custom_ncf
	etree.SubElement(iddoc, "FechaVencimientoSecuencia").text = format_dgii_date(doc.custom_ncf_vencimiento)
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
	totales = etree.SubElement(encabezado, "Totales")
	etree.SubElement(totales, "MontoTotal").text = f"{doc.grand_total:.2f}"

	# --- DetallesItems ---
	detalles = etree.SubElement(ecf_root, "DetallesItems")

	for idx, item in enumerate(doc.items):
		item_node = etree.SubElement(detalles, "Item")
		etree.SubElement(item_node, "NumeroLinea").text = str(idx + 1)
		etree.SubElement(item_node, "IndicadorFacturacion").text = "1"
		etree.SubElement(item_node, "NombreItem").text = item.item_name
		etree.SubElement(item_node, "IndicadorBienoServicio").text = "1"
		etree.SubElement(item_node, "CantidadItem").text = f"{item.qty:.2f}"
		etree.SubElement(item_node, "PrecioUnitarioItem").text = f"{item.rate:.2f}"
		etree.SubElement(item_node, "MontoItem").text = f"{item.amount:.2f}"

	# --- Footer & Signature ---
	current_time = datetime.datetime.now().strftime("%d-%m-%Y %H:%M:%S")
	etree.SubElement(ecf_root, "FechaHoraFirma").text = current_time

	return ecf_root


def build_xml_ecf_E32(doc):
	"""Builds the XML for an E32 (Factura de Consumo Electrónica)."""
	ns_map = {'xsi': "http://www.w3.org/2001/XMLSchema-instance"}
	ecf_root = etree.Element("ECF", nsmap=ns_map)

	encabezado = etree.SubElement(ecf_root, "Encabezado")
	etree.SubElement(encabezado, "Version").text = "1.0"

	# --- IdDoc Section ---
	iddoc = etree.SubElement(encabezado, "IdDoc")
	etree.SubElement(iddoc, "TipoeCF").text = "32"
	etree.SubElement(iddoc, "eNCF").text = doc.custom_ncf
	etree.SubElement(iddoc, "TipoIngresos").text = "01"
	etree.SubElement(iddoc, "TipoPago").text = "01"

	# --- Emisor Section ---
	emisor = etree.SubElement(encabezado, "Emisor")
	etree.SubElement(emisor, "RNCEmisor").text = doc.company_tax_id
	etree.SubElement(emisor, "RazonSocialEmisor").text = doc.company
	etree.SubElement(emisor, "DireccionEmisor").text = doc.company_address_display
	etree.SubElement(emisor, "FechaEmision").text = datetime.datetime.today().strftime("%d-%m-%Y")

	# --- Comprador Section ---
	etree.SubElement(encabezado, "Comprador")

	# --- Totales Section ---
	totales = etree.SubElement(encabezado, "Totales")
	etree.SubElement(totales, "MontoTotal").text = f"{doc.grand_total:.2f}"

	# --- DetallesItems ---
	detalles = etree.SubElement(ecf_root, "DetallesItems")

	for idx, item in enumerate(doc.items):
		item_node = etree.SubElement(detalles, "Item")
		etree.SubElement(item_node, "NumeroLinea").text = str(idx + 1)
		etree.SubElement(item_node, "IndicadorFacturacion").text = "1"
		etree.SubElement(item_node, "NombreItem").text = item.item_name
		etree.SubElement(item_node, "IndicadorBienoServicio").text = "1"
		etree.SubElement(item_node, "CantidadItem").text = f"{item.qty:.2f}"
		etree.SubElement(item_node, "PrecioUnitarioItem").text = f"{item.rate:.2f}"
		etree.SubElement(item_node, "MontoItem").text = f"{item.amount:.2f}"

	# --- Footer & Signature ---
	current_time = datetime.datetime.now().strftime("%d-%m-%Y %H:%M:%S")
	etree.SubElement(ecf_root, "FechaHoraFirma").text = current_time

	return ecf_root
