"""XMLDSig verification helpers for received DGII documents.

DGII's certification signer declares inclusive C14N on ``SignedInfo`` but
actually signs the exclusive-C14N representation. ``signxml`` follows the
declaration and reports ``InvalidSignature`` even though the document digest
is intact. This module first tries ``signxml`` and then falls back to a small
manual verifier that checks the signature over the exclusive-C14N
``SignedInfo`` and validates the Reference digest.
"""

import base64
import copy
from dataclasses import dataclass

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
from lxml import etree
from signxml import XMLVerifier

DS_NS = "http://www.w3.org/2000/09/xmldsig#"
DS = f"{{{DS_NS}}}"

ENVELOPED_SIGNATURE = "http://www.w3.org/2000/09/xmldsig#enveloped-signature"
C14N_INCLUSIVE = "http://www.w3.org/TR/2001/REC-xml-c14n-20010315"
C14N_INCLUSIVE_COMMENTS = "http://www.w3.org/TR/2001/REC-xml-c14n-20010315#WithComments"
C14N_EXCLUSIVE = "http://www.w3.org/2001/10/xml-exc-c14n#"
C14N_EXCLUSIVE_COMMENTS = "http://www.w3.org/2001/10/xml-exc-c14n#WithComments"

SIGNATURE_METHODS = {
	"http://www.w3.org/2001/04/xmldsig-more#rsa-sha256": (rsa.RSAPublicKey, hashes.SHA256),
	"http://www.w3.org/2001/04/xmldsig-more#rsa-sha384": (rsa.RSAPublicKey, hashes.SHA384),
	"http://www.w3.org/2001/04/xmldsig-more#rsa-sha512": (rsa.RSAPublicKey, hashes.SHA512),
	"http://www.w3.org/2000/09/xmldsig#rsa-sha1": (rsa.RSAPublicKey, hashes.SHA1),
	"http://www.w3.org/2001/04/xmldsig-more#rsa-sha1": (rsa.RSAPublicKey, hashes.SHA1),
	"http://www.w3.org/2001/04/xmldsig-more#ecdsa-sha256": (ec.EllipticCurvePublicKey, hashes.SHA256),
	"http://www.w3.org/2001/04/xmldsig-more#ecdsa-sha384": (ec.EllipticCurvePublicKey, hashes.SHA384),
	"http://www.w3.org/2001/04/xmldsig-more#ecdsa-sha512": (ec.EllipticCurvePublicKey, hashes.SHA512),
}

DIGEST_METHODS = {
	"http://www.w3.org/2000/09/xmldsig#sha1": hashes.SHA1,
	"http://www.w3.org/2001/04/xmlenc#sha256": hashes.SHA256,
	"http://www.w3.org/2001/04/xmldsig-more#sha384": hashes.SHA384,
	"http://www.w3.org/2001/04/xmlenc#sha512": hashes.SHA512,
}


@dataclass
class VerificationResult:
	ok: bool
	method: str | None = None
	error: str | None = None


def _load_certificate(root):
	cert_b64 = root.findtext(f".//{DS}X509Certificate")
	if not cert_b64:
		raise ValueError("No se encontró X509Certificate en la firma")
	return x509.load_der_x509_certificate(base64.b64decode(cert_b64.strip()))


def _certificate_pem(cert):
	return cert.public_bytes(serialization.Encoding.PEM)


def _canonicalize(element, algorithm):
	exclusive = algorithm in (C14N_EXCLUSIVE, C14N_EXCLUSIVE_COMMENTS)
	with_comments = algorithm in (C14N_INCLUSIVE_COMMENTS, C14N_EXCLUSIVE_COMMENTS)
	return etree.tostring(
		element,
		method="c14n",
		exclusive=exclusive,
		with_comments=with_comments,
	)


def _signature_algorithm(signed_info):
	method = signed_info.find(f"{DS}SignatureMethod")
	algorithm = method.get("Algorithm") if method is not None else None
	if algorithm not in SIGNATURE_METHODS:
		raise ValueError(f"Algoritmo de firma no soportado: {algorithm}")
	return SIGNATURE_METHODS[algorithm]


