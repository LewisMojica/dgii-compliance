# Copyright (c) 2026, Lewis Mojica and Contributors
# See license.txt

import unittest

from lxml import etree

from dgii_compliance.dgii_compliance import ri

DS = "http://www.w3.org/2000/09/xmldsig#"


def _ecf(tipo, monto, signature="EL/Dhc123"):
	return etree.fromstring(
		f"""<ECF xmlns:ds="{DS}">
		<Encabezado>
			<IdDoc><TipoeCF>{tipo}</TipoeCF><eNCF>E{tipo}0000004001</eNCF></IdDoc>
			<Emisor><RNCEmisor>133424959</RNCEmisor><FechaEmision>13-10-2026</FechaEmision></Emisor>
			<Comprador><RNCComprador>131880681</RNCComprador></Comprador>
			<Totales><MontoTotal>{monto}</MontoTotal></Totales>
		</Encabezado>
		<FechaHoraFirma>13-10-2026 22:30:36</FechaHoraFirma>
		<ds:Signature><ds:SignatureValue>{signature}</ds:SignatureValue></ds:Signature>
		</ECF>""".encode()
	)


class TestRI(unittest.TestCase):
	def test_normal_qr_url(self):
		url = ri._qr_url(_ecf("31", "1505.00"), "certecf")
		self.assertTrue(url.startswith("https://ecf.dgii.gov.do/certecf/consultatimbre?"))
		self.assertIn("rncemisor=133424959", url)
		self.assertIn("rnccomprador=131880681", url)
		self.assertIn("encf=E310000004001", url)
		self.assertIn("fechafirma=13-10-2026%2022:30:36", url)
		self.assertIn("codigoseguridad=EL%2FDhc", url)

	def test_small_consumption_qr_url(self):
		url = ri._qr_url(_ecf("32", "40120.00"), "certecf")
		self.assertTrue(url.startswith("https://fc.dgii.gov.do/certecf/consultatimbrefc?"))
		self.assertIn("encf=E320000004001", url)
		self.assertIn("montototal=40120.00", url)
		self.assertNotIn("rnccomprador", url)
		self.assertNotIn("fechafirma", url)

	def test_large_consumption_uses_ecf_qr(self):
		url = ri._qr_url(_ecf("32", "413785.30"), "certecf")
		self.assertIn("/consultatimbre?", url)

	def test_amount_formatting(self):
		self.assertEqual(ri._amount("1505"), "1,505.00")
		self.assertEqual(ri._amount(None), None)
		self.assertEqual(ri._amount("0.00"), "0.00")

	def test_uom_words(self):
		self.assertEqual(ri._uom("23"), "Libra")
		self.assertEqual(ri._uom("43"), "Unidad")
		self.assertEqual(ri._uom("999"), "999")
		self.assertIsNone(ri._uom(None))

	def test_municipio_provincia_words(self):
		self.assertEqual(ri._municipio("320300"), "Santo Domingo Norte")
		self.assertEqual(ri._provincia("320000"), "Santo Domingo")
		self.assertEqual(ri._municipio("999999"), "999999")
