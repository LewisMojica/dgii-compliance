import frappe


def execute():
	frappe.db.set_single_value("DGII Compliance Settings", "reuse_ncf_on_amendment", 1)