def _verify_signature_value(public_key, signature, data, expected_key_type, hash_algorithm):
	if not isinstance(public_key, expected_key_type):
		raise ValueError(
			f"El tipo de llave del certificado no corresponde al algoritmo de firma "
			f"({type(public_key).__name__})"
		)

	if isinstance(public_key, rsa.RSAPublicKey):
		public_key.verify(signature, data, padding.PKCS1v15(), hash_algorithm())
		return

	# XMLDSig encodes ECDSA signatures as raw r||s; cryptography expects DER.
	key_size = (public_key.key_size + 7) // 8
	if len(signature) == 2 * key_size:
		r = int.from_bytes(signature[:key_size], "big")
		s = int.from_bytes(signature[key_size:], "big")
		signature = encode_dss_signature(r, s)
	public_key.verify(signature, data, ec.ECDSA(hash_algorithm()))


def _verify_reference(root, signature, signed_info):
	references = signed_info.findall(f"{DS}Reference")
	if not references:
		raise ValueError("La firma no contiene Reference")

	default_c14n = signed_info.find(f"{DS}CanonicalizationMethod")
	default_c14n_algorithm = (
		default_c14n.get("Algorithm") if default_c14n is not None else C14N_INCLUSIVE
	)

	for reference in references:
		uri = (reference.get("URI") or "").strip()
		if uri:
			raise ValueError(f"Reference URI no soportado: {uri}")

		transforms = reference.findall(f"{DS}Transforms/{DS}Transform")
		c14n_algorithm = None
		document = copy.deepcopy(root)
		document_signature = document.find(f".//{DS}Signature")
		if document_signature is None:
			raise ValueError("No se encontró la firma al preparar el digest")

		for transform in transforms:
			algorithm = transform.get("Algorithm")
			if algorithm == ENVELOPED_SIGNATURE:
				document_signature.getparent().remove(document_signature)
			elif algorithm in (
				C14N_INCLUSIVE,
				C14N_INCLUSIVE_COMMENTS,
				C14N_EXCLUSIVE,
				C14N_EXCLUSIVE_COMMENTS,
			):
				c14n_algorithm = algorithm
			else:
				raise ValueError(f"Transform no soportado: {algorithm}")

		c14n_algorithm = c14n_algorithm or default_c14n_algorithm
		expected_digest = base64.b64decode(reference.findtext(f"{DS}DigestValue").strip())
		digest_method = reference.find(f"{DS}DigestMethod")
		digest_algorithm = digest_method.get("Algorithm") if digest_method is not None else None
		if digest_algorithm not in DIGEST_METHODS:
			raise ValueError(f"Algoritmo de digest no soportado: {digest_algorithm}")

		canonical_document = _canonicalize(document, c14n_algorithm)
		actual_digest = hashes.Hash(DIGEST_METHODS[digest_algorithm]())
		actual_digest.update(canonical_document)
		if actual_digest.finalize() != expected_digest:
			raise ValueError("El digest del documento no coincide con el valor firmado")


def _verify_with_exclusive_c14n(root, cert):
	signature = root.find(f".//{DS}Signature")
	if signature is None:
		raise ValueError("El XML no contiene Signature")

	signed_info = signature.find(f"{DS}SignedInfo")
	if signed_info is None:
		raise ValueError("La firma no contiene SignedInfo")

	signature_value = signature.findtext(f"{DS}SignatureValue")
	if not signature_value:
		raise ValueError("La firma no contiene SignatureValue")

	signature_value = base64.b64decode(signature_value.strip())
	key_type, hash_algorithm = _signature_algorithm(signed_info)
	canonical_signed_info = _canonicalize(signed_info, C14N_EXCLUSIVE)
	_verify_signature_value(
		cert.public_key(), signature_value, canonical_signed_info, key_type, hash_algorithm
	)
	_verify_reference(root, signature, signed_info)


def verify_signature(root):
	"""Verifies an enveloped XMLDSig signature.

	Returns a :class:`VerificationResult`. The first attempt uses signxml and
	the declared canonicalization; the fallback verifies DGII's exclusive-C14N
	SignedInfo and separately checks the Reference digest.
	"""
	try:
		cert = _load_certificate(root)
	except Exception as exc:
		return VerificationResult(False, None, f"{type(exc).__name__}: {exc}")

	try:
		XMLVerifier().verify(root, x509_cert=_certificate_pem(cert))
		return VerificationResult(True, "signxml", None)
	except Exception as exc:
		signxml_error = f"{type(exc).__name__}: {exc}"

	try:
		_verify_with_exclusive_c14n(root, cert)
		return VerificationResult(True, "c14n-exclusive", None)
	except Exception as exc:
		fallback_error = f"{type(exc).__name__}: {exc}"

	return VerificationResult(
		False,
		None,
		f"signxml: {signxml_error}; fallback: {fallback_error}",
	)
