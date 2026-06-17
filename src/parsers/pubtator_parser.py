#!/usr/bin/env python3
"""
PubTator Central Parser: Disease-Disease Co-occurrences
Source: https://ftp.ncbi.nlm.nih.gov/pub/lu/PubTatorCentral/disease2pubtatorcentral.gz
Target rel: (:Disease)-[:diseaseAssociatesWithDisease {source:'PubTator'}]->(:Disease)
Anchors: Disease.xrefDiseaseOntology (MATCH-only); restricted to CVD-scoped pairs.
"""
import argparse, os, sys, glob
import pandas as pd
from neo4j import GraphDatabase

URI = "bolt://localhost:7688"
RAW_DIR  = "./data/raw/pubtator"
PROC_DIR = "./data/processed/pubtator"
PROC_TSV = os.path.join(PROC_DIR, "cvd_disease_disease_edges.tsv")

def download():
    os.makedirs(RAW_DIR, exist_ok=True)
    if os.path.exists(os.path.join(PROC_DIR, "disease2pubtatorcentral.gz")):
        print(f"[download] disease2pubtatorcentral.gz already cached in {PROC_DIR}")
        return
    print("[download] would fetch https://ftp.ncbi.nlm.nih.gov/pub/lu/PubTatorCentral/disease2pubtatorcentral.gz")

def parse():
    os.makedirs(PROC_DIR, exist_ok=True)
    if os.path.exists(PROC_TSV):
        df = pd.read_csv(PROC_TSV, sep="\t")
        print(f"[parse] {PROC_TSV} already exists ({len(df):,} rows); skipping re-parse")
        return
    # Compute co-occurrences from disease2pubtatorcentral.gz
    src = os.path.join(PROC_DIR, "disease2pubtatorcentral.gz")
    if not os.path.exists(src):
        print(f"[parse] missing source {src}")
        sys.exit(1)
    import gzip
    from collections import defaultdict
    pmid2mesh = defaultdict(set)
    with gzip.open(src, "rt") as fh:
        for line in fh:
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 3: continue
            pmid, _, mesh_id = parts[0], parts[1], parts[2]
            if mesh_id.startswith("MESH:"):
                pmid2mesh[pmid].add(mesh_id)
    # Need MESH -> DOID. Use disease ontology
    driver = GraphDatabase.driver(URI, auth=None)
    with driver.session() as s:
        rows = s.run("MATCH (d:Disease) WHERE d.xrefMeshId IS NOT NULL RETURN d.xrefMeshId AS m, d.xrefDiseaseOntology AS doid").data()
        cvd_doids = set(r["d"] for r in s.run("MATCH (d:Disease) RETURN d.xrefDiseaseOntology AS d").data() if r["d"])
    driver.close()
    mesh2doid = {f"MESH:{r['m']}": r["doid"] for r in rows if r["m"] and r["doid"]}

    from collections import Counter
    pairs = Counter()
    for meshes in pmid2mesh.values():
        doids = sorted({mesh2doid[m] for m in meshes if m in mesh2doid and mesh2doid[m] in cvd_doids})
        for i in range(len(doids)):
            for j in range(i+1, len(doids)):
                pairs[(doids[i], doids[j])] += 1
    df = pd.DataFrame([{"disease1": a, "disease2": b, "cooccurrence": c, "source": "PubTator"} for (a,b), c in pairs.items()])
    df.to_csv(PROC_TSV, sep="\t", index=False)
    print(f"[parse] {len(df):,} disease-disease pairs -> {PROC_TSV}")

def load():
    df = pd.read_csv(PROC_TSV, sep="\t")
    driver = GraphDatabase.driver(URI, auth=None)
    q = """
    UNWIND $rows AS row
    MATCH (a:Disease {xrefDiseaseOntology: row.disease1})
    MATCH (b:Disease {xrefDiseaseOntology: row.disease2})
    MERGE (a)-[r:diseaseAssociatesWithDisease {source: 'PubTator'}]->(b)
    RETURN count(r) AS cnt
    """
    with driver.session() as s:
        pre_d = s.run("MATCH (d:Disease) RETURN count(d) AS c").single()["c"]
        pre   = s.run("MATCH ()-[r:diseaseAssociatesWithDisease {source:'PubTator'}]->() RETURN count(r) AS c").single()["c"]
    for i in range(0, len(df), 1000):
        batch = df.iloc[i:i+1000].to_dict("records")
        with driver.session() as s:
            s.execute_write(lambda tx, b: tx.run(q, rows=b).single()["cnt"], batch)
    with driver.session() as s:
        post   = s.run("MATCH ()-[r:diseaseAssociatesWithDisease {source:'PubTator'}]->() RETURN count(r) AS c").single()["c"]
        post_d = s.run("MATCH (d:Disease) RETURN count(d) AS c").single()["c"]
    print(f"[load] diseaseAssociatesWithDisease: pre={pre:,} post={post:,} Δ={post-pre:,}")
    print(f"[load] Disease count {pre_d:,} -> {post_d:,}")
    driver.close()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--download", action="store_true")
    ap.add_argument("--parse",    action="store_true")
    ap.add_argument("--load",     action="store_true")
    ap.add_argument("--all",      action="store_true")
    a = ap.parse_args()
    if a.all or a.download: download()
    if a.all or a.parse:    parse()
    if a.all or a.load:     load()

if __name__ == "__main__":
    main()
