"""Outbound client for DGII electronic invoicing services.

Handles authentication (semilla -> token), e-CF reception and status queries.
Environment is hardcoded for now; switch ``DGII_ENVIRONMENT`` to move between
``testecf`` (pre-certification), ``certecf`` (certification) and ``ecf``
(production).
"""

import requests
import frappe
from frappe import _
from frappe.utils import get_datetime, now_datetime
from lxml import etree

from dgii_compliance.dgii_compliance.doctype.ecf.signer import (
	get_dgii_file_path,
	sign_xml,
)

DGII_ENVIRONMENT = "testecf"

ECF_BASE_URL = f"https://ecf.dgii.gov.do/{DGII_ENVIRONMENT}"
FC_BASE_URL = f"https://fc.dgii.gov.do/{DGII_ENVIRONMENT}"

TOKEN_CACHE_PREFIX = "dgii:token"
TOKEN_SAFETY_MARGIN_SECONDS = 300
TOKEN_FALLBACK_TTL_SECONDS = 3000
REQUEST_TIMEOUT = 30

# Maps DGII response states to eCF.status values
ESTADO_STATUS_MAP = {
	"aceptado": "accepted",
	"aceptado condicional": "accepted_conditional",
	"rechazado": "rejected",
	"en proceso": "sent",
	"recibido": "sent",
}


def _normalize(data):
	return {str(key).lower(): value for key, value in (data or {}).items()}


def _parse_response(response):
	"""Parses a DGII response that may be JSON or XML into a flat dict."""
	content_type = (response.headers or {}).get("Content-Type", "")
	text = response.text or ""
	if "json" in content_type.lower() or text.lstrip().startswith(("{", "[")):
		data = response.json()
		if isinstance(data, list):
			return {"data": data}
		return _normalize(data)

	root = etree.fromstring(response.content)
	data = {}
	mensajes = []
	for node in root.iter():
		if not isinstance(node.tag, str):
			continue
		tag = etree.QName(node).localname
		if tag == "mensaje" and node.text:
			mensajes.append(node.text.strip())
			continue
		if node.text and node.text.strip() and tag not in data:
			data[tag] = node.text.strip()
	if mensajes:
		data["mensajes"] = mensajes
	return _normalize(data)


def _get_certificate_credentials():
	key_pem = open(get_dgii_file_path("key.pem"), "rb").read()
	cert_pem = open(get_dgii_file_path("certificate.pem"), "rb").read()
	return key_pem, cert_pem


def _raise_for_status(response):
	"""Raises a Frappe error that includes DGII's response body, if any."""
	if response.status_code < 400:
		return
	detail = (response.text or "").strip()
	message = _("DGII respondió con error {0}").format(response.status_code)
	if detail:
		message = f"{message}: {detail}"
	frappe.throw(message)


def get_semilla():
	"""Requests the authentication seed (semilla) from DGII."""
	url = f"{ECF_BASE_URL}/autenticacion/api/autenticacion/semilla"
	response = requests.get(url, timeout=REQUEST_TIMEOUT)
	_raise_for_status(response)
	return response.content


def _sign_semilla(semilla_xml):
	key_pem, cert_pem = _get_certificate_credentials()
	root = etree.fromstring(semilla_xml)
	signed = sign_xml(root, key_pem, cert_pem)
	return etree.tostring(signed)


def _request_new_token():
	"""Fetches and signs a semilla, then exchanges it for a fresh token."""
	signed_semilla = _sign_semilla(get_semilla())
	url = f"{ECF_BASE_URL}/autenticacion/api/autenticacion/validarsemilla"
	response = requests.post(
		url,
		files={"xml": ("semilla.xml", signed_semilla, "text/xml")},
		timeout=REQUEST_TIMEOUT,
	)
	_raise_for_status(response)

	data = _parse_response(response)
	token = data.get("token")
	if not token:
		frappe.throw(_("DGII no retornó un token de autenticación."))
	return token, data.get("expira")


def _token_ttl(expira):
	if not expira:
		return TOKEN_FALLBACK_TTL_SECONDS
	try:
		remaining = (get_datetime(expira) - now_datetime()).total_seconds()
	except Exception:
		return TOKEN_FALLBACK_TTL_SECONDS
	return int(max(remaining - TOKEN_SAFETY_MARGIN_SECONDS, 60))


def _token_cache_key(rnc):
	return f"{TOKEN_CACHE_PREFIX}:{DGII_ENVIRONMENT}:{rnc}"


def get_token(rnc):
	"""Returns a valid DGII token, reusing a cached one while it lasts."""
	cache_key = _token_cache_key(rnc)
	cached = frappe.cache.get_value(cache_key)
	if cached:
		return cached

	token, expira = _request_new_token()
	frappe.cache.set_value(cache_key, token, expires_in_sec=_token_ttl(expira))
	return token


def _clear_token(rnc):
	frappe.cache.delete_value(_token_cache_key(rnc))


