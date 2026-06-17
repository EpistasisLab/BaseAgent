#!/usr/bin/env python3
"""
AnAge Parser for CardioKB
Downloads, parses, and loads AnAge data (Species nodes + geneInSpecies edges)
into Memgraph.

Usage:
  python anage_parser.py --download
  python anage_parser.py --parse
  python anage_parser.py --load
  python anage_parser.py --all
"""

import argparse
import os
import sys
import zipfile
import urllib.request
import pandas as pd
from neo4j import GraphDatabase

ANAGE_URL = "https://genomics.senescence.info/species/dataset.zip"
RAW_DIR = "./data/raw/anage"
PROCESSED_DIR = "./data/processed/anage"
MEMGRAPH_URI = "bolt://localhost:7688"
SOURCE_LABEL = "NCBI Gene"  # for geneInSpecies edges (per task spec)
ANAGE_SOURCE = "AnAge"      # for Species node provenance


def download():
    os.makedirs(RAW_DIR, exist_ok=True)
    os.makedirs(PROCESSED_DIR, exist_ok=True)
    out_csv = os.path.join(PROCESSED_DIR, "anage_dataset.csv")
    if os.path.exists(out_csv):
        print(f"[download] AnAge file already exists: {out_csv}")
        return out_csv
    try:
        zip_path = os.path.join(RAW_DIR, "dataset.zip")
        print(f"[download] Fetching {ANAGE_URL}")
        urllib.request.urlretrieve(ANAGE_URL, zip_path)
        with zipfile.ZipFile(zip_path) as z:
            for name in z.namelist():
                if name.lower().endswith((".txt", ".csv", ".tsv")):
                    z.extract(name, RAW_DIR)
                    os.replace(os.path.join(RAW_DIR, name), out_csv)
                    print(f"[download] Extracted to {out_csv}")
                    return out_csv
    except Exception as e:
        print(f"[download] Network unavailable ({e}). Using existing CSV if present.")
    return out_csv


def parse():
    in_path = os.path.join(PROCESSED_DIR, "anage_dataset.csv")
    if not os.path.exists(in_path):
        raise FileNotFoundError(f"Missing {in_path}. Run --download first.")
    
    # Try common separators
    try:
        df = pd.read_csv(in_path, sep="\t", on_bad_lines="skip")
        if df.shape[1] < 5:
            df = pd.read_csv(in_path, on_bad_lines="skip")
    except Exception:
        df = pd.read_csv(in_path, on_bad_lines="skip")
    print(f"[parse] Loaded AnAge: {df.shape[0]} rows, {df.shape[1]} columns")
    
    df["speciesName"] = df["Genus"].astype(str).str.strip() + " " + df["Species"].astype(str).str.strip()
    
    species_df = pd.DataFrame({
        "hagrid": df.get("HAGRID"),
        "speciesName": df["speciesName"],
        "commonName": df.get("Common name"),
        "kingdom": df.get("Kingdom"),
        "phylum": df.get("Phylum"),
        "class": df.get("Class"),
        "order": df.get("Order"),
        "family": df.get("Family"),
        "genus": df.get("Genus"),
        "species": df.get("Species"),
        "maxLongevityYrs": df.get("Maximum longevity (yrs)"),
        "bodyMassG": df.get("Body mass (g)"),
        "adultWeightG": df.get("Adult weight (g)"),
        "metabolicRateW": df.get("Metabolic rate (W)"),
        "dataQuality": df.get("Data quality"),
        "specimenOrigin": df.get("Specimen origin"),
        "sampleSize": df.get("Sample size"),
    })
    species_path = os.path.join(PROCESSED_DIR, "species_nodes.tsv")
    species_df.to_csv(species_path, sep="\t", index=False)
    print(f"[parse] Saved {len(species_df)} Species rows -> {species_path}")
    
    # Build gene_species_associations using NCBI Gene mapping.
    # Strategy: For Homo sapiens, link all existing Gene anchors to Homo sapiens.
    # The list of geneSymbols will be resolved at --load time via MATCH on Gene.
    # Here we save a placeholder TSV with the canonical mapping (human genes).
    gs_path = os.path.join(PROCESSED_DIR, "gene_species_associations.tsv")
    if not os.path.exists(gs_path):
        pd.DataFrame(columns=["geneSymbol", "speciesName", "source"]).to_csv(
            gs_path, sep="\t", index=False)
    print(f"[parse] gene_species_associations TSV ready at {gs_path}")
    return species_df


def _to_float(v):
    try:
        return float(v) if pd.notna(v) else None
    except Exception:
        return None


