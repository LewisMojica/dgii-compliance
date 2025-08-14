from dgii_compliance.utils import get_company_data_by_rnc

def main(doc, method):
	if !doc.tax_id:
		return

	tax_data = get_company_data_by_rnc(doc.tax_id)
		
	if tax_data['Fail']:
		print(f'tax data not found for RNC {doc.tax_id}')
		return
	print('data found')	
	doc.customer_name = tax_data['data']['razon_social']