def _post_ecf(url, xml_content, filename, token):
	return requests.post(
		url,
		files={"xml": (filename, xml_content, "text/xml")},
		headers={"Authorization": f"bearer {token}"},
		timeout=REQUEST_TIMEOUT,
	)


def send_ecf(xml_content, rnc, encf, token=None):
	"""Sends a signed e-CF to DGII's reception service.

	Retries once with a fresh token if DGII rejects the session (401).
	"""
	if isinstance(xml_content, str):
		xml_content = xml_content.encode()

	if token is None:
		token = get_token(rnc)

	url = f"{ECF_BASE_URL}/recepcion/api/facturaselectronicas"
	filename = f"{rnc}{encf}.xml"

	response = _post_ecf(url, xml_content, filename, token)
	if response.status_code == 401:
		_clear_token(rnc)
		token = get_token(rnc)
		response = _post_ecf(url, xml_content, filename, token)

	_raise_for_status(response)
	return _parse_response(response)


def query_estado(track_id, rnc):
	"""Queries the validation status of a previously submitted e-CF."""
	token = get_token(rnc)
	url = f"{ECF_BASE_URL}/consultaresultado/api/consultas/estado"
	response = requests.get(
		url,
		params={"trackid": track_id},
		headers={"Authorization": f"bearer {token}"},
		timeout=REQUEST_TIMEOUT,
	)
	_raise_for_status(response)
	return _parse_response(response)


def map_estado_to_status(estado):
	if not estado:
		return "sent"
	return ESTADO_STATUS_MAP.get(str(estado).strip().lower(), "sent")


def _extract_rnc_and_encf(xml_content):
	root = etree.fromstring(xml_content.encode() if isinstance(xml_content, str) else xml_content)
	rnc = root.findtext(".//RNCEmisor") or ""
	encf = root.findtext("Encabezado/IdDoc/eNCF") or ""
	return rnc.strip(), encf.strip()


def _format_mensajes(mensajes):
	if not mensajes:
		return None
	if isinstance(mensajes, str):
		return mensajes
	parts = []
	for message in mensajes:
		if isinstance(message, dict):
			parts.append(f"{message.get('codigo', '')}: {message.get('valor', '')}".strip(": "))
		else:
			parts.append(str(message))
	return "\n".join(parts)


def _collect_mensaje(result):
	"""Builds a message from a DGII response.

	Reception returns singular ``error``/``mensaje``; the status query returns
	a ``mensajes`` list. Both are combined here.
	"""
	parts = []
	for key in ("error", "mensaje"):
		value = result.get(key)
		if value:
			parts.append(str(value).strip())
	formatted = _format_mensajes(result.get("mensajes"))
	if formatted:
		parts.append(formatted)
	return "\n".join(part for part in parts if part) or None


@frappe.whitelist()
def send_ecf_to_dgii(ecf_name):
	"""Sends the stored signed e-CF and records DGII's response."""
	doc = frappe.get_doc("eCF", ecf_name)
	if not doc.xml:
		frappe.throw(_("El e-CF no tiene XML firmado para enviar."))

	rnc, encf = _extract_rnc_and_encf(doc.xml)
	if not rnc or not encf:
		frappe.throw(_("No se pudo obtener el RNC o el e-NCF del XML."))

	result = send_ecf(doc.xml, rnc, encf)

	doc.track_id = result.get("trackid")
	doc.estado = result.get("estado")
	doc.mensaje = _collect_mensaje(result)
	doc.sent_at = now_datetime()
	doc.status = map_estado_to_status(doc.estado) if doc.estado else "sent"
	doc.save(ignore_permissions=True)

	return {
		"status": doc.status,
		"estado": doc.estado,
		"track_id": doc.track_id,
		"mensaje": doc.mensaje,
	}


@frappe.whitelist()
def refresh_ecf_status(ecf_name):
	"""Fetches the validation status of a sent e-CF from DGII."""
	doc = frappe.get_doc("eCF", ecf_name)
	if not doc.track_id:
		frappe.throw(_("El e-CF no tiene Track ID. Envíelo a DGII primero."))

	rnc, _ = _extract_rnc_and_encf(doc.xml)
	if not rnc:
		frappe.throw(_("No se pudo obtener el RNC del XML."))

	result = query_estado(doc.track_id, rnc)

	doc.estado = result.get("estado")
	doc.mensaje = _collect_mensaje(result)
	fecha_recepcion = result.get("fecharecepcion")
	if fecha_recepcion:
		doc.fecha_recepcion = get_datetime(fecha_recepcion)
	if doc.estado:
		doc.status = map_estado_to_status(doc.estado)
	doc.save(ignore_permissions=True)

	return {
		"status": doc.status,
		"estado": doc.estado,
		"track_id": doc.track_id,
		"mensaje": doc.mensaje,
		"fecha_recepcion": doc.fecha_recepcion,
	}