def _to_str(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    return str(v).strip()


def load():
    driver = GraphDatabase.driver(MEMGRAPH_URI, auth=None)
    species_path = os.path.join(PROCESSED_DIR, "species_nodes.tsv")
    if not os.path.exists(species_path):
        raise FileNotFoundError("Run --parse before --load")
    species_df = pd.read_csv(species_path, sep="\t")
    
    # Create indexes (idempotent)
    try:
        with driver.session() as session:
            session.run("CREATE INDEX ON :Species(speciesName)")
            print("[load] Index ensured on :Species(speciesName)")
    except Exception as e:
        print(f"[load] Index info: {e}")
    
    # Snapshot counts
    with driver.session() as session:
        before_species = session.run("MATCH (s:Species) RETURN count(s) AS c").single()["c"]
        before_edges = session.run(
            "MATCH ()-[r:geneInSpecies]->() RETURN count(r) AS c"
        ).single()["c"]
    
    # MERGE Species nodes
    records = []
    for _, row in species_df.iterrows():
        records.append({
            "speciesName": _to_str(row.get("speciesName")),
            "commonName": _to_str(row.get("commonName")),
            "kingdom": _to_str(row.get("kingdom")),
            "phylum": _to_str(row.get("phylum")),
            "class": _to_str(row.get("class")),
            "order": _to_str(row.get("order")),
            "family": _to_str(row.get("family")),
            "genus": _to_str(row.get("genus")),
            "maxLongevityYrs": _to_float(row.get("maxLongevityYrs")),
            "bodyMassG": _to_float(row.get("bodyMassG")),
            "adultWeightG": _to_float(row.get("adultWeightG")),
            "metabolicRateW": _to_float(row.get("metabolicRateW")),
            "dataQuality": _to_str(row.get("dataQuality")),
            "specimenOrigin": _to_str(row.get("specimenOrigin")),
            "hagrid": _to_str(row.get("hagrid")),
        })
    
    BATCH = 500
    with driver.session() as session:
        for i in range(0, len(records), BATCH):
            chunk = records[i:i+BATCH]
            session.run("""
                UNWIND $rows AS row
                MERGE (s:Species {speciesName: row.speciesName})
                SET s.commonName = coalesce(row.commonName, s.commonName),
                    s.kingdom = row.kingdom,
                    s.phylum = row.phylum,
                    s.class = row.class,
                    s.order = row.order,
                    s.family = row.family,
                    s.genus = row.genus,
                    s.maxLongevityYrs = row.maxLongevityYrs,
                    s.bodyMassG = row.bodyMassG,
                    s.adultWeightG = row.adultWeightG,
                    s.metabolicRateW = row.metabolicRateW,
                    s.dataQuality = row.dataQuality,
                    s.specimenOrigin = row.specimenOrigin,
                    s.hagrid = row.hagrid,
                    s.anageSource = $anageSource
            """, rows=chunk, anageSource=ANAGE_SOURCE)
        print(f"[load] MERGED {len(records)} Species nodes")
    
    # Create geneInSpecies edges: Gene -> Species (Homo sapiens) using NCBI Gene as source.
    # MATCH-only on Gene anchors.
    with driver.session() as session:
        session.run("""
            MATCH (s:Species {speciesName: 'Homo sapiens'})
            SET s.commonName = coalesce(s.commonName, 'human'),
                s.scientificName = 'Homo sapiens'
        """)
        res = session.run("""
            MATCH (g:Gene)
            MATCH (s:Species {speciesName: 'Homo sapiens'})
            MERGE (g)-[r:geneInSpecies {source: $source}]->(s)
            RETURN count(r) AS c
        """, source=SOURCE_LABEL).single()
        print(f"[load] geneInSpecies merge completed; matched {res['c']} edges")
    
    # Persist the resolved gene->species TSV (Homo sapiens)
    with driver.session() as session:
        rows = session.run("""
            MATCH (g:Gene)-[r:geneInSpecies]->(s:Species {speciesName: 'Homo sapiens'})
            RETURN g.geneSymbol AS geneSymbol, s.speciesName AS speciesName, r.source AS source
        """).data()
    gs_df = pd.DataFrame(rows)
    gs_path = os.path.join(PROCESSED_DIR, "gene_species_associations.tsv")
    gs_df.to_csv(gs_path, sep="\t", index=False)
    print(f"[load] Saved {len(gs_df)} gene->species associations -> {gs_path}")
    
    # Final counts
    with driver.session() as session:
        after_species = session.run("MATCH (s:Species) RETURN count(s) AS c").single()["c"]
        after_edges = session.run(
            "MATCH ()-[r:geneInSpecies]->() RETURN count(r) AS c"
        ).single()["c"]
    
    print(f"[load] Species: {before_species} -> {after_species} (Δ={after_species-before_species})")
    print(f"[load] geneInSpecies: {before_edges} -> {after_edges} (Δ={after_edges-before_edges})")
    driver.close()
    return {
        "species_delta": after_species - before_species,
        "edge_delta": after_edges - before_edges,
        "species_count": after_species,
        "edge_count": after_edges,
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
