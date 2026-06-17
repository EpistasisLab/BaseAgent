#!/usr/bin/env python3
"""
OpenTargets Parser: Gene-Disease Associations
Source: Platform Parquet downloads at https://platform.opentargets.org/downloads
Target rel: (:Gene)-[:geneAssociatesWithDisease {source:'OpenTargets'}]->(:Disease)
Anchors: Gene.geneSymbol (MATCH-only), Disease.xrefDiseaseOntology (MATCH-only)
"""
import argparse, os, sys, glob
import pandas as pd
from neo4j import GraphDatabase

URI = "bolt://localhost:7688"
RAW_DIR = "./data/raw/opentargets"
PROC_DIR = "./data/processed/opentargets"
PROC_TSV = os.path.join(PROC_DIR, "cvd_gene_disease_edges.tsv")
OT_VERSION = "24.06"

def download():
    os.makedirs(RAW_DIR, exist_ok=True)
    parquet_files = glob.glob(os.path.join(PROC_DIR, "*.parquet"))
    if parquet_files:
        print(f"[download] Found {len(parquet_files)} parquet files already in {PROC_DIR}; skip")
        return
    print(f"[download] (would download diseases/ and associationByOverallDirect/ parquet from")
    print(f"  https://ftp.ebi.ac.uk/pub/databases/opentargets/platform/{OT_VERSION}/output/etl/parquet)")

def parse():
    os.makedirs(PROC_DIR, exist_ok=True)
    if os.path.exists(PROC_TSV):
        df = pd.read_csv(PROC_TSV, sep="\t")
        print(f"[parse] {PROC_TSV} already exists ({len(df):,} rows); skipping re-parse")
        return
    driver = GraphDatabase.driver(URI, auth=None)
    with driver.session() as s:
        cvd_doids = set(r["d"] for r in s.run("MATCH (d:Disease) RETURN d.xrefDiseaseOntology AS d").data() if r["d"])
        gene_symbols = set(r["g"] for r in s.run("MATCH (g:Gene) RETURN g.geneSymbol AS g").data() if r["g"])
        ens2sym = {r["e"]: r["g"] for r in s.run("MATCH (g:Gene) WHERE g.ensemblGeneId IS NOT NULL RETURN g.ensemblGeneId AS e, g.geneSymbol AS g").data()}
    driver.close()
    print(f"[parse] CVD DOIDs={len(cvd_doids)} Genes={len(gene_symbols)} Ensembl={len(ens2sym)}")
    assoc_files = glob.glob(os.path.join(PROC_DIR, "*assoc*.parquet"))
    if not assoc_files:
        print(f"[parse] No association parquet found; cannot parse")
        sys.exit(1)
    df = pd.concat([pd.read_parquet(p) for p in assoc_files], ignore_index=True)
    df["geneSymbol"] = df["targetId"].map(ens2sym)
    disease_files = glob.glob(os.path.join(PROC_DIR, "disease_part*.parquet"))
    efo2doid = {}
    if disease_files:
        ddf = pd.concat([pd.read_parquet(p) for p in disease_files], ignore_index=True)
        for _, row in ddf.iterrows():
            xrefs = row.get("dbXRefs") or row.get("xrefs")
            if xrefs is None: continue
            for x in xrefs:
                if isinstance(x, str) and x.startswith("DOID:"):
                    efo2doid[row["id"]] = x; break
    df["xrefDiseaseOntology"] = df["diseaseId"].map(efo2doid)
    df = df[df["geneSymbol"].notna() & df["xrefDiseaseOntology"].notna()]
    df = df[df["geneSymbol"].isin(gene_symbols) & df["xrefDiseaseOntology"].isin(cvd_doids)]
    df["source"] = "OpenTargets"; df["diseaseName"] = ""
    out = df[["geneSymbol","xrefDiseaseOntology","diseaseName","score","source"]].drop_duplicates()
    out.to_csv(PROC_TSV, sep="\t", index=False)
    print(f"[parse] Wrote {len(out):,} edges to {PROC_TSV}")

def load():
    df = pd.read_csv(PROC_TSV, sep="\t")
    driver = GraphDatabase.driver(URI, auth=None)
    q = """
    UNWIND $rows AS row
    MATCH (g:Gene {geneSymbol: row.geneSymbol})
    MATCH (d:Disease {xrefDiseaseOntology: row.xrefDiseaseOntology})
    MERGE (g)-[r:geneAssociatesWithDisease {source: 'OpenTargets'}]->(d)
    ON CREATE SET r.score = row.score
    ON MATCH  SET r.score = row.score
    RETURN count(r) AS cnt
    """
    with driver.session() as s:
        pre_g = s.run("MATCH (g:Gene) RETURN count(g) AS c").single()["c"]
        pre_d = s.run("MATCH (d:Disease) RETURN count(d) AS c").single()["c"]
        pre   = s.run("MATCH ()-[r:geneAssociatesWithDisease {source:'OpenTargets'}]->() RETURN count(r) AS c").single()["c"]
    rows = df.to_dict("records")
    bs = 1000
    for i in range(0, len(rows), bs):
        with driver.session() as s:
            s.execute_write(lambda tx, b: tx.run(q, rows=b).single()["cnt"], rows[i:i+bs])
    with driver.session() as s:
        post  = s.run("MATCH ()-[r:geneAssociatesWithDisease {source:'OpenTargets'}]->() RETURN count(r) AS c").single()["c"]
        post_g = s.run("MATCH (g:Gene) RETURN count(g) AS c").single()["c"]
        post_d = s.run("MATCH (d:Disease) RETURN count(d) AS c").single()["c"]
    print(f"[load] OpenTargets geneAssociatesWithDisease: pre={pre:,} post={post:,} Δ={post-pre:,}")
    print(f"[load] Gene count: {pre_g:,} -> {post_g:,} ; Disease count: {pre_d:,} -> {post_d:,}")
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
