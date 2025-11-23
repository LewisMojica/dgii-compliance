function handle_invoice_amendment(frm) {
    if (frm.doc.amended_from && frm.doc.__islocal) {
        clear_ncf_fields(frm);
    }
}

frappe.ui.form.on('Sales Invoice', {
    onload: handle_invoice_amendment,
    refresh: handle_invoice_amendment
});

frappe.ui.form.on('POS Invoice', {
    onload: handle_invoice_amendment,
    refresh: handle_invoice_amendment
});

function clear_ncf_fields(frm) {
    // Clear the custom NCF fields
    frm.set_value('custom_ncf', '');
    frm.set_value('custom_ncf_vencimiento', '');
}

