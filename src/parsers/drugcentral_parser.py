#!/usr/bin/env python3
"""
DrugCentral Parser
Sources:
  - DrugCentral ActiveDownload (https://drugcentral.org/ActiveDownload):
       drug.target.interaction.tsv.gz, omop_relationship.tsv.gz, pharma_class.tsv (optional)
  - Hetionet edge file as fallback (encapsulates DrugCentral indications)
Targets:
  - (:Drug)-[:drugTreatsDisease    {source:'DrugCentral'}]->(:Disease)
  - (:Drug)-[:drugPalliatesDisease {source:'DrugCentral'}]->(:Disease)
  - (:PharmacologicClass {classId})  primary key
  - (:PharmacologicClass)-[:pharmacologicClassIncludesCompound {source:'DrugCentral'}]->(:Drug)
  - (:Drug)-[:compoundInPharmacologicClass {source:'DrugCentral'}]->(:PharmacologicClass)
Anchors: Drug.commonName (MATCH-only), Disease.xrefDiseaseOntology (MATCH-only).
PharmacologicClass.classId is MERGE (allowed: this loader OWNS PharmacologicClass).
"""
import argparse, os, sys, glob
import pandas as pd
from neo4j import GraphDatabase

URI = "bolt://localhost:7688"
RAW_DIR  = "./data/raw/drugcentral"
PROC_DIR = "./data/processed/drugcentral"
TREATS_TSV    = os.path.join(PROC_DIR, "drug_treats_disease_edges.tsv")
PALLIATES_TSV = os.path.join(PROC_DIR, "drug_palliates_disease_edges.tsv")
PHARM_NODES_TSV = os.path.join(PROC_DIR, "pharmacologic_class_nodes.tsv")
PHARM_EDGES_TSV = os.path.join(PROC_DIR, "pharmacologic_class_includes_compound.tsv")

HETIONET_PATH    = "./data/processed/medline/hetionet-v1.0-edges.sif"
DRUGBANK_VOCAB   = "./data/processed/drugbank/drugs.tsv"

def download():
    os.makedirs(RAW_DIR, exist_ok=True)
    have = [os.path.basename(p) for p in glob.glob(os.path.join(PROC_DIR, "*"))]
    print(f"[download] DrugCentral processed files present: {have}")
    print("[download] (drug.target.interaction.tsv.gz and omop_relationship.tsv.gz already cached)")

