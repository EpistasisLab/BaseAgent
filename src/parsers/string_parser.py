#!/usr/bin/env python3
"""STRING PPI parser & loader for CardioKB.

Downloads human PPI from STRING-DB, filters by combined_score >= 700,
restricts to genes already in the graph, and loads as
(Gene)-[:geneInteractsWithGene {score, source:'STRING'}]->(Gene).
"""
import argparse, os, gzip, sys, urllib.request
from neo4j import GraphDatabase

RAW_DIR = './data/processed/string'
PROC_DIR = './data/processed/string'
LINKS_URL = 'https://stringdb-downloads.org/download/protein.links.v12.0/9606.protein.links.v12.0.txt.gz'
INFO_URL  = 'https://stringdb-downloads.org/download/protein.info.v12.0/9606.protein.info.v12.0.txt.gz'
LINKS_FILE = os.path.join(RAW_DIR, '9606.protein.links.v12.0.txt.gz')
INFO_FILE  = os.path.join(RAW_DIR, '9606.protein.info.v12.0.txt.gz')
EDGES_FILE = os.path.join(PROC_DIR, 'gene_interactions.tsv')
SCORE_CUTOFF = 700

URI = 'bolt://localhost:7688'

def download():
    os.makedirs(RAW_DIR, exist_ok=True)
    for url, dest in [(LINKS_URL, LINKS_FILE), (INFO_URL, INFO_FILE)]:
        if os.path.exists(dest):
            print(f'[skip] {dest}')
            continue
        print(f'[download] {url}')
        urllib.request.urlretrieve(url, dest)

def parse():
    # Build STRING_id -> gene_symbol map
    sp2sym = {}
    with gzip.open(INFO_FILE, 'rt') as fh:
        next(fh)
        for line in fh:
            parts = line.rstrip().split('\t')
            sp2sym[parts[0]] = parts[1]
    print(f'[parse] {len(sp2sym)} protein->symbol mappings')

    out = open(EDGES_FILE, 'w')
    out.write('gene1\tgene2\tscore\n')
    n = 0
    with gzip.open(LINKS_FILE, 'rt') as fh:
        next(fh)
        for line in fh:
            p1, p2, s = line.rstrip().split(' ')
            s = int(s)
            if s < SCORE_CUTOFF: continue
            g1 = sp2sym.get(p1); g2 = sp2sym.get(p2)
            if not g1 or not g2 or g1 == g2: continue
            # write canonical order to avoid dup
            if g1 > g2: g1, g2 = g2, g1
            out.write(f'{g1}\t{g2}\t{s}\n')
            n += 1
    out.close()
    print(f'[parse] wrote {n} edges to {EDGES_FILE}')

def load():
    drv = GraphDatabase.driver(URI, auth=None)
    rows = []
    with open(EDGES_FILE) as fh:
        next(fh)
        for line in fh:
            g1, g2, s = line.rstrip().split('\t')
            rows.append({'g1': g1, 'g2': g2, 's': int(s)})
    print(f'[load] {len(rows)} edges parsed')
    cypher = """
    UNWIND $rows AS r
    MATCH (a:Gene {geneSymbol: r.g1})
    MATCH (b:Gene {geneSymbol: r.g2})
    MERGE (a)-[e:geneInteractsWithGene {source:'STRING'}]->(b)
    SET e.score = r.s
    """
    BATCH = 5000
    with drv.session() as s:
        for i in range(0, len(rows), BATCH):
            s.run(cypher, rows=rows[i:i+BATCH])
            if i % (BATCH*10) == 0:
                print(f'  loaded {i}/{len(rows)}')
    # verify
    with drv.session() as s:
        c = s.run("MATCH ()-[r:geneInteractsWithGene {source:'STRING'}]->() RETURN count(r) as c").single()['c']
        print(f'[done] STRING geneInteractsWithGene count = {c}')
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
