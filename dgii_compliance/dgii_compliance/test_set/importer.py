"""Turns parsed DGII test cases into draft Sales Invoices with full e-CF data."""

import frappe
from frappe.utils import today

from dgii_compliance.dgii_compliance.test_set import mapping, parser

DEFAULT_ITEM_GROUP = "Services"
DEFAULT_UOM = "Nos"
DEFAULT_TERRITORY = "Rest Of The World"
COMPANY_CUSTOMER_GROUP = "Commercial"
INDIVIDUAL_CUSTOMER_GROUP = "Individual"
CONSUMER_FINAL = "Consumidor Final"

# IndicadorFacturacion code -> ITBIS rate (%)
ITBIS_RATE_BY_INDICADOR = {"1": 18.0, "2": 16.0}
_ITT_CACHE = {}



def get_company(rnc):
	"""Returns the emitter company whose tax id matches ``rnc``."""
	company = frappe.db.get_value("Company", {"tax_id": rnc}, "name")
	if not company:
		frappe.throw(f"No existe una compañía con RNC {rnc}.")
	return company


def get_or_create_customer(case):
	"""Resolves (or creates) the buyer. E43 has no buyer -> Consumidor Final."""
	header = case["header"]
	rnc = parser._clean(header.get("RNCComprador"))
	name = parser._clean(header.get("RazonSocialComprador"))
	if not rnc and not name:
		return _ensure_consumer_final()

	if rnc:
		existing = frappe.db.get_value("Customer", {"custom_rnc": rnc}, "name")
		if existing:
			return existing

	name = name or f"RNC {rnc}"
	existing = frappe.db.get_value("Customer", {"customer_name": name}, "name")
	if existing:
		return existing

	customer = frappe.new_doc("Customer")
	customer.customer_name = name
	customer.customer_type = "Company" if rnc and len(rnc) in (9, 11) else "Individual"
	customer.customer_group = (
		COMPANY_CUSTOMER_GROUP if customer.customer_type == "Company" else INDIVIDUAL_CUSTOMER_GROUP
	)
	customer.territory = DEFAULT_TERRITORY
	if rnc:
		customer.custom_rnc = rnc
		customer.tax_id = rnc
	customer.insert(ignore_permissions=True)
	return customer.name


def _ensure_consumer_final():
	existing = frappe.db.get_value("Customer", {"customer_name": CONSUMER_FINAL}, "name")
	if existing:
		return existing
	customer = frappe.new_doc("Customer")
	customer.customer_name = CONSUMER_FINAL
	customer.customer_type = "Individual"
	customer.customer_group = INDIVIDUAL_CUSTOMER_GROUP
	customer.territory = DEFAULT_TERRITORY
	customer.insert(ignore_permissions=True)
	return customer.name


def get_or_create_item(nombre_item):
	"""Resolves (or creates) a non-stock Item for the given line description."""
	name = parser._clean(nombre_item) or "DGII Test Item"
	item_code = frappe.scrub(name)[:120] or "dgii_test_item"
	existing = frappe.db.get_value("Item", {"item_code": item_code}, "name")
	if existing:
		return existing

	item = frappe.new_doc("Item")
	item.item_code = item_code
	item.item_name = name
	item.item_group = DEFAULT_ITEM_GROUP
	item.stock_uom = DEFAULT_UOM
	item.is_stock_item = 0
	item.description = name
	item.insert(ignore_permissions=True)
	return item.name


def get_itbis_account(company):
	account = frappe.db.get_value(
		"Account", {"company": company, "is_group": 0, "name": ["like", "%ITBIS%"]}, "name"
	)
	if not account:
		frappe.throw(f"No existe una cuenta ITBIS para la compañía {company}.")
	return account


def get_cost_center(company):
	return frappe.db.get_value("Company", company, "cost_center") or frappe.db.get_value(
		"Cost Center", {"company": company, "is_group": 0}, "name"
	)


def get_item_tax_template(company, rate):
	"""Returns (creating if needed) an Item Tax Template for ``rate``% ITBIS."""
	key = (company, rate)
	if key in _ITT_CACHE:
		return _ITT_CACHE[key]
	title = f"ITBIS {int(rate)} - {frappe.db.get_value('Company', company, 'abbr') or company}"
	name = frappe.db.get_value("Item Tax Template", {"title": title, "company": company}, "name")
	if not name:
		template = frappe.new_doc("Item Tax Template")
		template.title = title
		template.company = company
		template.append("taxes", {"tax_type": get_itbis_account(company), "tax_rate": rate})
		template.insert(ignore_permissions=True)
		name = template.name
	_ITT_CACHE[key] = name
	return name



def _line_numbers(case):
	numbers = set()
	for base in mapping.ITEM_SCALARS:
		numbers.update(case["indexed"].get(base, {}))
	for group in case["sub"].values():
		numbers.update(group)
	return sorted(numbers)


def _apply_header(doc, case):
	for column, (fieldname, kind) in mapping.HEADER_MAP.items():
		if fieldname == "skip":
			continue
		value = case["header"].get(column)
		if value is None:
			continue
		doc.set(fieldname, mapping.convert(value, kind))


def _apply_phones(doc, case):
	phones = case["indexed"].get(mapping.PHONE_BASE, {})
	for idx in (1, 2, 3):
		value = phones.get(idx)
		if value is not None:
			doc.set(f"custom_ecf_telefono_emisor_{idx}", parser._clean(value))


def _apply_payments(doc, case):
	formas = case["indexed"].get("FormaPago", {})
	montos = case["indexed"].get("MontoPago", {})
	for idx in sorted(set(formas) | set(montos)):
		doc.append(
			"custom_ecf_formas_pago",
			{
				"forma_pago": parser._clean(formas.get(idx)) or "1",
				"monto_pago": parser.to_float(montos.get(idx)) or 0,
			},
		)


