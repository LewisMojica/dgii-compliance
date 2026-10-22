"""Inbound receptor services (Pasos 7-11).

Exposes the standard resource paths required by DGII's "Descripción Técnica
Servicios Emisores Electrónicos":

	POST /fe/recepcion/api/ecf            -> returns a signed ARECF
	POST /fe/aprobacioncomercial/api/ecf  -> returns HTTP 200 / 400

Both receive the XML as a ``multipart/form-data`` field named ``xml``.
Authentication (bearer) is optional and not implemented yet.
"""

import json
import os
import re

import frappe
from frappe.utils import cint, flt, now, now_datetime
from lxml import etree

from dgii_compliance.dgii_compliance.doctype.ecf.new_ecf import get_xml_schema_errors
from dgii_compliance.dgii_compliance.receptor import arecf
from dgii_compliance.dgii_compliance.receptor.xmldsig import verify_signature

DS_NS = "{http://www.w3.org/2000/09/xmldsig#}"
XML_HEADERS = {"Content-Type": "text/xml; charset=utf-8"}
LOGGER_NAME = "dgii_receptor"
DEBUG_SUBDIR = "receptor_debug"
MOTIVO_LABELS = {
	arecf.MOTIVO_ERROR_ESPECIFICACION: "Error de especificación",
	arecf.MOTIVO_ERROR_FIRMA: "Error de firma",
	arecf.MOTIVO_ENVIO_DUPLICADO: "Envío duplicado",
	arecf.MOTIVO_RNC_COMPRADOR: "RNC comprador inválido",
}


def _logger():
	try:
		return frappe.logger(LOGGER_NAME, allow_site=True)
	except Exception:
		return None


def _log(message, *args):
	try:
		text = message % args if args else message
	except Exception:
		text = message
	logger = _logger()
	if logger:
		try:
			logger.info(message, *args)
		except Exception:
			pass
	if getattr(frappe.flags, "in_test", False):
		return
	try:
		path = frappe.get_site_path("logs", "dgii_receptor.log")
		with open(path, "a", encoding="utf-8") as handle:
			handle.write(f"{now_datetime()} {text}\n")
	except Exception:
		pass


def _debug_dir():
	path = frappe.get_site_path("private", "files", "dgii_compliance", DEBUG_SUBDIR)
	os.makedirs(path, exist_ok=True)
	return path


def _save_debug(prefix, encf, data):
	"""Persists the raw e-CF / ARECF so failed DGII tests can be diagnosed."""
	if getattr(frappe.flags, "in_test", False):
		return None
	try:
		timestamp = now_datetime().strftime("%Y%m%d_%H%M%S_%f")
		safe_encf = re.sub(r"[^A-Za-z0-9_.-]", "_", encf or "unknown")
		suffix = ".json" if isinstance(data, (dict, list)) else ".xml"
		path = os.path.join(_debug_dir(), f"{timestamp}_{prefix}_{safe_encf}{suffix}")
		if isinstance(data, (dict, list)):
			with open(path, "w", encoding="utf-8") as handle:
				json.dump(data, handle, ensure_ascii=False, indent=2, default=str)
		else:
			if isinstance(data, str):
				data = data.encode("utf-8")
			with open(path, "wb") as handle:
				handle.write(data)
		return path
	except Exception as exc:
		_log("No se pudo guardar el debug del receptor: %s", exc)
		return None


def _request_info():
	request = frappe.request
	if not request:
		return {}
	forwarded_for = request.headers.get("X-Forwarded-For")
	remote_addr = (
		forwarded_for.split(",", 1)[0].strip()
		if forwarded_for
		else getattr(request, "remote_addr", None)
	)
	return {
		"remote_addr": remote_addr,
		"method": getattr(request, "method", None),
		"content_type": getattr(request, "content_type", None),
		"content_length": getattr(request, "content_length", None),
		"user_agent": request.headers.get("User-Agent"),
		"authorization_present": bool(request.headers.get("Authorization")),
	}


