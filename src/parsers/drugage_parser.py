#!/usr/bin/env python3
"""
DrugAge Parser for CardioKB
Downloads, parses, and loads DrugAge data (AgeingProperty nodes + 
associatedWithAging edges) into Memgraph.

Usage:
  python drugage_parser.py --download
  python drugage_parser.py --parse
  python drugage_parser.py --load
  python drugage_parser.py --all
"""

import argparse
import os
import sys
import zipfile
import urllib.request
import pandas as pd
from neo4j import GraphDatabase

# Configuration
DRUGAGE_URL = "https://genomics.senescence.info/drugs/dataset.zip"
RAW_DIR = "./data/raw/drugage"
PROCESSED_DIR = "./data/processed/drugage"
MEMGRAPH_URI = "bolt://localhost:7688"
SOURCE_LABEL = "DrugAge"

AGEING_PROPERTIES = [
    {"propertyName": "Lifespan Extension",
     "description": "Compound extends average lifespan in model organism"},
    {"propertyName": "Lifespan Reduction",
     "description": "Compound reduces average lifespan in model organism"},
    {"propertyName": "No Significant Effect",
     "description": "Compound has no significant effect on lifespan"},
]


def download():
    os.makedirs(RAW_DIR, exist_ok=True)
    zip_path = os.path.join(RAW_DIR, "dataset.zip")
    csv_path = os.path.join(PROCESSED_DIR, "drugage_dataset.csv")
    os.makedirs(PROCESSED_DIR, exist_ok=True)
    if os.path.exists(csv_path):
        print(f"[download] DrugAge CSV already exists: {csv_path}")
        return csv_path
    try:
        print(f"[download] Fetching {DRUGAGE_URL}")
        urllib.request.urlretrieve(DRUGAGE_URL, zip_path)
        with zipfile.ZipFile(zip_path) as z:
            for name in z.namelist():
                if name.lower().endswith(".csv"):
                    z.extract(name, RAW_DIR)
                    src = os.path.join(RAW_DIR, name)
                    os.replace(src, csv_path)
                    print(f"[download] Extracted to {csv_path}")
                    return csv_path
    except Exception as e:
        print(f"[download] Network unavailable ({e}). Using existing CSV if present.")
    return csv_path


def parse():
    csv_path = os.path.join(PROCESSED_DIR, "drugage_dataset.csv")
    if not os.path.exists(csv_path):
        raise FileNotFoundError(f"Missing {csv_path}. Run --download first.")
    
    df = pd.read_csv(csv_path)
    print(f"[parse] Loaded DrugAge: {df.shape[0]} rows")
    
    def classify(x):
        if pd.isna(x):
            return "No Significant Effect"
        if x > 0:
            return "Lifespan Extension"
        if x < 0:
            return "Lifespan Reduction"
        return "No Significant Effect"
    df["effect"] = df["avg_lifespan_change_percent"].apply(classify)
    df["compound_name"] = df["compound_name"].astype(str).str.strip()
    df["species"] = df["species"].astype(str).str.strip()
    
    # Save AgeingProperty TSV
    ageing_tsv = pd.DataFrame(AGEING_PROPERTIES)
    ageing_tsv["source"] = SOURCE_LABEL
    ageing_path = os.path.join(PROCESSED_DIR, "ageing_properties.tsv")
    ageing_tsv.to_csv(ageing_path, sep="\t", index=False)
    print(f"[parse] Saved {len(ageing_tsv)} AgeingProperty rows -> {ageing_path}")
    
    # Save drug-aging associations
    assoc_cols = ["compound_name", "species", "strain", "dosage",
                  "avg_lifespan_change_percent", "avg_lifespan_significance",
                  "max_lifespan_change_percent", "max_lifespan_significance",
                  "gender", "ITP", "pubmed_id", "effect"]
    assoc_df = df[assoc_cols].copy()
    assoc_path = os.path.join(PROCESSED_DIR, "drug_aging_associations.tsv")
    assoc_df.to_csv(assoc_path, sep="\t", index=False)
    print(f"[parse] Saved {len(assoc_df)} drug-aging associations -> {assoc_path}")
    return ageing_tsv, assoc_df


