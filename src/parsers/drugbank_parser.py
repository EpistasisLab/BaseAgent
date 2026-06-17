#!/usr/bin/env python3
"""DrugBank drug-target parser & loader for CardioKB.

DrugBank XML requires academic account; we use the pre-extracted
target interactions in ./data/processed/drugbank/drugbank_cvd_interactions.tsv
as the source. If a full feed is available, point INPUT_FILE at it.

Creates (Drug)-[:drugBindsGene {action, source:'DrugBank'}]->(Gene).
"""
import argparse, os, csv, urllib.request, sys
from neo4j import GraphDatabase

PROC_DIR = './data/processed/drugbank'
INPUT_FILE = os.path.join(PROC_DIR, 'drugbank_cvd_interactions.tsv')
EDGES_FILE = os.path.join(PROC_DIR, 'drug_binds_gene.tsv')
URI = 'bolt://localhost:7688'

def download():
    """DrugBank requires login; fallback informational only."""
    print('[info] DrugBank XML requires academic credentials.')
    print('[info] Using pre-extracted CVD-target subset at', INPUT_FILE)
    if not os.path.exists(INPUT_FILE):
        print('[ERR] expected', INPUT_FILE); sys.exit(1)

def parse():
    os.makedirs(PROC_DIR, exist_ok=True)
    out = open(EDGES_FILE, 'w')
    out.write('drug_name\tgene_symbol\tdrugbank_id\taction\n')
    n = 0
    with open(INPUT_FILE) as fh:
        rdr = csv.DictReader(fh, delimiter='\t')
        for r in rdr:
            name = (r.get('drug_name') or r.get('matched_drug') or '').strip()
            gene = (r.get('gene_symbol') or '').strip()
            db_id = (r.get('drugbank_id') or '').strip()
            act = (r.get('action') or r.get('actions') or '').strip()
            if not name or not gene: continue
            out.write(f'{name}\t{gene}\t{db_id}\t{act}\n')
            n += 1
    out.close()
    print(f'[parse] wrote {n} drug-gene edges to {EDGES_FILE}')

def load():
    drv = GraphDatabase.driver(URI, auth=None)
    rows = []
    with open(EDGES_FILE) as fh:
        next(fh)
        for line in fh:
            parts = line.rstrip('\n').split('\t')
            while len(parts) < 4: parts.append('')
            name, gene, db_id, act = parts[:4]
            rows.append({'name': name, 'gene': gene, 'db_id': db_id, 'act': act})
    print(f'[load] {len(rows)} edges')
    # Anchor to existing Drug nodes via commonName or drugBankId
    cypher = """
    UNWIND $rows AS r
    MATCH (g:Gene {geneSymbol: r.gene})
    OPTIONAL MATCH (d1:Drug {commonName: r.name})
    OPTIONAL MATCH (d2:Drug {drugBankId: r.db_id})
    WITH r, g, coalesce(d1, d2) AS d
    WHERE d IS NOT NULL
    MERGE (d)-[e:drugBindsGene {source:'DrugBank'}]->(g)
    SET e.action = r.act
    """
    BATCH = 1000
    with drv.session() as s:
        for i in range(0, len(rows), BATCH):
            s.run(cypher, rows=rows[i:i+BATCH])
        c = s.run("MATCH ()-[r:drugBindsGene {source:'DrugBank'}]->() RETURN count(r) as c").single()['c']
        print(f'[done] DrugBank drugBindsGene = {c}')
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