SETTINGS_DOCTYPE = "DGII Compliance Settings"


def _setting(fieldname):
	try:
		return frappe.db.get_single_value(SETTINGS_DOCTYPE, fieldname)
	except Exception:
		return None


def _dgii_environment():
	return (_setting("dgii_environment") or "").strip()


def _soft_signature_enabled():
	"""Soft signature acceptance is only allowed in DGII test environments."""
	if _dgii_environment() not in ("testecf", "certecf"):
		return False

	setting = _setting("allow_unverified_received_signatures")
	if setting is not None:
		return bool(cint(setting))

	# Backward-compatible fallback for sites that have not migrated the setting yet.
	return bool(cint((frappe.conf or {}).get("dgii_receptor_soft_signature")))


def _receptor_rnc():
	value = (_setting("receptor_rnc") or "").strip()
	if value:
		return value
	return ((frappe.conf or {}).get("dgii_receptor_rnc") or "").strip()


def _read_uploaded_xml():
	if not frappe.request:
		return None
	uploaded = frappe.request.files.get("xml")
	if uploaded:
		return uploaded.read()
	data = frappe.request.get_data()
	return data or None


def _verify_signature_detail(root):
	"""Verifies the enveloped signature using the embedded X509 certificate.

	Returns ``(ok, method, error)``. ``method`` is ``signxml`` for correctly
	signed documents and ``c14n-exclusive`` for DGII's certification quirk.
	"""
	result = verify_signature(root)
	return result.ok, result.method, result.error


def _verify_signature(root):
	return _verify_signature_detail(root)[0]


def _has_signature(root):
	return root.find(f".//{DS_NS}Signature") is not None


def _extract(root):
	return (
		(root.findtext("Encabezado/IdDoc/TipoeCF") or "").strip(),
		(root.findtext("Encabezado/IdDoc/eNCF") or "").strip(),
		(root.findtext(".//RNCEmisor") or "").strip(),
		(root.findtext(".//RNCComprador") or "").strip(),
	)


def _is_duplicate(rnc_emisor, encf):
	"""Only accepted receptions count as duplicates.

	Rejected attempts are stored for diagnostics and must not block DGII from
	retrying the same e-NCF after we fix a verification issue.
	"""
	return bool(
		frappe.db.exists(
			"eCF",
			{
				"direction": "Recibido",
				"status": "accepted",
				"rnc_emisor": rnc_emisor,
				"encf": encf,
			},
		)
	)


