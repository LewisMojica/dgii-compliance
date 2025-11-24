import frappe
from lxml import etree

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
        return schema.validate(xml_object)
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
    xml_object = etree.Element('ECF')
    if not validate_xml_schema(xml_object, eNCF_type):
        print(validate_xml_schema(xml_object, eNCF_type))
        frappe.throw('XML Schema validation failed')
    ecf = frappe.get_doc({
        'doctype': 'eCF',
        'ref_doctype': doc.doctype,
        'ref_name': doc.name,
        'xml': etree.tostring(xml_object),
    })
    ecf.insert() 
    return ecf