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
	xml_object = build_xml_ecf_E32(doc)
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



def build_xml_ecf_E32(doc):
	# 1. Create the Root Element
	# Note: We can easily add namespaces here as a dict
	ns_map = {'xsi': "http://www.w3.org/2001/XMLSchema-instance"}
	ecf_root = etree.Element("ECF", nsmap=ns_map)

	# 2. Build the Header (Encabezado)
	encabezado = etree.SubElement(ecf_root, "Encabezado")

	# Version (Mandatory & First)
	etree.SubElement(encabezado, "Version").text = "1.0"

	# --- IdDoc Section ---
	iddoc = etree.SubElement(encabezado, "IdDoc")
	etree.SubElement(iddoc, "TipoeCF").text = "32"
	print(doc.custom_ncf)
	etree.SubElement(iddoc, "eNCF").text = doc.custom_ncf
	#etree.SubElement(iddoc, "IndicadorMontoGravado").text = "1"
	etree.SubElement(iddoc, "TipoIngresos").text = "01"
	etree.SubElement(iddoc, "TipoPago").text = "01"

	# --- Emisor Section ---
	emisor = etree.SubElement(encabezado, "Emisor")
	etree.SubElement(emisor, "RNCEmisor").text = doc.company_tax_id
	etree.SubElement(emisor, "RazonSocialEmisor").text = doc.company
	#etree.SubElement(emisor, "NombreComercial").text = "TU TIENDA"
	#etree.SubElement(emisor, "Sucursal").text = "01"
	etree.SubElement(emisor, "DireccionEmisor").text = doc.company_address_display
	#etree.SubElement(emisor, "Municipio").text = "020103"
	#etree.SubElement(emisor, "Provincia").text = "010000"
	etree.SubElement(emisor, "FechaEmision").text = datetime.datetime.today().strftime("%d-%m-%Y")

	# --- Comprador Section ---
	comprador = etree.SubElement(encabezado, "Comprador")
	#etree.SubElement(comprador, "RNCComprador").text = '132758919'

	#etree.SubElement(comprador, "RazonSocialComprador").text = doc.customer_name

	# --- Totales Section ---
	totales = etree.SubElement(encabezado, "Totales")
	#etree.SubElement(totales, "MontoGravadoTotal").text = f"{doc.total:.2f}"
	#etree.SubElement(totales, "MontoExento").text = "0.00"
	#etree.SubElement(totales, "TotalITBIS").text = f"{doc.total_taxes_and_charges:.2f}"
	etree.SubElement(totales, "MontoTotal").text = f"{doc.grand_total:.2f}"

	# 3. Build Items Loop (DetallesItems)
	detalles = etree.SubElement(ecf_root, "DetallesItems")

	for idx, item in enumerate(doc.items):
		item_node = etree.SubElement(detalles, "Item")

		etree.SubElement(item_node, "NumeroLinea").text = str(idx + 1)

		# Nested Table Structure
		#tabla_codigos = etree.SubElement(item_node, "TablaCodigosItem")
		#codigos_item = etree.SubElement(tabla_codigos, "CodigosItem")
		#etree.SubElement(codigos_item, "TipoCodigo").text = "04"
		#etree.SubElement(codigos_item, "CodigoItem").text = item.item_code

		# SANDWICH ORDER LOGIC (Facturacion -> Nombre -> BienoServicio)
		etree.SubElement(item_node, "IndicadorFacturacion").text = "1"
		etree.SubElement(item_node, "NombreItem").text = item.item_name
		etree.SubElement(item_node, "IndicadorBienoServicio").text = "1"

		etree.SubElement(item_node, "CantidadItem").text = f"{item.qty:.2f}"
		etree.SubElement(item_node, "PrecioUnitarioItem").text = f"{item.rate:.2f}"
		etree.SubElement(item_node, "MontoItem").text = f"{item.amount:.2f}"
		"""
		# Subtotals Table
		tabla_sub = etree.SubElement(item_node, "TablaSubtotales")
		sub_node = etree.SubElement(tabla_sub, "Subtotal")
		etree.SubElement(sub_node, "MontoSubtotal").text = f"{item.amount:.2f}"
		"""
	# 4. Footer & Signature Placeholder
	current_time = datetime.datetime.now().strftime("%d-%m-%Y %H:%M:%S")
	etree.SubElement(ecf_root, "FechaHoraFirma").text = current_time

	# Placeholder for Signature (Required for schema validation before signing)
	# Note: We don't build the complex signature internals here, just the wrapper
	# because the Signer class will overwrite/fill this anyway.
	#sig = etree.SubElement(ecf_root, "Signature")

	return ecf_root
