frappe.ui.form.on('Customer', {
    custom_validar_datos_en_dgii: function(frm) {
        if (!frm.doc.tax_id) {
            frappe.msgprint(__('Please enter RNC first'));
            return;
        }
        
        frappe.show_alert({
            message: 'Fetching DGII data...',
            indicator: 'blue'
        });
        
        frappe.call({
            method: 'dgii_compliance.utils.get_company_data_by_rnc',
            args: {
                rnc: frm.doc.tax_id
            },
            callback: function(r) {
                if (r.message && r.message.success) {
                    const data = r.message.data;
                    
                    // Fill customer name
                    frm.set_value('customer_name', data.razon_social);
                    
                    frappe.show_alert({
                        message: 'DGII data loaded successfully',
                        indicator: 'green'
                    });
                    
                } else {
                    frappe.msgprint({
                        title: 'RNC Not Found',
                        message: r.message ? r.message.message : 'Could not fetch DGII data',
                        indicator: 'red'
                    });
                }
            }
        });
    }
});
