#!/usr/bin/env python3
"""
Parse HGNC Gene Families (already processed).
Outputs:
  ./data/processed/hgnc/hgnc_families_cvd.tsv
  ./data/processed/hgnc/hgnc_gene_family_cvd.tsv
"""

import csv, json, os

OUT_DIR = "./data/processed/hgnc"

with open('./data/processed/cvd_genes.json') as f:
    cvd = json.load(f)
CVD_SYMBOLS = set(cvd['symbols'])
print(f"CVD genes: {len(CVD_SYMBOLS)}")

# Load existing gene_family_edges
edges = []
with open('./data/processed/hgnc/gene_family_edges.tsv', encoding='utf-8') as f:
    reader = csv.DictReader(f, delimiter='\t')
    for row in reader:
        if row['geneSymbol'] in CVD_SYMBOLS:
            edges.append({'geneSymbol': row['geneSymbol'],
                          'familyId':   str(row['familyId']),
                          'familyName': row['familyName']})

# Load existing gene_families
fam_ids_used = set(e['familyId'] for e in edges)
families = []
seen_fam = set()
with open('./data/processed/hgnc/gene_families.tsv', encoding='utf-8') as f:
    reader = csv.DictReader(f, delimiter='\t')
    for row in reader:
        fid = str(row['familyId'])
        if fid in fam_ids_used and fid not in seen_fam:
            families.append({'familyId': fid, 'familyName': row['familyName']})
            seen_fam.add(fid)

print(f"Gene-family edges (CVD): {len(edges)}")
print(f"Unique families (CVD):   {len(families)}")
genes_cov = set(e['geneSymbol'] for e in edges)
print(f"CVD genes covered:       {len(genes_cov)}")

# Write families TSV
FAM_PATH = f"{OUT_DIR}/hgnc_families_cvd.tsv"
with open(FAM_PATH, 'w', newline='') as f:
    w = csv.writer(f, delimiter='\t')
    w.writerow(['familyId','familyName'])
    for fam in families:
        w.writerow([fam['familyId'], fam['familyName']])
print(f"\nWritten {len(families)} families -> {FAM_PATH}")

# Write edges TSV
EDGES_PATH = f"{OUT_DIR}/hgnc_gene_family_cvd.tsv"
with open(EDGES_PATH, 'w', newline='') as f:
    w = csv.writer(f, delimiter='\t')
    w.writerow(['geneSymbol','familyId','familyName'])
    for e in edges:
        w.writerow([e['geneSymbol'], e['familyId'], e['familyName']])
print(f"Written {len(edges)} edges -> {EDGES_PATH}")
