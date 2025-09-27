import frappe

def after_migrate():
	if _customer_groups_exists():
		return
	else:
		print('[dgii_compliance]->Creating customer groups') 
		_create_customer_groups()	


def _customer_groups_exists():
	group = frappe.db.get_all('Customer Group', 
		filters={
			'name': 'B14',
		})
	
	group += frappe.db.get_all('Customer Group', 
		filters={
			'name': 'Regímenes Especiales',
		})

	le = len(group)
	if le > 0 and le != 2:
		print('[dgii_compliance]-> WARNNING! ABORTED CUSTOMER GROUP CREATION')	
	return len(group) != 0

def _create_customer_groups():
	#query root group
	root_group = frappe.db.get_all('Customer Group',
		filters={
			'parent_customer_group': '',
			'is_group': 1,
		}
	)[0]
	print(f'root group: {root_group}')

	#create new custumer groups
	reg_es = frappe.new_doc('Customer Group')
	reg_es.parent_customer_group = root_group['name']
	reg_es.is_group = 1
	reg_es.customer_group_name = 'Regímenes Especiales'
	reg_es.save()	

	b14 = frappe.new_doc('Customer Group')
	b14.parent_customer_group = 'Regímenes Especiales'
	b14.is_group = 0
	b14.customer_group_name = 'B14'
	b14.save()	

	print(f'[dgii_compliance]-> created {reg_es.name} and {b14.name}')