def parse():
    os.makedirs(PROC_DIR, exist_ok=True)

    # 1. treats / palliates from Hetionet (DrugCentral indications)
    if os.path.exists(TREATS_TSV) and os.path.exists(PALLIATES_TSV):
        print(f"[parse] treats/palliates TSVs already exist; skipping")
    else:
        driver = GraphDatabase.driver(URI, auth=None)
        with driver.session() as s:
            cvd_drug_names = set(r["n"] for r in s.run("MATCH (d:Drug) RETURN d.commonName AS n").data() if r["n"])
            cvd_doids      = set(r["d"] for r in s.run("MATCH (d:Disease) RETURN d.xrefDiseaseOntology AS d").data() if r["d"])
        driver.close()
        df = pd.read_csv(HETIONET_PATH, sep="\t")
        db = pd.read_csv(DRUGBANK_VOCAB, sep="\t")
        names_lower = {n.lower(): n for n in cvd_drug_names if n}
        db_to_cvd = {row["drugbankId"]: names_lower[row["commonName"].lower()]
                     for _, row in db.iterrows()
                     if pd.notna(row["commonName"]) and row["commonName"].lower() in names_lower}
        for tag, out, rel in [("CtD", TREATS_TSV, "drugTreatsDisease"),
                              ("CpD", PALLIATES_TSV, "drugPalliatesDisease")]:
            df_r = df[df["metaedge"] == tag].copy()
            df_r["drugBankId"] = df_r["source"].str.replace("Compound::", "")
            df_r["doid"]       = df_r["target"].str.replace("Disease::", "")
            df_r = df_r[df_r["drugBankId"].isin(db_to_cvd) & df_r["doid"].isin(cvd_doids)].copy()
            df_r["commonName"]   = df_r["drugBankId"].map(db_to_cvd)
            df_r["source"]       = "DrugCentral"
            df_r["relationship"] = rel
            df_r[["commonName","doid","source","relationship"]].drop_duplicates().to_csv(out, sep="\t", index=False)
            print(f"[parse] {rel}: {len(df_r):,} edges -> {out}")

    # 2. PharmacologicClass nodes + includesCompound edges (from Hetionet PCiC)
    if os.path.exists(PHARM_NODES_TSV) and os.path.exists(PHARM_EDGES_TSV):
        print(f"[parse] pharmacologic_class TSVs already exist; skipping")
        return
    driver = GraphDatabase.driver(URI, auth=None)
    with driver.session() as s:
        cvd_drug_names = set(r["n"] for r in s.run("MATCH (d:Drug) RETURN d.commonName AS n").data() if r["n"])
    driver.close()
    db = pd.read_csv(DRUGBANK_VOCAB, sep="\t")
    names_lower = {n.lower(): n for n in cvd_drug_names if n}
    db_to_cvd = {row["drugbankId"]: names_lower[row["commonName"].lower()]
                 for _, row in db.iterrows()
                 if pd.notna(row["commonName"]) and row["commonName"].lower() in names_lower}

    df = pd.read_csv(HETIONET_PATH, sep="\t")
    df_pc = df[df["metaedge"] == "PCiC"].copy()
    df_pc["classId"]    = df_pc["source"].str.replace("Pharmacologic Class::", "")
    df_pc["drugBankId"] = df_pc["target"].str.replace("Compound::", "")
    df_pc["commonName"] = df_pc["drugBankId"].map(db_to_cvd)
    df_pc = df_pc[df_pc["commonName"].notna()].copy()
    df_pc["source"] = "DrugCentral"
    nodes = df_pc[["classId"]].drop_duplicates()
    nodes["source"] = "DrugCentral"
    nodes.to_csv(PHARM_NODES_TSV, sep="\t", index=False)
    edges = df_pc[["classId","commonName","source"]].drop_duplicates()
    edges.to_csv(PHARM_EDGES_TSV, sep="\t", index=False)
    print(f"[parse] PharmacologicClass nodes: {len(nodes):,} -> {PHARM_NODES_TSV}")
    print(f"[parse] PCiC edges: {len(edges):,} -> {PHARM_EDGES_TSV}")

def _counts(s, rel):
    return s.run(f"MATCH ()-[r:{rel} {{source:'DrugCentral'}}]->() RETURN count(r) AS c").single()["c"]

