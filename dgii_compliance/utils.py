import os
import csv
import requests
import zipfile
import frappe
from frappe import _

# File management
def get_dgii_file_path():
    """Get the path for DGII RNC CSV file"""
    dgii_dir = frappe.get_site_path("private", "files", "dgii_compliance")
    frappe.create_folder(dgii_dir)
    return os.path.join(dgii_dir, "dgii_rnc_data.csv")

def get_dgii_zip_path():
    """Get the path for DGII RNC ZIP file"""
    dgii_dir = frappe.get_site_path("private", "files", "dgii_compliance")
    frappe.create_folder(dgii_dir)
    return os.path.join(dgii_dir, "RNC_CONTRIBUYENTES.ZIP")

# Scheduled job
def sync_dgii_rnc_data():
    """Daily job to sync DGII RNC data"""
    frappe.logger().info("Starting DGII RNC data sync")
    
    try:
        success = download_and_extract_dgii_data()
        if success:
            frappe.logger().info("DGII RNC data sync completed successfully")
        else:
            frappe.logger().error("DGII RNC data sync failed")
    except Exception as e:
        frappe.log_error(f"DGII RNC sync error: {str(e)}", "DGII Sync")

def download_and_extract_dgii_data():
    """Download and extract DGII RNC ZIP file"""
    zip_url = "https://dgii.gov.do/app/WebApps/Consultas/RNC/RNC_CONTRIBUYENTES.zip"
    zip_path = get_dgii_zip_path()
    csv_path = get_dgii_file_path()
    
    # Add headers to look like a real browser
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'es-ES,es;q=0.8,en-US;q=0.5,en;q=0.3',
        'Accept-Encoding': 'gzip, deflate, br',
        'Referer': 'https://dgii.gov.do/',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
    }
    
    try:
        # Download ZIP file with headers
        response = requests.get(zip_url, headers=headers, timeout=30)
        response.raise_for_status()
        
        with open(zip_path, 'wb') as f:
            f.write(response.content)
        
        # Extract CSV from ZIP
        with zipfile.ZipFile(zip_path, 'r') as zip_file:
            # List files in ZIP to find CSV
            file_list = zip_file.namelist()
            csv_file = None
            
            # Find the CSV file (might have different name)
            for file_name in file_list:
                if file_name.lower().endswith('.csv'):
                    csv_file = file_name
                    break
            
            if csv_file:
                # Extract CSV to our target location
                with zip_file.open(csv_file) as source, open(csv_path, 'wb') as target:
                    target.write(source.read())
            else:
                raise Exception("No CSV file found in ZIP")
        
        # Clean up ZIP file (optional)
        os.remove(zip_path)
        
        return True
        
    except Exception as e:
        frappe.log_error(f"Failed to download/extract DGII data: {str(e)}", "DGII Download")
        return False

def clean_csv_value(value):
    """Clean and normalize CSV values"""
    if not value:
        return ""
    return str(value).replace('"', '').strip()

def normalize_rnc(rnc):
    """Normalize RNC for comparison"""
    if not rnc:
        return ""
    return str(rnc).replace("-", "").replace(" ", "").replace('"', '').strip()

@frappe.whitelist()
def get_company_data_by_rnc(rnc):
    """API method to get company data by RNC"""
    csv_path = get_dgii_file_path()
    
    # Check if CSV file exists
    if not os.path.exists(csv_path):
        return {
            "success": False,
            "message": "Datos de RNC no disponibles. Intente más tarde.",
            "data": None
        }
    
    # Clean and validate input RNC
    clean_rnc = normalize_rnc(rnc)
    if not clean_rnc:
        return {
            "success": False,
            "message": "RNC inválido",
            "data": None
        }
    
    try:
        with open(csv_path, 'r', encoding='utf-8', errors='ignore') as file:
            # Try different delimiters if comma fails
            sample = file.read(1024)
            file.seek(0)
            
            delimiter = ','
            if sample.count(';') > sample.count(','):
                delimiter = ';'
            
            csv_reader = csv.DictReader(file, delimiter=delimiter)
            
            for line_num, row in enumerate(csv_reader, start=2):
                try:
                    # Skip malformed rows
                    if not row or 'RNC' not in row:
                        continue
                    
                    # Clean and compare RNC
                    csv_rnc = normalize_rnc(row.get('RNC', ''))
                    if not csv_rnc:
                        continue
                    
                    if csv_rnc == clean_rnc:
                        # Clean all data fields
                        return {
                            "success": True,
                            "message": "RNC encontrado",
                            "data": {
                                "rnc": clean_csv_value(row.get('RNC', '')),
                                "razon_social": clean_csv_value(row.get('RAZN SOCIAL', '')),
                                "actividad_economica": clean_csv_value(row.get('ACTIVIDAD ECONMICA', '')),
                                "fecha_inicio": clean_csv_value(row.get('FECHA DE INICIO OPERACIONES', '')),
                                "estado": clean_csv_value(row.get('ESTADO', '')),
                                "regimen_pago": clean_csv_value(row.get('RGIMEN DE PAGO', ''))
                            }
                        }
                        
                except Exception as row_error:
                    # Log problematic row but continue processing
                    frappe.log_error(f"Error processing CSV row {line_num}: {str(row_error)}", "DGII CSV Row Error")
                    continue
        
        # RNC not found
        return {
            "success": False,
            "message": "RNC no encontrado en la base de datos de DGII",
            "data": None
        }
        
    except UnicodeDecodeError:
        # Try different encoding
        try:
            return get_company_data_by_rnc_latin1(rnc)
        except Exception:
            pass
            
    except Exception as e:
        frappe.log_error(f"Error reading DGII CSV: {str(e)}", "DGII CSV Read")
        return {
            "success": False,
            "message": "Error al consultar datos de RNC",
            "data": None
        }

def get_company_data_by_rnc_latin1(rnc):
    """Fallback with Latin-1 encoding"""
    csv_path = get_dgii_file_path()
    clean_rnc = normalize_rnc(rnc)
    
    with open(csv_path, 'r', encoding='latin-1', errors='ignore') as file:
        csv_reader = csv.DictReader(file)
        for row in csv_reader:
            if normalize_rnc(row.get('RNC', '')) == clean_rnc:
                return {
                    "success": True,
                    "message": "RNC encontrado",
                    "data": {
                        "rnc": clean_csv_value(row.get('RNC', '')),
                        "razon_social": clean_csv_value(row.get('RAZN SOCIAL', '')),
                        "actividad_economica": clean_csv_value(row.get('ACTIVIDAD ECONMICA', '')),
                        "fecha_inicio": clean_csv_value(row.get('FECHA DE INICIO OPERACIONES', '')),
                        "estado": clean_csv_value(row.get('ESTADO', '')),
                        "regimen_pago": clean_csv_value(row.get('RGIMEN DE PAGO', ''))
                    }
                }
    
    return {"success": False, "message": "RNC no encontrado", "data": None}
