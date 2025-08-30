// Copyright (c) 2025, Lewis Mojica and contributors
// For license information, please see license.txt

// frappe.ui.form.on("DGII Compliance Settings", {
// 	refresh(frm) {

// 	},
// });
frappe.ui.form.on('DGII Compliance Settings', {
    sync_rnc_data: function(frm) {
        frappe.show_alert({message: __('Syncing RNC data...'), indicator: 'blue'});
        
        frappe.call({
            method: 'manual_sync_rnc_data',
            doc: frm.doc,
            callback: function(r) {
                frappe.show_alert({message: __('RNC data sync completed'), indicator: 'green'});
                frm.reload_doc();
            },
            error: function(r) {
                frappe.show_alert({message: __('Sync failed'), indicator: 'red'});
            }
        });
    }
});
