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
					const message = r.message.estado
						? __("Estado DGII: {0}", [r.message.estado])
						: __("Enviado. Track ID: {0}", [r.message.track_id || ""]);
					frappe.show_alert({ message: message, indicator: "green" });
					frm.reload_doc();
				},
			});
		});

		// e-CFs have a Track ID; RFCEs (Resumen < RD$250k) do not, but were
		// still submitted, so allow querying whenever we have a DGII estado.
		if (frm.doc.track_id || frm.doc.estado) {
			frm.add_custom_button(__("Consultar estado"), function () {
				frappe.call({
					method: "dgii_compliance.dgii_compliance.dgii_client.refresh_ecf_status",
					args: { ecf_name: frm.doc.name },
					freeze: true,
					freeze_message: __("Consultando estado en DGII..."),
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
		}
	},
});
