"""Inbound receptor services (Pasos 7-11).

Exposes the standard resource paths required by DGII's "Descripción Técnica
Servicios Emisores Electrónicos":

	POST /fe/recepcion/api/ecf            -> returns a signed ARECF
	POST /fe/aprobacioncomercial/api/ecf  -> returns HTTP 200 / 400

Both receive the XML as a ``multipart/form-data`` field named ``xml``.
Authentication (bearer) is optional and not implemented yet.
"""

import base64

import frappe
from cryptography import x509
from cryptography.hazmat.primitives import serialization
from frappe.utils import now
from lxml import etree
from signxml import XMLVerifier

from dgii_compliance.dgii_compliance.doctype.ecf.new_ecf import validate_xml_schema
from dgii_compliance.dgii_compliance.receptor import arecf

DS_NS = "{http://www.w3.org/2000/09/xmldsig#}"
XML_HEADERS = {"Content-Type": "text/xml; charset=utf-8"}


def _read_uploaded_xml():
	if not frappe.request:
		return None
	uploaded = frappe.request.files.get("xml")
	if uploaded:
		return uploaded.read()
	data = frappe.request.get_data()
	return data or None


def _verify_signature(root):
	"""Verifies the enveloped signature using the embedded X509 certificate."""
	cert_b64 = root.findtext(f".//{DS_NS}X509Certificate")
	if not cert_b64:
		return False
	try:
		cert = x509.load_der_x509_certificate(base64.b64decode(cert_b64))
		pem = cert.public_bytes(serialization.Encoding.PEM)
		XMLVerifier().verify(root, x509_cert=pem)
		return True
	except Exception:
		return False


def _extract(root):
	return (
		(root.findtext("Encabezado/IdDoc/TipoeCF") or "").strip(),
		(root.findtext("Encabezado/IdDoc/eNCF") or "").strip(),
		(root.findtext(".//RNCEmisor") or "").strip(),
		(root.findtext(".//RNCComprador") or "").strip(),
	)


def _is_duplicate(rnc_emisor, encf):
	return bool(
		frappe.db.exists(
			"eCF", {"direction": "Recibido", "rnc_emisor": rnc_emisor, "encf": encf}
		)
	)


def process_recepcion(raw):
	"""Pure-ish receipt logic. Returns a dict with the ARECF and the state."""
	try:
		root = etree.fromstring(raw)
	except Exception:
		return {"estado": 1, "motivo": arecf.MOTIVO_ERROR_ESPECIFICACION, "arecf": None}

	tipo, encf, rnc_emisor, rnc_comprador = _extract(root)
	estado, motivo = 0, None

	if not (tipo and encf and rnc_emisor and rnc_comprador):
		estado, motivo = 1, arecf.MOTIVO_ERROR_ESPECIFICACION
	elif not validate_xml_schema(root, f"E{tipo}"):
		estado, motivo = 1, arecf.MOTIVO_ERROR_ESPECIFICACION
	elif not _verify_signature(root):
		estado, motivo = 1, arecf.MOTIVO_ERROR_FIRMA
	elif _is_duplicate(rnc_emisor, encf):
		estado, motivo = 1, arecf.MOTIVO_ENVIO_DUPLICADO

	arecf_xml = arecf.build_signed(rnc_emisor, encf, rnc_comprador, estado=estado, motivo=motivo)
	return {
		"estado": estado,
		"motivo": motivo,
		"arecf": arecf_xml,
		"tipo": tipo,
		"encf": encf,
		"rnc_emisor": rnc_emisor,
		"rnc_comprador": rnc_comprador,
		"root": root,
		"raw": raw,
	}


def _store_received(result):
	doc = frappe.get_doc(
		{
			"doctype": "eCF",
			"direction": "Recibido",
			"rnc_emisor": result["rnc_emisor"],
			"rnc_comprador": result["rnc_comprador"],
			"encf": result["encf"],
			"status": "accepted",
			"estado": "Recibido",
			"received_at": now(),
			"xml": result["raw"].decode("utf-8", "replace")
			if isinstance(result["raw"], bytes)
			else result["raw"],
			"arecf_xml": result["arecf"],
		}
	)
	doc.insert(ignore_permissions=True)


def handle_recepcion():
	raw = _read_uploaded_xml()
	if not raw:
		return b"", 400, {}
	result = process_recepcion(raw)
	if result["estado"] == 0 and result["arecf"]:
		_store_received(result)
	return (result["arecf"] or "").encode("utf-8"), 200, XML_HEADERS


def handle_aprobacion():
	raw = _read_uploaded_xml()
	ok = False
	if raw:
		try:
			root = etree.fromstring(raw)
			ok = validate_xml_schema(root, "ACECF") and _verify_signature(root)
		except Exception:
			ok = False
	return b"", (200 if ok else 400), {}
