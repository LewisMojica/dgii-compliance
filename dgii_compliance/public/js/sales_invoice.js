frappe.ui.form.on('Sales Invoice', {
    onload: function(frm) {
        // Clear NCF fields when a Sales Invoice is being amended
        if (frm.doc.amended_from && frm.doc.__islocal) {
            clear_ncf_fields(frm);
        }
    },

    refresh: function(frm) {
        // Additional check for edge cases
        if (frm.doc.amended_from && frm.doc.__islocal && !frm.is_new()) {
            clear_ncf_fields(frm);
        }
    }
});

function clear_ncf_fields(frm) {
    // Clear the custom NCF fields
    frm.set_value('custom_ncf', '');
    frm.set_value('custom_ncf_vencimiento', '');
}
