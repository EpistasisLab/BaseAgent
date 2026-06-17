#!/usr/bin/env python3
"""
Parse Reactome UniProt2Reactome_All_Levels.txt
Outputs:
  ./data/processed/reactome/reactome_pathways.tsv
  ./data/processed/reactome/reactome_gene_pathway.tsv
"""

import csv, json, os
from collections import defaultdict

OUT_DIR = "./data/processed/reactome"
os.makedirs(OUT_DIR, exist_ok=True)

# Load mappings
with open('./data/processed/cvd_genes.json') as f:
    cvd = json.load(f)
CVD_SYMBOLS = set(cvd['symbols'])

with open('./data/processed/reactome/uniprot_to_gene.json') as f:
    UNIPROT_TO_GENE = json.load(f)

print(f"CVD genes: {len(CVD_SYMBOLS)}")
print(f"UniProt mappings: {len(UNIPROT_TO_GENE)}")

# Parse Reactome file
# Columns: UniProtKB_ID, Reactome_Pathway_ID, URL, Pathway_Name, Evidence, Species
REACTOME_PATH = "./data/processed/reactome/UniProt2Reactome_All_Levels.txt"

pathways = {}       # pathway_id -> {name}
gene_pathway = []   # {gene, pathway_id, pathway_name}
seen = set()

print("Parsing UniProt2Reactome_All_Levels.txt ...")
with open(REACTOME_PATH, encoding='utf-8') as fh:
    for line in fh:
        cols = line.rstrip('\n').split('\t')
        if len(cols) < 6:
            continue
        uniprot     = cols[0]
        pathway_id  = cols[1]
        pathway_name= cols[3]
        species     = cols[5]

        # Filter to human only
        if species != 'Homo sapiens':
            continue
        # Filter to CVD genes
        gene = UNIPROT_TO_GENE.get(uniprot)
        if not gene:
            continue

        # Store pathway
        if pathway_id not in pathways:
            pathways[pathway_id] = pathway_name

        key = (gene, pathway_id)
        if key not in seen:
            seen.add(key)
            gene_pathway.append({'gene': gene, 'pathwayId': pathway_id,
                                  'pathwayName': pathway_name})

print(f"  Human pathways found: {len(pathways)}")
print(f"  Gene-pathway edges:   {len(gene_pathway)}")
genes_covered = set(r['gene'] for r in gene_pathway)
print(f"  CVD genes covered:    {len(genes_covered)}")

# Write pathways TSV
PATHWAYS_PATH = f"{OUT_DIR}/reactome_pathways.tsv"
with open(PATHWAYS_PATH, 'w', newline='') as f:
    w = csv.writer(f, delimiter='\t')
    w.writerow(['pathwayId','pathwayName'])
    for pid, pname in pathways.items():
        w.writerow([pid, pname])
print(f"\nWritten {len(pathways)} pathways -> {PATHWAYS_PATH}")

# Write gene-pathway TSV
GP_PATH = f"{OUT_DIR}/reactome_gene_pathway.tsv"
with open(GP_PATH, 'w', newline='') as f:
    w = csv.writer(f, delimiter='\t')
    w.writerow(['geneSymbol','pathwayId','pathwayName'])
    for r in gene_pathway:
        w.writerow([r['gene'], r['pathwayId'], r['pathwayName']])
print(f"Written {len(gene_pathway)} edges -> {GP_PATH}")
