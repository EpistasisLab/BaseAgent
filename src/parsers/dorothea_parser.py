#!/usr/bin/env python3
"""DoRothEA (OmniPath) TF-gene parser & loader for CardioKB.

Fetches TF -> target interactions from OmniPath DoRothEA dataset,
filters to confidence A/B/C, creates TranscriptionFactor nodes
(primary key TF = gene symbol), and loads
(TranscriptionFactor)-[:transcriptionFactorInteractsWithGene {confidence, source:'DoRothEA'}]->(Gene).
"""
import argparse, os, sys, urllib.request, csv
from neo4j import GraphDatabase

RAW_DIR = './data/raw/dorothea'
PROC_DIR = './data/processed/dorothea'
RAW_FILE = os.path.join(RAW_DIR, 'omnipath_dorothea.tsv')
EDGES_FILE = os.path.join(PROC_DIR, 'tf_gene_edges_loaded.tsv')
TF_FILE = os.path.join(PROC_DIR, 'tf_nodes_loaded.tsv')
URL = 'https://omnipathdb.org/interactions?datasets=dorothea&fields=sources,references,dorothea_level&dorothea_levels=A,B,C&genesymbols=1'
URI = 'bolt://localhost:7688'

def download():
    os.makedirs(RAW_DIR, exist_ok=True)
    if os.path.exists(RAW_FILE):
        print(f'[skip] {RAW_FILE}')
        return
    print(f'[download] {URL}')
    urllib.request.urlretrieve(URL, RAW_FILE)

def parse():
    os.makedirs(PROC_DIR, exist_ok=True)
    src = './data/processed/dorothea/dorothea_raw_ABC.tsv'
    if not os.path.exists(src):
        src = RAW_FILE
    tfs = set()
    rows = []
    with open(src) as fh:
        rdr = csv.DictReader(fh, delimiter='\t')
        for r in rdr:
            tf = r.get('source_genesymbol') or r.get('tf') or r.get('tf_symbol')
            tg = r.get('target_genesymbol') or r.get('target') or r.get('target_gene')
            conf = r.get('confidence') or r.get('dorothea_level') or 'C'
            if not tf or not tg: continue
            tfs.add(tf)
            rows.append((tf, tg, conf))
    with open(TF_FILE, 'w') as fh:
        fh.write('TF\n')
        for t in sorted(tfs): fh.write(t + '\n')
    with open(EDGES_FILE, 'w') as fh:
        fh.write('tf\ttarget\tconfidence\n')
        for tf, tg, c in rows:
            fh.write(f'{tf}\t{tg}\t{c}\n')
    print(f'[parse] {len(tfs)} TFs, {len(rows)} edges')

def load():
    drv = GraphDatabase.driver(URI, auth=None)
    tfs = [l.strip() for l in open(TF_FILE)][1:]
    rows = []
    with open(EDGES_FILE) as fh:
        next(fh)
        for line in fh:
            tf, tg, c = line.rstrip().split('\t')
            rows.append({'tf': tf, 'tg': tg, 'c': c})
    print(f'[load] {len(tfs)} TFs, {len(rows)} edges')
    with drv.session() as s:
        # Index/constraint (Memgraph)
        try:
            s.run("CREATE INDEX ON :TranscriptionFactor(TF)")
        except Exception: pass
        # Create TF nodes (MERGE)
        s.run("UNWIND $tfs AS t MERGE (:TranscriptionFactor {TF: t})", tfs=tfs)
    cypher = """
    UNWIND $rows AS r
    MATCH (g:Gene {geneSymbol: r.tg})
    MERGE (tf:TranscriptionFactor {TF: r.tf})
    MERGE (tf)-[e:transcriptionFactorInteractsWithGene {source:'DoRothEA'}]->(g)
    SET e.confidence = r.c
    """
    BATCH = 2000
    with drv.session() as s:
        for i in range(0, len(rows), BATCH):
            s.run(cypher, rows=rows[i:i+BATCH])
        c = s.run("MATCH ()-[r:transcriptionFactorInteractsWithGene {source:'DoRothEA'}]->() RETURN count(r) as c").single()['c']
        print(f'[done] DoRothEA transcriptionFactorInteractsWithGene = {c}')
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