def process_recepcion(raw):
	"""Pure-ish receipt logic. Returns a dict with the ARECF and the state."""
	info = _request_info()
	parse_error = None
	root = None
	tipo = encf = rnc_emisor = rnc_comprador = ""
	schema_errors = []
	signature_ok = False
	signature_method = None
	signature_error = "No se procesó la firma"

	try:
		root = etree.fromstring(raw)
	except Exception as exc:
		parse_error = f"{type(exc).__name__}: {exc}"
		_log("Recepción: XML no parseable (%s)", parse_error)
		raw_path = _save_debug("request", "unparseable", raw)
		result = {
			"estado": 1,
			"motivo": arecf.MOTIVO_ERROR_ESPECIFICACION,
			"arecf": None,
			"tipo": tipo,
			"encf": encf,
			"rnc_emisor": rnc_emisor,
			"rnc_comprador": rnc_comprador,
			"rnc_receptor": _receptor_rnc(),
			"root": None,
			"raw": raw,
			"parse_error": parse_error,
			"schema_errors": ["XML no parseable"],
			"signature_ok": False,
			"signature_method": None,
			"signature_error": signature_error,
			"soft_signature": False,
			"request": info,
			"raw_debug_path": raw_path,
		}
		_log("Recepción RECHAZADA parse_error=%s raw=%s", parse_error, raw_path)
		return result

	tipo, encf, rnc_emisor, rnc_comprador = _extract(root)

	if tipo and encf and rnc_emisor:
		try:
			schema_errors = get_xml_schema_errors(root, f"E{tipo}")
		except Exception as exc:
			schema_errors = [f"{type(exc).__name__}: {exc}"]
		signature_ok, signature_method, signature_error = _verify_signature_detail(root)
	else:
		schema_errors = ["Faltan campos obligatorios del e-CF"]
		signature_error = "No se verificó la firma: faltan campos obligatorios"

	# The ARECF's RNCComprador identifies the taxpayer that issues the acuse
	# (us), not necessarily the buyer printed on the incoming e-CF.
	rnc_receptor = _receptor_rnc() or rnc_comprador
	estado, motivo = 0, None

	if not (tipo and encf and rnc_emisor and rnc_receptor):
		estado, motivo = 1, arecf.MOTIVO_ERROR_ESPECIFICACION
	elif schema_errors:
		estado, motivo = 1, arecf.MOTIVO_ERROR_ESPECIFICACION
	elif not signature_ok:
		if _soft_signature_enabled() and _has_signature(root):
			signature_method = "soft"
			_log(
				"Recepción: firma no verificable para %s/%s, aceptada por "
				"allow_unverified_received_signatures (%s)",
				rnc_emisor,
				encf,
				signature_error,
			)
		else:
			estado, motivo = 1, arecf.MOTIVO_ERROR_FIRMA
	elif _is_duplicate(rnc_emisor, encf):
		estado, motivo = 1, arecf.MOTIVO_ENVIO_DUPLICADO

	arecf_xml = None
	if rnc_emisor and encf and rnc_receptor:
		try:
			arecf_xml = arecf.build_signed(
				rnc_emisor, encf, rnc_receptor, estado=estado, motivo=motivo
			)
		except Exception as exc:
			_log("Recepción: no se pudo construir/firmar el ARECF: %s", exc)

	raw_path = _save_debug("request", encf, raw)
	arecf_path = _save_debug("arecf", encf, arecf_xml or "")
	result = {
		"estado": estado,
		"motivo": motivo,
		"arecf": arecf_xml,
		"tipo": tipo,
		"encf": encf,
		"rnc_emisor": rnc_emisor,
		"rnc_comprador": rnc_comprador,
		"rnc_receptor": rnc_receptor,
		"root": root,
		"raw": raw,
		"parse_error": parse_error,
		"schema_errors": schema_errors,
		"signature_ok": signature_ok,
		"signature_method": signature_method,
		"signature_error": signature_error,
		"soft_signature": estado == 0 and not signature_ok and _has_signature(root),
		"request": info,
		"raw_debug_path": raw_path,
		"arecf_debug_path": arecf_path,
	}
	_save_debug("result", encf, result)
	_log(
		"Recepción ip=%s tipo=%s encf=%s emisor=%s comprador=%s receptor=%s "
		"estado=%s motivo=%s schema=%s firma=%s metodo_firma=%s error_firma=%s "
		"raw=%s arecf=%s",
		info.get("remote_addr"),
		tipo,
		encf,
		rnc_emisor,
		rnc_comprador,
		rnc_receptor,
		estado,
		motivo,
		schema_errors or "ok",
		"ok" if signature_ok else "error",
		signature_method or "-",
		signature_error,
		raw_path,
		arecf_path,
	)
	return result


