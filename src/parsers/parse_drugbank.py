"""
DrugBank Parser for CardioKB
============================
MANUAL STEP REQUIRED:
1. Register at https://go.drugbank.com/releases (free academic account)
2. Download "DrugBank Complete Database" XML: drugbank_all_full_database.xml.zip
3. Place the extracted XML at: ./data/raw/drugbank/full_database.xml
4. Run this script to parse and load into Memgraph

This parser will create:
- Drug nodes (commonName, drugBankId, description, indication, mechanism)
- drugBindsGene edges (Drug -> Gene)
"""
import xml.etree.ElementTree as ET
import sys, csv
sys.path.insert(0, "./src/parsers")
from utils import get_driver

NS = "{http://www.drugbank.ca}"

def parse_drugbank(xml_path):
    drugs = []
    drug_gene_edges = []
    
    tree = ET.parse(xml_path)
    root = tree.getroot()
    
    for drug in root.findall(f"{NS}drug"):
        db_id_elem = drug.find(f"{NS}drugbank-id[@primary='true']")
        name_elem = drug.find(f"{NS}name")
        desc_elem = drug.find(f"{NS}description")
        indication_elem = drug.find(f"{NS}indication")
        mechanism_elem = drug.find(f"{NS}mechanism-of-action")
        
        if db_id_elem is None or name_elem is None:
            continue
        
        db_id = db_id_elem.text.strip()
        name = name_elem.text.strip()
        description = desc_elem.text.strip() if desc_elem is not None and desc_elem.text else ""
        indication = indication_elem.text.strip() if indication_elem is not None and indication_elem.text else ""
        mechanism = mechanism_elem.text.strip() if mechanism_elem is not None and mechanism_elem.text else ""
        
        drugs.append({
            "commonName": name,
            "drugBankId": db_id,
            "description": description[:500],
            "indication": indication[:500],
            "mechanism": mechanism[:500],
        })
        
        # Parse drug-target (gene) interactions
        for target in drug.findall(f".//{NS}target"):
            polypeptide = target.find(f".//{NS}polypeptide")
            if polypeptide is None:
                continue
            gene_name_elem = polypeptide.find(f"{NS}gene-name")
            if gene_name_elem is not None and gene_name_elem.text:
                drug_gene_edges.append({
                    "drugName": name,
                    "gene": gene_name_elem.text.strip()
                })
    
    return drugs, drug_gene_edges

if __name__ == "__main__":
    import os
    xml_path = "./data/raw/drugbank/full_database.xml"
    if not os.path.exists(xml_path):
        print("ERROR: DrugBank XML not found!")
        print("Please download from https://go.drugbank.com/releases")
        print(f"and place at {xml_path}")
    else:
        drugs, edges = parse_drugbank(xml_path)
        print(f"Parsed {len(drugs)} drugs, {len(edges)} drug-gene edges")
        # Load into Memgraph...
