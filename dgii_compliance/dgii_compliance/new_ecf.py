import frappe


def new_ecf(doc):
    """
    Creates a new eCF document based on the provided reference document.

    Args:
        doc (frappe.model.document.Document): The reference document (e.g., Invoice) to link the eCF to.

    Returns:
        frappe.model.document.Document: The newly created and inserted eCF document.
    """
    
    ecf = frappe.get_doc({
        'doctype': 'eCF',
        'ref_doctype': doc.doctype,
        'ref_name': doc.name,
        'xml': 'bad xml :('
    })
    ecf.insert() 
    return ecf