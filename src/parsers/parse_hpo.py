#!/usr/bin/env python3
"""
Parse HPO genes_to_phenotype.txt
Outputs:
  ./data/processed/hpo/hpo_phenotypes.tsv
  ./data/processed/hpo/hpo_gene_phenotype.tsv
"""

import csv, json, os
from collections import defaultdict

OUT_DIR = "./data/processed/hpo"
os.makedirs(OUT_DIR, exist_ok=True)

with open('./data/processed/cvd_genes.json') as f:
    cvd = json.load(f)
CVD_SYMBOLS = set(cvd['symbols'])
print(f"CVD genes: {len(CVD_SYMBOLS)}")

HPO_PATH = "./data/processed/hpo/genes_to_phenotype.txt"

phenotypes = {}      # hpo_id -> hpo_name
gene_phenotype = []  # {gene, hpo_id, hpo_name}
seen = set()

print("Parsing genes_to_phenotype.txt ...")
with open(HPO_PATH, encoding='utf-8') as fh:
    reader = csv.DictReader(fh, delimiter='\t')
    for row in reader:
        gene   = row.get('gene_symbol','').strip()
        hpo_id = row.get('hpo_id','').strip()
        hpo_nm = row.get('hpo_name','').strip()

        if not gene or not hpo_id:
            continue
        if gene not in CVD_SYMBOLS:
            continue
        if not hpo_id.startswith('HP:'):
            continue

        if hpo_id not in phenotypes:
            phenotypes[hpo_id] = hpo_nm

        key = (gene, hpo_id)
        if key not in seen:
            seen.add(key)
            gene_phenotype.append({'gene': gene, 'xrefHPO': hpo_id, 'name': hpo_nm})

print(f"  Unique HPO phenotypes: {len(phenotypes)}")
print(f"  Gene-phenotype edges:  {len(gene_phenotype)}")
genes_covered = set(r['gene'] for r in gene_phenotype)
print(f"  CVD genes covered:     {len(genes_covered)}")

# Write phenotypes TSV
PHENO_PATH = f"{OUT_DIR}/hpo_phenotypes.tsv"
with open(PHENO_PATH, 'w', newline='') as f:
    w = csv.writer(f, delimiter='\t')
    w.writerow(['xrefHPO','name'])
    for hid, hname in phenotypes.items():
        w.writerow([hid, hname])
print(f"\nWritten {len(phenotypes)} phenotypes -> {PHENO_PATH}")

# Write gene-phenotype TSV
GP_PATH = f"{OUT_DIR}/hpo_gene_phenotype.tsv"
with open(GP_PATH, 'w', newline='') as f:
    w = csv.writer(f, delimiter='\t')
    w.writerow(['geneSymbol','xrefHPO','name'])
    for r in gene_phenotype:
        w.writerow([r['gene'], r['xrefHPO'], r['name']])
print(f"Written {len(gene_phenotype)} edges -> {GP_PATH}")
