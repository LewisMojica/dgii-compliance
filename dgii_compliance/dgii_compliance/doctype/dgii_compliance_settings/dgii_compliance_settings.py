# Copyright (c) 2025, Lewis Mojica and contributors
# For license information, please see license.txt

# import frappe
from frappe.model.document import Document
import frappe
from datetime import datetime



class DGIIComplianceSettings(Document):
	@frappe.whitelist()
	def manual_sync_rnc_data(self):
		import os
		from frappe.utils import get_site_path

		file_path = get_site_path('private', 'files', 'dgii_compliance', 'dgii_rnc_data.csv')

		if os.path.exists(file_path):
			mod_time = datetime.fromtimestamp(os.path.getmtime(file_path))
			if (frappe.utils.now_datetime() - mod_time).seconds < 3600:  # 1 hour
				frappe.throw("RNC data was already synced recently")

		from dgii_compliance.utils import sync_dgii_rnc_data
		sync_dgii_rnc_data()
