#!/usr/bin/env python3
"""
Parse Gene Ontology OBO + human GAF annotations.
Outputs:
  ./data/processed/go/go_terms.tsv
  ./data/processed/go/go_annotations.tsv
"""

import gzip, csv, json, os, urllib.request
from collections import Counter

OUT_DIR = "./data/processed/go"
os.makedirs(OUT_DIR, exist_ok=True)

# Load CVD gene list
with open('./data/processed/cvd_genes.json') as f:
    cvd = json.load(f)
CVD_SYMBOLS = set(cvd['symbols'])
print(f"CVD genes loaded: {len(CVD_SYMBOLS)}")

OBO_PATH = "./data/processed/go/go.obo"
GAF_PATH = "./data/processed/go/goa_human.gaf.gz"

# 1. Parse OBO
print("Parsing go.obo ...")
terms = {}
cur   = {}
with open(OBO_PATH, encoding='utf-8') as fh:
    for line in fh:
        line = line.rstrip('\n')
        if line == '[Term]':
            if cur.get('id') and cur.get('namespace') not in ('external', 'obsolete', ''):
                terms[cur['id']] = {'name': cur.get('name',''), 'namespace': cur.get('namespace','')}
            cur = {}
        elif line.startswith('id: '):
            cur['id'] = line[4:]
        elif line.startswith('name: '):
            cur['name'] = line[6:]
        elif line.startswith('namespace: '):
            cur['namespace'] = line[11:]
        elif line.startswith('is_obsolete: true'):
            cur['namespace'] = 'obsolete'
    if cur.get('id') and cur.get('namespace') not in ('external', 'obsolete', ''):
        terms[cur['id']] = {'name': cur.get('name',''), 'namespace': cur.get('namespace','')}

print(f"  GO terms parsed: {len(terms)}")

# 2. Write go_terms.tsv
TERMS_PATH = f"{OUT_DIR}/go_terms.tsv"
with open(TERMS_PATH, 'w', newline='') as f:
    w = csv.writer(f, delimiter='\t')
    w.writerow(['geneOntologyId','name','namespace'])
    for goid, info in terms.items():
        w.writerow([goid, info['name'], info['namespace']])
print(f"  Written {len(terms)} terms -> {TERMS_PATH}")

# 3. Parse GAF
print("Parsing GAF annotations ...")
NS_MAP = {'P': 'biological_process', 'F': 'molecular_function', 'C': 'cellular_component'}
annotations = []
seen = set()

with gzip.open(GAF_PATH, 'rt') as fh:
    for line in fh:
        if line.startswith('!'):
            continue
        cols = line.rstrip('\n').split('\t')
        if len(cols) < 13:
            continue
        symbol    = cols[2]
        go_id     = cols[4]
        aspect    = cols[8]
        evidence  = cols[6]
        qualifier = cols[3]
        if 'NOT' in qualifier:
            continue
        if symbol not in CVD_SYMBOLS:
            continue
        if go_id not in terms:
            continue
        key = (symbol, go_id)
        if key in seen:
            continue
        seen.add(key)
        ns = NS_MAP.get(aspect, '')
        annotations.append({'gene': symbol, 'go_id': go_id,
                             'namespace': ns, 'evidence': evidence,
                             'name': terms[go_id]['name']})

print(f"  Filtered annotations (CVD genes): {len(annotations)}")

# 4. Write go_annotations.tsv
ANN_PATH = f"{OUT_DIR}/go_annotations.tsv"
with open(ANN_PATH, 'w', newline='') as f:
    w = csv.writer(f, delimiter='\t')
    w.writerow(['geneSymbol','geneOntologyId','name','namespace','evidence'])
    for a in annotations:
        w.writerow([a['gene'], a['go_id'], a['name'], a['namespace'], a['evidence']])
print(f"  Written {len(annotations)} annotations -> {ANN_PATH}")

ns_counts = Counter(a['namespace'] for a in annotations)
print("\n=== Annotation namespace breakdown ===")
for ns, cnt in ns_counts.items():
    print(f"  {ns}: {cnt}")

# Unique GO IDs per namespace
bp_ids = set(a['go_id'] for a in annotations if a['namespace']=='biological_process')
mf_ids = set(a['go_id'] for a in annotations if a['namespace']=='molecular_function')
cc_ids = set(a['go_id'] for a in annotations if a['namespace']=='cellular_component')
print(f"\nUnique BiologicalProcess terms: {len(bp_ids)}")
print(f"Unique MolecularFunction terms:  {len(mf_ids)}")
print(f"Unique CellularComponent terms:  {len(cc_ids)}")
