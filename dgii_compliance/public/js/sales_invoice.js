let invoicing_method_cache = null;

function get_invoicing_method() {
	if (invoicing_method_cache) {
		return Promise.resolve(invoicing_method_cache);
	}
	return frappe.db
		.get_single_value("DGII Compliance Settings", "invoicing_method")
		.then((method) => {
			invoicing_method_cache = method || "NCF";
			return invoicing_method_cache;
		});
}

function set_ecf_tab_visibility(frm, show) {
	const tab = (frm.layout?.tabs || []).find(
		(tab) => tab.df && tab.df.fieldname === "custom_ecf_tab"
	);
	if (!tab) {
		return;
	}

	tab.df.hidden = show ? 0 : 1;
	tab.refresh();

	if (!show && tab.is_active && tab.is_active()) {
		const first_tab = (frm.layout.tabs || []).find((candidate) => candidate !== tab);
		if (first_tab) {
			first_tab.set_active();
		}
	}
}

function apply_ecf_tab_visibility(frm) {
	if (frm.doctype !== "Sales Invoice") {
		return;
	}

	const ncf = (frm.doc.custom_ncf || "").toUpperCase();
	if (ncf.startsWith("E")) {
		set_ecf_tab_visibility(frm, true);
		return;
	}
	if (ncf.startsWith("B")) {
		set_ecf_tab_visibility(frm, false);
		return;
	}

	// An existing e-CF invoice may not have its e-NCF yet.
	if (!frm.doc.__islocal && (frm.doc.custom_ecf_type || frm.doc.custom_ecf_certification)) {
		set_ecf_tab_visibility(frm, true);
		return;
	}

	// New invoices follow the configured invoicing method.
	get_invoicing_method().then((method) => {
		set_ecf_tab_visibility(frm, method === "eNCF");
	});
}

function handle_invoice_amendment(frm) {
	if (frm.doc.amended_from && frm.doc.__islocal) {
		clear_ncf_fields(frm);
	}
}

frappe.ui.form.on("Sales Invoice", {
	onload(frm) {
		handle_invoice_amendment(frm);
		apply_ecf_tab_visibility(frm);
	},
	refresh(frm) {
		handle_invoice_amendment(frm);
		apply_ecf_tab_visibility(frm);
	},
});

frappe.ui.form.on("POS Invoice", {
	onload: handle_invoice_amendment,
	refresh: handle_invoice_amendment,
});

function clear_ncf_fields(frm) {
	// Clear the custom NCF fields
	frm.set_value("custom_ncf", "");
	frm.set_value("custom_ncf_vencimiento", "");
}