def _safe(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    return str(v)


def load():
    driver = GraphDatabase.driver(MEMGRAPH_URI, auth=None)
    
    ageing_path = os.path.join(PROCESSED_DIR, "ageing_properties.tsv")
    assoc_path = os.path.join(PROCESSED_DIR, "drug_aging_associations.tsv")
    if not (os.path.exists(ageing_path) and os.path.exists(assoc_path)):
        raise FileNotFoundError("Run --parse before --load")
    
    ageing_df = pd.read_csv(ageing_path, sep="\t")
    assoc_df = pd.read_csv(assoc_path, sep="\t")
    
    try:
        with driver.session() as session:
            # Create index for AgeingProperty
            session.run("CREATE INDEX ON :AgeingProperty(propertyName)")
            print("[load] Index ensured on :AgeingProperty(propertyName)")
    except Exception as e:
        print(f"[load] Index info: {e}")
    
    # Snapshot counts
    with driver.session() as session:
        before_ap = session.run("MATCH (a:AgeingProperty) RETURN count(a) AS c").single()["c"]
        before_assoc = session.run(
            "MATCH (g:Gene)-[r:associatedWithAging]->(:AgeingProperty) RETURN count(r) AS c"
        ).single()["c"]
    
    # 1) MERGE AgeingProperty nodes
    with driver.session() as session:
        for prop in AGEING_PROPERTIES:
            session.run("""
                MERGE (a:AgeingProperty {propertyName: $propertyName})
                SET a.description = $description,
                    a.source = $source
            """, propertyName=prop["propertyName"],
                 description=prop["description"],
                 source=SOURCE_LABEL)
        print(f"[load] MERGED {len(AGEING_PROPERTIES)} AgeingProperty nodes")
    
    # 2) Build Gene->AgeingProperty edges via existing drug-target/binding relationships.
    #    MATCH-only on Gene anchors (geneSymbol). Use compound_name to match Drug.
    #    Aggregate by (gene, effect) pair to avoid heavy combinatorics, with source=DrugAge.
    with driver.session() as session:
        records = []
        for _, row in assoc_df.iterrows():
            records.append({
                "compoundName": _safe(row["compound_name"]),
                "effect": _safe(row["effect"]),
                "species": _safe(row["species"]),
                "pubmedId": _safe(row["pubmed_id"]),
                "avgLifespanChange": float(row["avg_lifespan_change_percent"])
                    if pd.notna(row["avg_lifespan_change_percent"]) else None,
            })
        
        # Batch process: for each compound name, link compound's gene targets to the ageing property
        BATCH = 200
        total_created = 0
        for i in range(0, len(records), BATCH):
            chunk = records[i:i+BATCH]
            res = session.run("""
                UNWIND $rows AS row
                MATCH (d:Drug {commonName: row.compoundName})
                MATCH (d)-[:drugTargetsGene|drugBindsGene]->(g:Gene)
                MATCH (a:AgeingProperty {propertyName: row.effect})
                MERGE (g)-[r:associatedWithAging {source: $source, drug: row.compoundName, species: row.species}]->(a)
                SET r.pubmedId = row.pubmedId,
                    r.avgLifespanChangePct = row.avgLifespanChange
                RETURN count(r) AS cnt
            """, rows=chunk, source=SOURCE_LABEL).single()
        print(f"[load] Processed {len(records)} drug-aging records (Gene->AgeingProperty via drug targets)")
    
    # Final counts
    with driver.session() as session:
        after_ap = session.run("MATCH (a:AgeingProperty) RETURN count(a) AS c").single()["c"]
        after_assoc = session.run(
            "MATCH (g:Gene)-[r:associatedWithAging]->(:AgeingProperty) RETURN count(r) AS c"
        ).single()["c"]
        total_assoc = session.run(
            "MATCH ()-[r:associatedWithAging]->() RETURN count(r) AS c"
        ).single()["c"]
    
    print(f"[load] AgeingProperty: {before_ap} -> {after_ap} (Δ={after_ap-before_ap})")
    print(f"[load] Gene->AgeingProperty: {before_assoc} -> {after_assoc} (Δ={after_assoc-before_assoc})")
    print(f"[load] Total associatedWithAging edges: {total_assoc}")
    driver.close()
    return {
        "ageing_property_delta": after_ap - before_ap,
        "assoc_delta": after_assoc - before_assoc,
        "ageing_property_count": after_ap,
        "gene_assoc_count": after_assoc,
        "total_assoc_count": total_assoc,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--download", action="store_true")
    ap.add_argument("--parse", action="store_true")
    ap.add_argument("--load", action="store_true")
    ap.add_argument("--all", action="store_true")
    args = ap.parse_args()
    if args.all:
        download(); parse(); load()
    else:
        if args.download: download()
        if args.parse: parse()
        if args.load: load()
        if not any([args.download, args.parse, args.load]):
            ap.print_help()


if __name__ == "__main__":
    main()
