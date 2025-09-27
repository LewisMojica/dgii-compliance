import frappe

def main(doc,method):
	"""
	Generate or assign NCF (Número de Comprobante Fiscal) for Dominican Republic fiscal invoices.

	- New invoices (3 dashes): generates sequential NCF from enabled sequences
	- Cancelled invoices (4 dashes): copies NCF from original invoice
	note: doc may be a POS Invoice or a Sales Invoice

	Args:
	doc: Sales Invoice document to process
	"""
	if doc.is_pos and doc.doctype == 'Sales Invoice': #si la factura viene del POS no aplica para dgii, hay que aplicar los ncf a las factura pos individuales
		doc.custom_factura_de_valor_fiscal = 0 
		#Sales Invoices generated at POS Closing seem to inherite the value of fields, so ncf was getting fille
		#when it shouldn't, this make sures is empty as this could cause confusion fo accounting
		doc.custom_ncf = None
		doc.custom_ncf_vencimiento = None
		return

	if doc.name.count('-') == 4: #si la factura es amendada de una factura cancelada reutilizar el ncf anterior
		doc.custom_ncf = frappe.db.get_value('Sales Invoice', doc.name[:19],'custom_ncf') #toma el ncf de la factura cancelada original
		return
	
	if doc.custom_factura_de_valor_fiscal:
		customer_type = frappe.get_value('Customer', doc.customer, 'customer_type')
		ncf_type = get_ncf_type(frappe.get_doc('Customer',doc.customer))
		ncf_seq_list = frappe.get_all('Secuencia NCF', filters = {'disabled': 0, 'ncf_type': ncf_type})
		
		#error check
		if len(ncf_seq_list) == 0:
			frappe.throw('No existen secuencias de ncf habilitadas. Contacte administrador del sistema')
		if frappe.db.get_value('Secuencia NCF', ncf_seq_list[0], 'end') < frappe.db.get_value('Secuencia NCF', ncf_seq_list[0], 'next_ncf'): #si el siguiente ncf no supera el ncf final se escribe un nuevo ncf en la factura
			frappe.throw('next_ncf es mayor que end_ncf. Contacte administrador del sistema')
		if frappe.db.get_value('Secuencia NCF', ncf_seq_list[0], 'start') > frappe.db.get_value('Secuencia NCF', ncf_seq_list[0], 'next_ncf'): #si el siguiente ncf no supera el ncf final se escribe un nuevo ncf en la factura
			frappe.throw('next_ncf es menor que start_ncf. Contacte administrador del sistema')
		
		ncf_data = frappe.db.get_value('Secuencia NCF', ncf_seq_list[0], ['end', 'next_ncf', 'start'], as_dict=True)
		end_ncf = ncf_data.end
		next_ncf = ncf_data.next_ncf
		start_ncf = ncf_data.start
		
		#avisar si se estan agotando los ncf
		no_ncf = end_ncf-start_ncf
		if len(ncf_seq_list) < 2 and (next_ncf/no_ncf > 0.8 or end_ncf-2 < next_ncf):
			frappe.msgprint(msg='Se están agotando los NCF',title='*Atención requerida')
			
		
		if end_ncf < 1 or start_ncf < 1 or next_ncf < 1:
			frappe.throw('uno o más valores del secuencia de ncf fuera de rango. Contacte administrador del sistema')
		
		
		
		
		#set new ncf
		if ncf_type == 'B01':
			formated_ncf = 100000000
		elif ncf_type == 'B02':
			formated_ncf = 200000000
		elif ncf_type == 'B14':
			formated_ncf = 1400000000
		else:
			frappe.throw(f'NCF {ncf_type} no es válido')
			
		formated_ncf += next_ncf
		formated_ncf = str(formated_ncf).zfill(10)
		doc.custom_ncf= f'B{formated_ncf}'
		doc.custom_ncf_vencimiento = frappe.db.get_value('Secuencia NCF', ncf_seq_list[0], 'expiration_date')
		
		if end_ncf == next_ncf: # si se llego al final de la secuencia se deshabilita secuencia de ncf
			frappe.db.set_value('Secuencia NCF', ncf_seq_list[0], {'disabled': 1, 'next_ncf': -1})
		else:
			frappe.db.set_value('Secuencia NCF', ncf_seq_list[0], 'next_ncf', next_ncf+1)
	

def get_ncf_type(customer):
	"""returns the ncf type based on customer type and Customer group"""
	if customer.customer_group == 'B14':
		return 'B14'
	if customer.customer_type == 'Company':
		return 'B01'
	if customer.customer_type == 'Individual':
		return 'B02'
	
