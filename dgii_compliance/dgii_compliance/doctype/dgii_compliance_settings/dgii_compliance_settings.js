// Copyright (c) 2025, Lewis Mojica and contributors
// For license information, please see license.txt

// frappe.ui.form.on("DGII Compliance Settings", {
// 	refresh(frm) {

// 	},
// });
frappe.ui.form.on('DGII Compliance Settings', {
    sync_rnc_data: function(frm) {
        frappe.call({
            method: 'manual_sync_rnc_data',
            doc: frm.doc,
            callback: function(r) {
                frappe.msgprint(__('RNC data sync completed'));
                frm.reload_doc();
            }
        });
    }
});