def _item_scalar(case, base, line):
	return case["indexed"].get(base, {}).get(line)


def _apply_items(doc, case, company):
	for line in _line_numbers(case):
		nombre = _item_scalar(case, "NombreItem", line)
		qty = parser.to_float(_item_scalar(case, "CantidadItem", line)) or 0
		amount = parser.to_float(_item_scalar(case, "MontoItem", line))
		# Align the ERPNext line amount with the e-CF MontoItem (line total net of
		# the discounts/recargos that ERPNext does not model here).
		rate = (amount / qty) if qty else (amount or 0)
		item = {
			"item_code": get_or_create_item(nombre),
			"item_name": parser._clean(nombre),
			"description": parser._clean(_item_scalar(case, "DescripcionItem", line)) or nombre,
			"qty": qty,
			"rate": rate,
		}
		indicador = str(parser._clean(_item_scalar(case, "IndicadorFacturacion", line)))
		if indicador in ITBIS_RATE_BY_INDICADOR:
			item["item_tax_template"] = get_item_tax_template(
				company, ITBIS_RATE_BY_INDICADOR[indicador]
			)
		doc.append("items", item)

		detalle = {"numero_linea": line}
		for base, (fieldname, kind) in mapping.ITEM_SCALARS.items():
			value = _item_scalar(case, base, line)
			if value is not None:
				detalle[fieldname] = mapping.convert(value, kind)
		doc.append("custom_ecf_detalle_items", detalle)


def _apply_taxes(doc, case, company):
	"""Adds an ITBIS tax row so the invoice is submittable and accounting-correct.

	Per-line rates come from each item's Item Tax Template; the row rate 0 is the
	fallback for untaxed (exento / 0%) lines.
	"""
	indicators = {
		str(parser._clean(_item_scalar(case, "IndicadorFacturacion", line)))
		for line in _line_numbers(case)
	}
	if not (indicators & set(ITBIS_RATE_BY_INDICADOR)):
		return
	gravado = str(parser._clean(case["header"].get("IndicadorMontoGravado")))
	doc.append(
		"taxes",
		{
			"charge_type": "On Net Total",
			"account_head": get_itbis_account(company),
			"cost_center": get_cost_center(company),
			"description": "ITBIS",
			"rate": 0,
			"included_in_print_rate": 1 if gravado == "1" else 0,
		},
	)



def _apply_child_group(doc, case, group, child_field):
	bases = list(group)
	for line, subs in _rows_by_line(case, bases).items():
		for sub in sorted(subs):
			row = {"numero_linea": line}
			for base, fieldname in group.items():
				value = case["sub"].get(base, {}).get(line, {}).get(sub)
				if value is not None:
					row[fieldname] = parser.to_float(value) if fieldname in _FLOAT_CHILD else parser._clean(value)
			doc.append(child_field, row)


_FLOAT_CHILD = {
	"sub_descuento_porcentaje",
	"monto_sub_descuento",
	"sub_recargo_porcentaje",
	"monto_sub_recargo",
}


def _rows_by_line(case, bases):
	rows = {}
	for base in bases:
		for line, subs in case["sub"].get(base, {}).items():
			rows.setdefault(line, set()).update(subs)
	return rows


def build_invoice(case, company):
	"""Builds (but does not insert) a Sales Invoice for a parsed case."""
	doc = frappe.new_doc("Sales Invoice")
	doc.company = company
	doc.customer = get_or_create_customer(case)
	doc.posting_date = today()
	doc.set("taxes", [])
	# Mark as fiscal + certification: on submit `add_ncf_data` generates the
	# e-CF from the workbook's e-NCF without consuming a sequence.
	doc.custom_factura_de_valor_fiscal = 1
	doc.custom_ecf_certification = 1

	_apply_header(doc, case)
	_apply_phones(doc, case)
	_apply_payments(doc, case)
	_apply_items(doc, case, company)
	_apply_taxes(doc, case, company)
	_apply_child_group(doc, case, mapping.CODIGO_GROUP, "custom_ecf_codigos_item")
	_apply_child_group(doc, case, mapping.SUBDESCUENTO_GROUP, "custom_ecf_sub_descuentos")
	_apply_child_group(doc, case, mapping.SUBRECARGO_GROUP, "custom_ecf_sub_recargos")
	return doc


def reset_case(encf):
	"""Deletes any invoice/e-CF previously created for ``encf``."""
	names = frappe.get_all("Sales Invoice", filters={"custom_ncf": encf}, pluck="name")
	if names:
		frappe.db.delete("eCF", {"ref_doctype": "Sales Invoice", "ref_name": ["in", names]})
		for name in names:
			doc = frappe.get_doc("Sales Invoice", name)
			if doc.docstatus == 1:
				doc.cancel()
			frappe.delete_doc("Sales Invoice", name, force=True, ignore_permissions=True)
	return names


def import_case(case, company, reset=True):
	"""Creates the draft invoice for a single case and returns its name."""
	if reset:
		reset_case(case["encf"])
	doc = build_invoice(case, company)
	doc.insert(ignore_permissions=True)
	return doc.name


def import_cases(cases, company=None, reset=True):
	"""Creates draft invoices for every case. Returns a per-case report."""
	if not company:
		company = get_company(cases[0]["header"].get("RNCEmisor"))
	report = []
	for case in cases:
		try:
			name = import_case(case, company, reset=reset)
			frappe.db.commit()
			report.append({"encf": case["encf"], "tipo": case["tipo"], "invoice": name, "error": None})
		except Exception as exc:
			frappe.db.rollback()
			report.append({"encf": case["encf"], "tipo": case["tipo"], "invoice": None, "error": str(exc)})
	return report