def _store_attempt(result):
	"""Stores every reception attempt so the eCF list shows DGII's tests.

	Rejected attempts use ``status=rejected`` and do not count as duplicates.
	"""
	if not frappe.db:
		return None

	motivo = result.get("motivo")
	mensaje = MOTIVO_LABELS.get(motivo, "")
	if result.get("parse_error"):
		mensaje = f"XML no parseable: {result['parse_error']}"
	elif result.get("schema_errors"):
		mensaje = f"{mensaje}: {' | '.join(result['schema_errors'])}".strip(": ")
	elif result.get("soft_signature"):
		mensaje = f"{mensaje}: firma no verificada (modo prueba)".strip(": ")
	if not mensaje:
		mensaje = "Recibido correctamente" if result.get("estado") == 0 else "No recibido"

	estado_label = "Recibido" if result.get("estado") == 0 else "No recibido"
	status = "accepted" if result.get("estado") == 0 else "rejected"
	if result.get("parse_error"):
		status = "failed"

	xml_value = result.get("raw") or b""
	if isinstance(xml_value, bytes):
		xml_value = xml_value.decode("utf-8", "replace")

	doc = frappe.get_doc(
		{
			"doctype": "eCF",
			"direction": "Recibido",
			"rnc_emisor": result.get("rnc_emisor") or None,
			"rnc_comprador": result.get("rnc_comprador") or None,
			"encf": result.get("encf") or None,
			"status": status,
			"estado": estado_label,
			"mensaje": mensaje,
			"received_at": now(),
			"xml": xml_value,
			"arecf_xml": result.get("arecf") or None,
		}
	)
	doc.insert(ignore_permissions=True)
	return doc.name


def handle_recepcion():
	raw = _read_uploaded_xml()
	if not raw:
		return b"", 400, {}
	result = process_recepcion(raw)
	try:
		_stored = _store_attempt(result)
		_log("Recepción: intento guardado en eCF %s", _stored)
	except Exception as exc:
		_log("Recepción: no se pudo guardar el intento en eCF: %s", exc)
	return (result["arecf"] or "").encode("utf-8"), 200, XML_HEADERS


def _extract_aprobacion(root):
	return {
		"rnc_emisor": (root.findtext(".//RNCEmisor") or "").strip(),
		"encf": (root.findtext(".//eNCF") or "").strip(),
		"rnc_comprador": (root.findtext(".//RNCComprador") or "").strip(),
		"estado_acecf": (root.findtext(".//Estado") or "").strip(),
		"fecha_emision": (root.findtext(".//FechaEmision") or "").strip(),
		"monto_total": (root.findtext(".//MontoTotal") or "").strip(),
		"detalle_motivo_rechazo": (root.findtext(".//DetalleMotivoRechazo") or "").strip(),
		"fecha_hora_aprobacion_comercial": (
			root.findtext(".//FechaHoraAprobacionComercial") or ""
		).strip(),
	}


def process_aprobacion(raw):
	"""Validates an incoming ACECF and returns the result for logging."""
	info = _request_info()
	fields = {
		"rnc_emisor": "",
		"encf": "",
		"rnc_comprador": "",
		"estado_acecf": "",
		"fecha_emision": "",
		"monto_total": "",
		"detalle_motivo_rechazo": "",
		"fecha_hora_aprobacion_comercial": "",
	}
	parse_error = None
	schema_errors = []
	signature_ok = False
	signature_method = None
	signature_error = "No se procesó la firma"
	root = None

	try:
		root = etree.fromstring(raw)
	except Exception as exc:
		parse_error = f"{type(exc).__name__}: {exc}"
		_log("Aprobación: XML no parseable (%s)", parse_error)
	else:
		fields = _extract_aprobacion(root)
		try:
			schema_errors = get_xml_schema_errors(root, "ACECF")
		except Exception as exc:
			schema_errors = [f"{type(exc).__name__}: {exc}"]
		signature_ok, signature_method, signature_error = _verify_signature_detail(root)

	soft_accepted = False
	ok = not parse_error and not schema_errors and signature_ok
	if not ok and not parse_error and not schema_errors and not signature_ok:
		if _soft_signature_enabled() and root is not None and _has_signature(root):
			ok = True
			soft_accepted = True
			signature_method = "soft"
			_log(
				"Aprobación: firma no verificable para %s/%s, aceptada por "
				"allow_unverified_received_signatures (%s)",
				fields["rnc_emisor"],
				fields["encf"],
				signature_error,
			)

	raw_path = _save_debug("acecf_request", fields["encf"], raw)
	result = {
		"ok": ok,
		"fields": fields,
		"parse_error": parse_error,
		"schema_errors": schema_errors,
		"signature_ok": signature_ok,
		"signature_method": signature_method,
		"signature_error": signature_error,
		"soft_accepted": soft_accepted,
		"request": info,
		"raw_debug_path": raw_path,
	}
	result_path = _save_debug("acecf_result", fields["encf"], result)
	_log(
		"Aprobación ip=%s emisor=%s encf=%s comprador=%s estado_acecf=%s "
		"schema=%s firma=%s metodo_firma=%s error_firma=%s ok=%s raw=%s result=%s",
		info.get("remote_addr"),
		fields["rnc_emisor"],
		fields["encf"],
		fields["rnc_comprador"],
		fields["estado_acecf"],
		schema_errors or "ok",
		"ok" if signature_ok else "error",
		signature_method or "-",
		signature_error,
		ok,
		raw_path,
		result_path,
	)
	return result


