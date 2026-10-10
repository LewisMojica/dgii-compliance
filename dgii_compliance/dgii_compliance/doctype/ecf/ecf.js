// Copyright (c) 2025, Lewis Mojica and contributors
// For license information, please see license.txt

frappe.ui.form.on("eCF", {
	refresh(frm) {
		if (frm.is_new() || !frm.doc.xml) {
			return;
		}

		frm.add_custom_button(__("Enviar a DGII"), function () {
			frappe.call({
				method: "dgii_compliance.dgii_compliance.dgii_client.send_ecf_to_dgii",
				args: { ecf_name: frm.doc.name },
				freeze: true,
				freeze_message: __("Enviando a DGII..."),
				callback: function (r) {
					if (r.exc) {
						return;
					}
					frappe.show_alert({
						message: __("Estado DGII: {0}", [r.message.estado || r.message.status || ""]),
						indicator: r.message.status === "rejected" ? "red" : "green",
					});
					frm.reload_doc();
				},
			});
		});
	},
});
