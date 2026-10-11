"""E47 - Comprobante para Pagos al Exterior Electrónico."""

from lxml import etree

from . import common
from .common import (
	NSMAP,
	append_detalles_items,
	compute_dgii_tax_totals,
	is_certification,
	item_rows,
	present_indicators,
)

# E47 has no IndicadorEnvioDiferido / IndicadorMontoGravado / TipoIngresos.
ID_DOC_TAGS = [
	"TipoeCF",
	"eNCF",
	"FechaVencimientoSecuencia",
	"TipoPago",
	"FechaLimitePago",
	"TerminoPago",
	"TablaFormasPago",
	"TipoCuentaPago",
	"NumeroCuentaPago",
	"BancoPago",
	"FechaDesde",
	"FechaHasta",
	"TotalPaginas",
]


def build(doc):
	cert = is_certification(doc)
	rows = item_rows(doc)
	tax_totals = common.EMPTY_TOTALS if cert else compute_dgii_tax_totals(doc, forced_indicador="4")
	present = present_indicators(rows, tax_totals)

	ecf_root = etree.Element("ECF", nsmap=NSMAP)
	encabezado = etree.SubElement(ecf_root, "Encabezado")
	common.add(encabezado, "Version", "1.0")

	common.emit_id_doc(encabezado, doc, "E47", ID_DOC_TAGS, tax_totals)
	common.emit_emisor(encabezado, doc)
	common.emit_comprador(encabezado, doc, "", require_rnc=False)
	common.emit_totales(encabezado, doc, present, tax_totals, cert)
	common.emit_otra_moneda(encabezado, doc)

	if cert:
		common.emit_items(ecf_root, doc, rows, tax_totals, cert)
	else:
		append_detalles_items(ecf_root, doc, tax_totals)
	common.emit_referencia(ecf_root, doc)
	common.append_firma(ecf_root)
	return ecf_root