def _store_aprobacion(result):
	"""Stores the received ACECF in the eCF Aprobacion Comercial list."""
	fields = result.get("fields") or {}
	rnc_emisor = (fields.get("rnc_emisor") or "").strip()
	encf = (fields.get("encf") or "").strip()
	if not (rnc_emisor and encf):
		return None

	received_ecf = frappe.db.get_value(
		"eCF", {"direction": "Recibido", "encf": encf}, "name"
	)
	existing = frappe.db.get_value(
		"eCF Aprobacion Comercial",
		{"direction": "Recibido", "rnc_emisor": rnc_emisor, "encf": encf},
		"name",
	)

	if existing:
		doc = frappe.get_doc("eCF Aprobacion Comercial", existing)
	else:
		doc = frappe.new_doc("eCF Aprobacion Comercial")
		doc.direction = "Recibido"

	doc.rnc_emisor = rnc_emisor
	doc.encf = encf
	doc.rnc_comprador = fields.get("rnc_comprador") or _receptor_rnc()
	doc.fecha_emision = fields.get("fecha_emision") or None
	doc.monto_total = flt(fields.get("monto_total") or 0)
	doc.estado_acecf = fields.get("estado_acecf") or "1"
	doc.detalle_motivo_rechazo = fields.get("detalle_motivo_rechazo") or None
	doc.fecha_hora_aprobacion_comercial = (
		fields.get("fecha_hora_aprobacion_comercial") or None
	)
	doc.received_ecf = received_ecf
	doc.received_at = now()
	doc.verification_method = result.get("signature_method")
	doc.source_ip = (result.get("request") or {}).get("remote_addr")
	doc.status = "received" if result.get("ok") else "rejected"

	if result.get("parse_error"):
		message = f"XML no parseable: {result['parse_error']}"
	elif result.get("schema_errors"):
		message = "Rechazado: " + " | ".join(result["schema_errors"])
	elif result.get("signature_ok"):
		message = f"Recibido; firma verificada ({result.get('signature_method')})"
	elif result.get("soft_accepted"):
		message = (
			"Recibido en modo prueba; firma no verificada: "
			f"{result.get('signature_error')}"
		)
	else:
		message = f"Rechazado; firma no verificada: {result.get('signature_error')}"
	doc.respuesta_mensaje = message

	raw = result.get("raw")
	if raw is None:
		raw_path = result.get("raw_debug_path")
		if raw_path and os.path.exists(raw_path):
			raw = open(raw_path, "rb").read()
	if isinstance(raw, bytes):
		raw = raw.decode("utf-8", "replace")
	doc.xml = raw

	if existing:
		doc.save(ignore_permissions=True)
	else:
		doc.insert(ignore_permissions=True)
	return doc.name


def handle_aprobacion():
	raw = _read_uploaded_xml()
	if not raw:
		return b"", 400, {}
	result = process_aprobacion(raw)
	result["raw"] = raw
	try:
		_stored = _store_aprobacion(result)
		_log("Aprobación: intento guardado en eCF Aprobacion Comercial %s", _stored)
	except Exception as exc:
		_log("Aprobación: no se pudo guardar el intento: %s", exc)
	return b"", (200 if result["ok"] else 400), {}
