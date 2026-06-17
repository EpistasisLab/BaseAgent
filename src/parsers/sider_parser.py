#!/usr/bin/env python3
"""
SIDER Parser: SideEffect nodes + Drug -> SideEffect edges
Source: http://sideeffects.embl.de/media/download/ (meddra_all_se.tsv.gz, drug_names.tsv)
Targets:
  - (:SideEffect {xrefUmlsCUI})  primary key
  - (:Drug)-[:compoundCausesSideEffect {source:'SIDER'}]->(:SideEffect)
Anchors: Drug.commonName (MATCH-only)
"""
import argparse, os, sys
import pandas as pd
from neo4j import GraphDatabase

URI = "bolt://localhost:7688"
RAW_DIR  = "./data/raw/sider"
PROC_DIR = "./data/processed/sider"
NODES_TSV = os.path.join(PROC_DIR, "side_effect_nodes.tsv")
EDGES_TSV = os.path.join(PROC_DIR, "cvd_drug_side_effect_edges.tsv")

def download():
    os.makedirs(RAW_DIR, exist_ok=True)
    for f in ["meddra_all_se.gz", "drug_names.tsv"]:
        if os.path.exists(os.path.join(PROC_DIR, f)):
            print(f"[download] {f} already cached")
    print("[download] would fetch http://sideeffects.embl.de/media/download/meddra_all_se.tsv.gz, drug_names.tsv")

def parse():
    os.makedirs(PROC_DIR, exist_ok=True)
    if os.path.exists(NODES_TSV) and os.path.exists(EDGES_TSV):
        n = pd.read_csv(NODES_TSV, sep="\t"); e = pd.read_csv(EDGES_TSV, sep="\t")
        print(f"[parse] outputs exist: nodes={len(n):,} edges={len(e):,}")
        return
    print("[parse] precomputed TSVs missing; would parse meddra_all_se.gz + drug_names.tsv here")
    sys.exit(1)

def load():
    driver = GraphDatabase.driver(URI, auth=None)

    # SideEffect nodes
    df_n = pd.read_csv(NODES_TSV, sep="\t")
    q_n = """
    UNWIND $rows AS row
    MERGE (s:SideEffect {xrefUmlsCUI: row.xrefUmlsCUI})
    ON CREATE SET s.name = row.sideEffectName, s.source = 'SIDER'
    ON MATCH  SET s.name = row.sideEffectName
    RETURN count(s) AS cnt
    """
    with driver.session() as s:
        pre_n = s.run("MATCH (s:SideEffect) RETURN count(s) AS c").single()["c"]
    for i in range(0, len(df_n), 1000):
        with driver.session() as s:
            s.execute_write(lambda tx, b: tx.run(q_n, rows=b).single()["cnt"], df_n.iloc[i:i+1000].to_dict("records"))
    with driver.session() as s:
        post_n = s.run("MATCH (s:SideEffect) RETURN count(s) AS c").single()["c"]
    print(f"[load] SideEffect nodes: pre={pre_n:,} post={post_n:,} Δ={post_n-pre_n:,}")

    # Edges
    df_e = pd.read_csv(EDGES_TSV, sep="\t")
    q_e = """
    UNWIND $rows AS row
    MATCH (d:Drug {commonName: row.commonName})
    MATCH (s:SideEffect {xrefUmlsCUI: row.xrefUmlsCUI})
    MERGE (d)-[r:compoundCausesSideEffect {source: 'SIDER'}]->(s)
    RETURN count(r) AS cnt
    """
    with driver.session() as s:
        pre_d = s.run("MATCH (d:Drug) RETURN count(d) AS c").single()["c"]
        pre_e = s.run("MATCH ()-[r:compoundCausesSideEffect {source:'SIDER'}]->() RETURN count(r) AS c").single()["c"]
    for i in range(0, len(df_e), 1000):
        with driver.session() as s:
            s.execute_write(lambda tx, b: tx.run(q_e, rows=b).single()["cnt"], df_e.iloc[i:i+1000].to_dict("records"))
    with driver.session() as s:
        post_e = s.run("MATCH ()-[r:compoundCausesSideEffect {source:'SIDER'}]->() RETURN count(r) AS c").single()["c"]
        post_d = s.run("MATCH (d:Drug) RETURN count(d) AS c").single()["c"]
    print(f"[load] compoundCausesSideEffect: pre={pre_e:,} post={post_e:,} Δ={post_e-pre_e:,}")
    print(f"[load] Drug count {pre_d:,} -> {post_d:,}")
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
