"""Resolve e-CF emitter, buyer and export data from native ERPNext records.

The certification importer still writes the exact DGII test values, but the
Sales Invoice no longer carries emitter/buyer/transport columns. Values live on
Company, Customer, Address and the export JSON override field.
"""

import datetime
import json
import re

import frappe

EXPORT_KEYS = (
	"fecha_embarque",
	"numero_embarque",
	"numero_contenedor",
	"numero_referencia",
	"peso_bruto",
	"peso_neto",
	"unidad_peso_bruto",
	"unidad_peso_neto",
	"cantidad_bulto",
	"unidad_bulto",
	"volumen_bulto",
	"unidad_volumen",
	"conductor",
	"documento_transporte",
	"ficha",
	"placa",
	"ruta_transporte",
	"zona_transporte",
	"numero_albaran",
)


def _get_doc(doctype, name):
	if not name:
		return None
	try:
		return frappe.get_cached_doc(doctype, name)
	except Exception:
		return None


def _clean(value):
	if isinstance(value, str):
		value = value.strip()
	return value or None


def normalize_phone(value):
	"""Returns a DGII phone (``NNN-NNN-NNNN``) or ``None``.

	``TelefonoValidationType`` only accepts ten digits in
	``NNN-NNN-NNNN`` format. Production data commonly contains ``+1``,
	parentheses, spaces and hyphens, so reduce it to the local number before
	emitting the e-CF. Unparseable values are omitted (the fields are optional).
	"""
	value = _clean(value)
	if not value:
		return None

	text = str(value).strip()
	if re.fullmatch(r"\d{3}-\d{3}-\d{4}", text):
		return text

	digits = re.sub(r"\D", "", text)
	if len(digits) > 10:
		digits = digits.lstrip("0")
		if len(digits) == 11 and digits.startswith("1"):
			digits = digits[1:]

	if len(digits) != 10:
		return None
	return f"{digits[:3]}-{digits[3:6]}-{digits[6:]}"


def _company_value(company, fieldname):
	if not company:
		return None
	return _clean(company.get(fieldname))


def get_emitter(doc):
	"""Returns the data needed by ``<Emisor>`` and ``FechaEmision``."""
	company = _get_doc("Company", doc.get("company"))
	company_name = _company_value(company, "company_name") or _clean(doc.get("company"))
	phones = []
	if company:
		phones = [
			normalize_phone(
				_company_value(company, "custom_ecf_telefono_emisor_1")
				or _company_value(company, "phone_no")
			),
			normalize_phone(_company_value(company, "custom_ecf_telefono_emisor_2")),
			normalize_phone(_company_value(company, "custom_ecf_telefono_emisor_3")),
		]
	return {
		"rnc": _clean(doc.get("company_tax_id")) or _company_value(company, "tax_id"),
		"razon_social": _company_value(company, "custom_ecf_razon_social_emisor") or company_name,
		"nombre_comercial": _company_value(company, "custom_ecf_nombre_comercial"),
		"sucursal": _company_value(company, "custom_ecf_sucursal"),
		"direccion": _company_value(company, "custom_ecf_direccion_emisor")
		or _clean(doc.get("company_address_display")),
		"municipio": _company_value(company, "custom_ecf_municipio"),
		"provincia": _company_value(company, "custom_ecf_provincia"),
		"telefonos": [phone for phone in phones if phone],
		"correo": _company_value(company, "custom_ecf_correo_emisor")
		or _company_value(company, "email"),
		"web_site": _company_value(company, "custom_ecf_web_site")
		or _company_value(company, "website"),
		"actividad_economica": _company_value(company, "custom_ecf_actividad_economica"),
		"fecha_emision": _clean(doc.get("custom_ecf_fecha_emision"))
		or doc.get("posting_date")
		or datetime.date.today(),
	}


def _address_line(address):
	if not address:
		return None
	parts = [_clean(address.get("address_line1")), _clean(address.get("address_line2"))]
	parts = [part for part in parts if part]
	return ", ".join(parts) if parts else None


def _contact_name(contact):
	if not contact:
		return None
	return (
		_clean(getattr(contact, "full_name", None))
		or " ".join(
			part
			for part in (
				_clean(contact.get("first_name")),
				_clean(contact.get("last_name")),
			)
			if part
		)
		or None
	)


def get_buyer(doc):
	"""Returns the data needed by ``<Comprador>``."""
	customer = _get_doc("Customer", doc.get("customer"))
	cert = bool(doc.get("custom_ecf_certification"))
	address = _get_doc(
		"Address",
		doc.get("customer_address")
		or (None if cert else (customer.get("customer_primary_address") if customer else None)),
	)
	contact = _get_doc(
		"Contact",
		doc.get("contact_person")
		or (None if cert else (customer.get("customer_primary_contact") if customer else None)),
	)
	contact_email = None
	if contact:
		contact_email = _clean(contact.get("email_id"))
		if not contact_email and contact.get("email_ids"):
			contact_email = _clean(contact.email_ids[0].email_id)
	return {
		"rnc": _clean(doc.get("tax_id"))
		or (customer and _clean(customer.get("custom_rnc")))
		or (customer and _clean(customer.get("tax_id"))),
		"identificador_extranjero": _clean(doc.get("custom_ecf_identificador_extranjero")),
		"razon_social": _clean(doc.get("customer_name"))
		or (customer and _clean(customer.get("customer_name"))),
		"contacto": _contact_name(contact)
		or (None if cert else _clean(doc.get("contact_display"))),
		"correo": contact_email
		or _clean(doc.get("contact_email"))
		or (None if cert else (customer and _clean(customer.get("email_id")))),
		"direccion": _address_line(address)
		or (None if cert else _clean(doc.get("address_display"))),
		"municipio": (address and _clean(address.get("custom_ecf_municipio")))
		or (address and _clean(address.get("city"))),
		"provincia": (address and _clean(address.get("custom_ecf_provincia")))
		or (address and _clean(address.get("state"))),
		"pais": address
		and (
			_clean(address.get("custom_ecf_pais"))
			or (None if cert else _clean(address.get("country")))
		),
		"fecha_entrega": doc.get("custom_ecf_fecha_entrega"),
		"contacto_entrega": _clean(doc.get("custom_ecf_contacto_entrega")),
		"direccion_entrega": _clean(doc.get("custom_ecf_direccion_entrega")),
		"telefono_adicional": normalize_phone(doc.get("custom_ecf_telefono_adicional")),
		"fecha_orden_compra": doc.get("po_date"),
		"numero_orden_compra": _clean(doc.get("po_no")),
		"codigo_interno_comprador": _clean(doc.get("custom_ecf_codigo_interno_comprador")),
		"responsable_pago": _clean(doc.get("custom_ecf_responsable_pago")),
		"informacion_adicional_comprador": _clean(
			doc.get("custom_ecf_informacion_adicional_comprador")
		),
	}


def get_export(doc):
	"""Returns the E43/E47 transport/export JSON payload."""
	raw = doc.get("custom_ecf_export_data")
	if not raw:
		return {}
	if isinstance(raw, dict):
		return raw
	try:
		data = json.loads(raw)
	except (TypeError, ValueError):
		return {}
	return data if isinstance(data, dict) else {}
