#!/usr/bin/env python3
"""BindingDB chemical-gene binding parser & loader for CardioKB.

Loads (Drug)-[:chemicalBindsGene {pchembl, activity_type, source:'BindingDB'}]->(Gene).
Anchors to existing Drug nodes via commonName when possible; otherwise creates new Drug nodes
via MERGE on commonName. Restricts to genes already in the graph.
"""
import argparse, os, csv, sys, urllib.request
from neo4j import GraphDatabase

PROC_DIR = './data/processed/bindingdb'
INPUT_FILE = os.path.join(PROC_DIR, 'chemical_gene_binding.tsv')
EDGES_FILE = os.path.join(PROC_DIR, 'chemical_binds_gene_loaded.tsv')
URL = 'https://www.bindingdb.org/rwd/bind/downloads/BindingDB_All_terse.tsv.zip'
URI = 'bolt://localhost:7688'

def download():
    print('[info] Full BindingDB download is multi-GB; using pre-extracted subset at', INPUT_FILE)
    if not os.path.exists(INPUT_FILE):
        print('[ERR] expected', INPUT_FILE); sys.exit(1)

def parse():
    os.makedirs(PROC_DIR, exist_ok=True)
    out = open(EDGES_FILE, 'w')
    out.write('drug\tgene\tpchembl\tactivity_type\n')
    n = 0
    with open(INPUT_FILE) as fh:
        rdr = csv.DictReader(fh, delimiter='\t')
        for r in rdr:
            d = (r.get('drug') or '').strip()
            g = (r.get('gene') or '').strip()
            if not d or not g: continue
            pc = r.get('pchembl') or ''
            at = r.get('activityType') or ''
            out.write(f'{d}\t{g}\t{pc}\t{at}\n')
            n += 1
    out.close()
    print(f'[parse] wrote {n} chemical-gene rows to {EDGES_FILE}')

def load():
    drv = GraphDatabase.driver(URI, auth=None)
    rows = []
    with open(EDGES_FILE) as fh:
        next(fh)
        for line in fh:
            parts = line.rstrip('\n').split('\t')
            while len(parts) < 4: parts.append('')
            d, g, pc, at = parts[:4]
            try: pc_f = float(pc) if pc else None
            except: pc_f = None
            rows.append({'d': d, 'g': g, 'pc': pc_f, 'at': at})
    print(f'[load] {len(rows)} rows')

    # Pre-fetch existing drug names to partition into MATCH vs MERGE
    drug_names = list({r['d'] for r in rows})
    existing = set()
    with drv.session() as s:
        BATCH_Q = 5000
        for i in range(0, len(drug_names), BATCH_Q):
            chunk = drug_names[i:i+BATCH_Q]
            res = s.run("UNWIND $names AS n MATCH (d:Drug {commonName: n}) RETURN d.commonName AS cn", names=chunk)
            for r in res: existing.add(r['cn'])
    print(f'[load] {len(existing)}/{len(drug_names)} drug names already in graph')

    match_rows = [r for r in rows if r['d'] in existing]
    merge_rows = [r for r in rows if r['d'] not in existing]

    cy_match = """
    UNWIND $rows AS r
    MATCH (g:Gene {geneSymbol: r.g})
    MATCH (d:Drug {commonName: r.d})
    MERGE (d)-[e:chemicalBindsGene {source:'BindingDB'}]->(g)
    SET e.pchembl = r.pc, e.activity_type = r.at
    """
    cy_merge = """
    UNWIND $rows AS r
    MATCH (g:Gene {geneSymbol: r.g})
    MERGE (d:Drug {commonName: r.d})
    MERGE (d)-[e:chemicalBindsGene {source:'BindingDB'}]->(g)
    SET e.pchembl = r.pc, e.activity_type = r.at
    """
    BATCH = 500
    with drv.session() as s:
        for i in range(0, len(match_rows), BATCH):
            s.run(cy_match, rows=match_rows[i:i+BATCH])
        for i in range(0, len(merge_rows), BATCH):
            s.run(cy_merge, rows=merge_rows[i:i+BATCH])
        c = s.run("MATCH ()-[r:chemicalBindsGene {source:'BindingDB'}]->() RETURN count(r) as c").single()['c']
        print(f'[done] BindingDB chemicalBindsGene = {c}')
    drv.close()

if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--download', action='store_true')
    ap.add_argument('--parse',    action='store_true')
    ap.add_argument('--load',     action='store_true')
    ap.add_argument('--all',      action='store_true')
    a = ap.parse_args()
    if a.all or a.download: download()
    if a.all or a.parse:    parse()
    if a.all or a.load:     load()
