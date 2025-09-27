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
			'parent_customer_group': 'Regímenes Especiales'
		})

	return len(group) == 1

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
	reg_es = frappe.get_doc({
		'doctype': 'Customer Group',
		'name': 'Regímenes Especiales',
		'parent_customer_group': root_group['name'],
		'is_group': 1,
		}
	).save()

	b14 = frappe.get_doc({
		'doctype': 'Customer Group',
		'name': 'B14',
		'parent_customer_group': reg_es.name,
		'is_group': 0,
		}
	).save()

	print(f'[dgii_compliance]-> created {reg_es.name} and {b14.name}')	
	
