# Copyright (c) 2025, Lewis Mojica and Contributors
# See license.txt

from unittest.mock import MagicMock, patch

from frappe.tests.utils import FrappeTestCase

from dgii_compliance.dgii_compliance import dgii_client


def make_response(status_code=200, json_data=None, headers=None, text="", content=None):
	response = MagicMock()
	response.status_code = status_code
	response.headers = headers or {"Content-Type": "application/json"}
	response.text = text
	response.content = content if content is not None else text.encode()
	if json_data is not None:
		response.json.return_value = json_data
	response.raise_for_status.return_value = None
	return response


class TestDGIIClient(FrappeTestCase):
	def test_map_estado_to_status(self):
		self.assertEqual(dgii_client.map_estado_to_status("Aceptado"), "accepted")
		self.assertEqual(dgii_client.map_estado_to_status("Aceptado Condicional"), "accepted_conditional")
		self.assertEqual(dgii_client.map_estado_to_status("Rechazado"), "rejected")
		self.assertEqual(dgii_client.map_estado_to_status("En Proceso"), "sent")
		self.assertEqual(dgii_client.map_estado_to_status(None), "sent")

	def test_send_ecf_uses_rnc_encf_filename_and_bearer(self):
		response = make_response(json_data={"trackId": "abc", "estado": "Aceptado", "mensajes": []})
		with patch.object(dgii_client.requests, "post", return_value=response) as mock_post:
			result = dgii_client.send_ecf("<ECF/>", "132758919", "E320000000018", token="tok")

		_, kwargs = mock_post.call_args
		self.assertEqual(kwargs["files"]["xml"][0], "132758919E320000000018.xml")
		self.assertEqual(kwargs["headers"]["Authorization"], "bearer tok")
		self.assertEqual(result["trackid"], "abc")

	def test_send_ecf_retries_once_on_401(self):
		unauthorized = make_response(status_code=401, json_data={})
		ok = make_response(json_data={"trackId": "t1", "estado": "Aceptado"})
		with patch.object(dgii_client.requests, "post", side_effect=[unauthorized, ok]) as mock_post, \
				patch.object(dgii_client, "_clear_token") as mock_clear, \
				patch.object(dgii_client, "get_token", return_value="fresh"):
			result = dgii_client.send_ecf("<ECF/>", "1", "E32", token="stale")

		self.assertEqual(mock_post.call_count, 2)
		mock_clear.assert_called_once_with("1")
		self.assertEqual(result["trackid"], "t1")

	def test_get_token_reuses_cache(self):
		with patch.object(dgii_client.frappe.cache, "get_value", return_value="cached"), \
				patch.object(dgii_client, "_request_new_token") as mock_request:
			self.assertEqual(dgii_client.get_token("1"), "cached")
		mock_request.assert_not_called()

	def test_get_token_fetches_and_caches(self):
		with patch.object(dgii_client.frappe.cache, "get_value", return_value=None), \
				patch.object(dgii_client.frappe.cache, "set_value") as mock_set, \
				patch.object(dgii_client, "_request_new_token", return_value=("fresh", None)):
			self.assertEqual(dgii_client.get_token("1"), "fresh")
		self.assertEqual(mock_set.call_args[0][1], "fresh")

	def test_parse_response_from_xml(self):
		xml = b"<RespuestaRecepcion><trackId>xyz</trackId><estado>Aceptado</estado></RespuestaRecepcion>"
		response = make_response(
			status_code=200,
			headers={"Content-Type": "text/xml"},
			text=xml.decode(),
			content=xml,
		)
		data = dgii_client._parse_response(response)
		self.assertEqual(data["trackid"], "xyz")
		self.assertEqual(data["estado"], "Aceptado")

	def test_raise_for_status_includes_dgii_body(self):
		response = make_response(
			status_code=400,
			headers={"Content-Type": "text/plain"},
			text="Tipo de certificado no admitido",
		)
		with self.assertRaises(Exception) as ctx:
			dgii_client._raise_for_status(response)
		self.assertIn("Tipo de certificado no admitido", str(ctx.exception))

	def test_query_estado_uses_consultaresultado_endpoint(self):
		response = make_response(json_data={"trackId": "t", "estado": "Aceptado", "fechaRecepcion": "2026-10-10T15:24:53Z"})
		with patch.object(dgii_client.requests, "get", return_value=response) as mock_get, \
				patch.object(dgii_client, "get_token", return_value="tok"):
			result = dgii_client.query_estado("t1", "1")

		url = mock_get.call_args[0][0]
		self.assertIn("/consultaresultado/api/consultas/estado", url)
		self.assertEqual(mock_get.call_args[1]["params"], {"trackid": "t1"})
		self.assertEqual(result["estado"], "Aceptado")
		self.assertEqual(result["fecharecepcion"], "2026-10-10T15:24:53Z")

	def test_collect_mensaje_combines_singular_and_plural(self):
		self.assertEqual(dgii_client._collect_mensaje({"error": "E1", "mensaje": "M1"}), "E1\nM1")
		self.assertEqual(
			dgii_client._collect_mensaje({"mensajes": [{"codigo": 1, "valor": "V"}]}),
			"1: V",
		)
		self.assertIsNone(dgii_client._collect_mensaje({}))
		# success entries carry a code but no text
		self.assertIsNone(dgii_client._collect_mensaje({"mensajes": [{"codigo": 0, "valor": ""}]}))

	def test_query_rfce_estado_uses_consultarfce(self):
		response = make_response(json_data={"estado": "Aceptado", "codigo": "1"})
		with patch.object(dgii_client.requests, "get", return_value=response) as mock_get, \
				patch.object(dgii_client, "get_token", return_value="tok"):
			result = dgii_client.query_rfce_estado("101010101", "E320000000001", "ABC123")

		self.assertIn("/consultarfce/api/Consultas/Consulta", mock_get.call_args[0][0])
		self.assertEqual(
			mock_get.call_args[1]["params"],
			{"RNC_Emisor": "101010101", "ENCF": "E320000000001", "Cod_Seguridad_eCF": "ABC123"},
		)
		self.assertEqual(result["estado"], "Aceptado")

	def test_send_rfce_uses_fc_endpoint(self):
		response = make_response(json_data={"codigo": 1, "estado": "Aceptado", "mensajes": []})
		with patch.object(dgii_client.requests, "post", return_value=response) as mock_post:
			result = dgii_client.send_rfce("<RFCE/>", "101010101", "E320000000001", token="tok")

		url = mock_post.call_args[0][0]
		self.assertIn("fc.dgii.gov.do", url)
		self.assertIn("/recepcionfc/api/recepcion/ecf", url)
		self.assertEqual(mock_post.call_args[1]["files"]["xml"][0], "101010101E320000000001.xml")
		self.assertEqual(result["estado"], "Aceptado")
