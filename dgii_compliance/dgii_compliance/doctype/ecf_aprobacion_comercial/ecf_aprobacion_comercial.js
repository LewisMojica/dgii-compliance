// Copyright (c) 2026, Lewis Mojica and contributors
// For license information, please see license.txt

frappe.ui.form.on("eCF Aprobacion Comercial", {
	refresh(frm) {
		if (frm.is_new()) {
			return;
		}

		frm.add_custom_button(__("Generar y firmar"), function () {
			frappe.call({
				method: "dgii_compliance.dgii_compliance.doctype.ecf_aprobacion_comercial.acecf.generate_xml",
				args: { name: frm.doc.name },
				freeze: true,
				freeze_message: __("Generando y firmando XML..."),
				callback: function (r) {
					if (r.exc) {
						return;
					}
					frappe.show_alert({ message: __("XML generado y firmado"), indicator: "green" });
					frm.reload_doc();
				},
			});
		});

		if (!frm.doc.xml) {
			return;
		}

		frm.add_custom_button(__("Enviar a DGII"), function () {
			frappe.call({
				method: "dgii_compliance.dgii_compliance.dgii_client.send_acecf_to_dgii",
				args: { acecf_name: frm.doc.name },
				freeze: true,
				freeze_message: __("Enviando a DGII..."),
				callback: function (r) {
					if (r.exc) {
						return;
					}
					frappe.show_alert({
						message: __("Estado DGII: {0}", [r.message.estado || r.message.status || ""]),
						indicator: r.message.status === "error" ? "red" : "green",
					});
					frm.reload_doc();
				},
			});
		});

		frm.add_custom_button(__("Descargar XML"), function () {
			const url =
				"/api/method/dgii_compliance.dgii_compliance.dgii_client.download_acecf_xml?acecf_name=" +
				encodeURIComponent(frm.doc.name);
			window.open(url);
		});
	},
});
