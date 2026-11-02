"""Drop e-CF fields that moved to Company/Address or the export JSON payload.

This runs on sites that had an intermediate build of the feature branch. Fresh
sites and production sites that never installed the feature branch are no-ops.
"""

import frappe

REMOVED_FIELDS = [
	"custom_ecf_razon_social_emisor",
	"custom_ecf_nombre_comercial",
	"custom_ecf_sucursal",
	"custom_ecf_municipio",
	"custom_ecf_provincia",
	"custom_ecf_direccion_emisor",
	"custom_ecf_telefono_emisor_1",
	"custom_ecf_telefono_emisor_2",
	"custom_ecf_telefono_emisor_3",
	"custom_ecf_correo_emisor",
	"custom_ecf_web_site",
	"custom_ecf_actividad_economica",
	"custom_ecf_rnc_comprador",
	"custom_ecf_razon_social_comprador",
	"custom_ecf_contacto_comprador",
	"custom_ecf_correo_comprador",
	"custom_ecf_direccion_comprador",
	"custom_ecf_municipio_comprador",
	"custom_ecf_provincia_comprador",
	"custom_ecf_pais_comprador",
	"custom_ecf_fecha_orden_compra",
	"custom_ecf_numero_orden_compra",
	"custom_ecf_fecha_embarque",
	"custom_ecf_numero_embarque",
	"custom_ecf_numero_contenedor",
	"custom_ecf_numero_referencia",
	"custom_ecf_peso_bruto",
	"custom_ecf_peso_neto",
	"custom_ecf_unidad_peso_bruto",
	"custom_ecf_unidad_peso_neto",
	"custom_ecf_cantidad_bulto",
	"custom_ecf_unidad_bulto",
	"custom_ecf_volumen_bulto",
	"custom_ecf_unidad_volumen",
	"custom_ecf_conductor",
	"custom_ecf_documento_transporte",
	"custom_ecf_ficha",
	"custom_ecf_placa",
	"custom_ecf_ruta_transporte",
	"custom_ecf_zona_transporte",
	"custom_ecf_numero_albaran",
	"custom_ecf_itbis1",
	"custom_ecf_itbis2",
	"custom_ecf_itbis3",
	"custom_ecf_section_transporte",
]


def execute():
	doctype = "Sales Invoice"
	table = f"tab{doctype}"
	for fieldname in REMOVED_FIELDS:
		name = f"{doctype}-{fieldname}"
		if frappe.db.exists("Custom Field", name):
			frappe.delete_doc("Custom Field", name, force=True, ignore_permissions=True)
		if frappe.db.has_column(doctype, fieldname):
			frappe.db.sql_ddl(f"ALTER TABLE `{table}` DROP COLUMN `{fieldname}`")
	frappe.clear_cache(doctype=doctype)