def load():
    driver = GraphDatabase.driver(URI, auth=None)

    # Treats
    df = pd.read_csv(TREATS_TSV, sep="\t")
    q_t = """
    UNWIND $rows AS row
    MATCH (dr:Drug {commonName: row.commonName})
    MATCH (di:Disease {xrefDiseaseOntology: row.doid})
    MERGE (dr)-[r:drugTreatsDisease {source: 'DrugCentral'}]->(di)
    RETURN count(r) AS cnt
    """
    with driver.session() as s:
        pre_d  = s.run("MATCH (d:Drug) RETURN count(d) AS c").single()["c"]
        pre_di = s.run("MATCH (d:Disease) RETURN count(d) AS c").single()["c"]
        pre_t  = _counts(s, "drugTreatsDisease")
    for i in range(0, len(df), 1000):
        with driver.session() as s:
            s.execute_write(lambda tx, b: tx.run(q_t, rows=b).single()["cnt"], df.iloc[i:i+1000].to_dict("records"))
    with driver.session() as s:
        post_t = _counts(s, "drugTreatsDisease")
    print(f"[load] drugTreatsDisease: pre={pre_t:,} post={post_t:,} Δ={post_t-pre_t:,}")

    # Palliates
    df = pd.read_csv(PALLIATES_TSV, sep="\t")
    q_p = q_t.replace("drugTreatsDisease", "drugPalliatesDisease")
    with driver.session() as s:
        pre_p = _counts(s, "drugPalliatesDisease")
    for i in range(0, len(df), 1000):
        with driver.session() as s:
            s.execute_write(lambda tx, b: tx.run(q_p, rows=b).single()["cnt"], df.iloc[i:i+1000].to_dict("records"))
    with driver.session() as s:
        post_p = _counts(s, "drugPalliatesDisease")
    print(f"[load] drugPalliatesDisease: pre={pre_p:,} post={post_p:,} Δ={post_p-pre_p:,}")

    # PharmacologicClass nodes
    nodes = pd.read_csv(PHARM_NODES_TSV, sep="\t")
    q_n = """
    UNWIND $rows AS row
    MERGE (p:PharmacologicClass {classId: row.classId})
    ON CREATE SET p.source = 'DrugCentral'
    RETURN count(p) AS cnt
    """
    with driver.session() as s:
        pre_pc = s.run("MATCH (p:PharmacologicClass) RETURN count(p) AS c").single()["c"]
    for i in range(0, len(nodes), 1000):
        with driver.session() as s:
            s.execute_write(lambda tx, b: tx.run(q_n, rows=b).single()["cnt"], nodes.iloc[i:i+1000].to_dict("records"))
    with driver.session() as s:
        post_pc = s.run("MATCH (p:PharmacologicClass) RETURN count(p) AS c").single()["c"]
    print(f"[load] PharmacologicClass nodes: pre={pre_pc:,} post={post_pc:,} Δ={post_pc-pre_pc:,}")

    # PCiC edges (both directions)
    edges = pd.read_csv(PHARM_EDGES_TSV, sep="\t")
    q_e = """
    UNWIND $rows AS row
    MATCH (p:PharmacologicClass {classId: row.classId})
    MATCH (d:Drug {commonName: row.commonName})
    MERGE (p)-[r1:pharmacologicClassIncludesCompound {source: 'DrugCentral'}]->(d)
    MERGE (d)-[r2:compoundInPharmacologicClass {source: 'DrugCentral'}]->(p)
    RETURN count(r1) AS cnt
    """
    with driver.session() as s:
        pre_e1 = s.run("MATCH ()-[r:pharmacologicClassIncludesCompound]->() RETURN count(r) AS c").single()["c"]
        pre_e2 = s.run("MATCH ()-[r:compoundInPharmacologicClass]->() RETURN count(r) AS c").single()["c"]
    for i in range(0, len(edges), 1000):
        with driver.session() as s:
            s.execute_write(lambda tx, b: tx.run(q_e, rows=b).single()["cnt"], edges.iloc[i:i+1000].to_dict("records"))
    with driver.session() as s:
        post_e1 = s.run("MATCH ()-[r:pharmacologicClassIncludesCompound]->() RETURN count(r) AS c").single()["c"]
        post_e2 = s.run("MATCH ()-[r:compoundInPharmacologicClass]->() RETURN count(r) AS c").single()["c"]
        post_d  = s.run("MATCH (d:Drug) RETURN count(d) AS c").single()["c"]
        post_di = s.run("MATCH (d:Disease) RETURN count(d) AS c").single()["c"]
    print(f"[load] pharmacologicClassIncludesCompound: pre={pre_e1:,} post={post_e1:,} Δ={post_e1-pre_e1:,}")
    print(f"[load] compoundInPharmacologicClass:      pre={pre_e2:,} post={post_e2:,} Δ={post_e2-pre_e2:,}")
    print(f"[load] Drug count {pre_d:,} -> {post_d:,} ; Disease count {pre_di:,} -> {post_di:,}")
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
