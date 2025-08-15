import frappe
def customer(doc,method):
	if doc.customer_type == 'Company' and not doc.custom_rnc:
		 frappe.throw("RNC es requerido para compañías")
	doc.tax_id = doc.custom_rnc

