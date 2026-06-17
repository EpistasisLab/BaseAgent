#!/usr/bin/env python3
"""
AnAge Parser for CardioKB
Processes AnAge dataset and loads species longevity data into Memgraph
"""

import pandas as pd
import os
from neo4j import GraphDatabase

# Config
ANAGE_CSV = "./data/processed/anage/anage_dataset.csv"
OUTPUT_DIR = "./data/processed/anage/"
MEMGRAPH_URI = "bolt://localhost:7688"


def load_anage_data():
    """Load and preprocess AnAge dataset."""
    df = pd.read_csv(ANAGE_CSV, sep="\t", on_bad_lines="skip")
    print(f"Loaded AnAge: {df.shape[0]} rows, {df.shape[1]} columns")
    
    # Create speciesName as "Genus species"
    df["speciesName"] = df["Genus"].str.strip() + " " + df["Species"].str.strip()
    df["commonName_anage"] = df["Common name"].str.strip()
    
    print(f"Unique species: {df['speciesName'].nunique()}")
    print(f"Species with longevity data: {df['Maximum longevity (yrs)'].notna().sum()}")
    return df


def save_processed_files(df):
    """Save processed TSV files."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    # Species nodes TSV
    species_df = df[[
        "HAGRID", "speciesName", "Common name", "Kingdom", "Phylum", "Class",
        "Order", "Family", "Genus", "Species", "Maximum longevity (yrs)",
        "Body mass (g)", "Adult weight (g)", "Metabolic rate (W)",
        "Data quality", "Specimen origin", "Sample size"
    ]].copy()
    species_df.columns = [
        "hagrid", "speciesName", "commonName", "kingdom", "phylum", "class",
        "order", "family", "genus", "species", "maxLongevityYrs",
        "bodyMassG", "adultWeightG", "metabolicRateW",
        "dataQuality", "specimenOrigin", "sampleSize"
    ]
    species_df.to_csv(f"{OUTPUT_DIR}species_nodes.tsv", sep="\t", index=False)
    print(f"Saved {len(species_df)} species nodes to TSV")
    return species_df


def load_to_memgraph(df, driver):
    """Load AnAge species data into Memgraph."""
    
    # 1. Update existing Homo sapiens node
    print("\nUpdating Homo sapiens Species node...")
    with driver.session() as session:
        homo = df[df["speciesName"] == "Homo sapiens"].iloc[0]
        session.run("""
            MATCH (s:Species {scientificName: "Homo sapiens"})
            SET s.speciesName = "Homo sapiens",
                s.maxLongevityYrs = $maxLongevity,
                s.bodyMassG = $bodyMass,
                s.kingdom = $kingdom,
                s.phylum = $phylum,
                s.class = $class,
                s.order = $order,
                s.family = $family,
                s.genus = $genus,
                s.dataQuality = $dataQuality,
                s.specimenOrigin = $specimenOrigin,
                s.hagrid = $hagrid,
                s.anageSource = "AnAge"
        """, {
            "maxLongevity": float(homo["Maximum longevity (yrs)"]) if pd.notna(homo["Maximum longevity (yrs)"]) else None,
            "bodyMass": float(homo["Body mass (g)"]) if pd.notna(homo["Body mass (g)"]) else None,
            "kingdom": str(homo["Kingdom"]) if pd.notna(homo["Kingdom"]) else None,
            "phylum": str(homo["Phylum"]) if pd.notna(homo["Phylum"]) else None,
            "class": str(homo["Class"]) if pd.notna(homo["Class"]) else None,
            "order": str(homo["Order"]) if pd.notna(homo["Order"]) else None,
            "family": str(homo["Family"]) if pd.notna(homo["Family"]) else None,
            "genus": str(homo["Genus"]) if pd.notna(homo["Genus"]) else None,
            "dataQuality": str(homo["Data quality"]) if pd.notna(homo["Data quality"]) else None,
            "specimenOrigin": str(homo["Specimen origin"]) if pd.notna(homo["Specimen origin"]) else None,
            "hagrid": str(int(homo["HAGRID"])) if pd.notna(homo["HAGRID"]) else None
        })
        print("  Homo sapiens node updated")
    
    # 2. Create all Species nodes
    print("\nCreating Species nodes from AnAge...")
    species_batch = []
    for _, row in df.iterrows():
        species_name = f"{str(row['Genus']).strip()} {str(row['Species']).strip()}"
        record = {
            "speciesName": species_name,
            "commonName": str(row["Common name"]).strip() if pd.notna(row["Common name"]) else None,
            "kingdom": str(row["Kingdom"]).strip() if pd.notna(row["Kingdom"]) else None,
            "phylum": str(row["Phylum"]).strip() if pd.notna(row["Phylum"]) else None,
            "class": str(row["Class"]).strip() if pd.notna(row["Class"]) else None,
            "order": str(row["Order"]).strip() if pd.notna(row["Order"]) else None,
            "family": str(row["Family"]).strip() if pd.notna(row["Family"]) else None,
            "genus": str(row["Genus"]).strip() if pd.notna(row["Genus"]) else None,
            "maxLongevityYrs": float(row["Maximum longevity (yrs)"]) if pd.notna(row["Maximum longevity (yrs)"]) else None,
            "bodyMassG": float(row["Body mass (g)"]) if pd.notna(row["Body mass (g)"]) else None,
            "adultWeightG": float(row["Adult weight (g)"]) if pd.notna(row["Adult weight (g)"]) else None,
            "metabolicRateW": float(row["Metabolic rate (W)"]) if pd.notna(row["Metabolic rate (W)"]) else None,
            "dataQuality": str(row["Data quality"]).strip() if pd.notna(row["Data quality"]) else None,
            "specimenOrigin": str(row["Specimen origin"]).strip() if pd.notna(row["Specimen origin"]) else None,
            "hagrid": str(int(row["HAGRID"])) if pd.notna(row["HAGRID"]) else None,
            "anageSource": "AnAge"
        }
        species_batch.append(record)
    
    BATCH_SIZE = 500
    with driver.session() as session:
        for i in range(0, len(species_batch), BATCH_SIZE):
            chunk = species_batch[i:i+BATCH_SIZE]
            session.run("""
                UNWIND $batch AS row
                MERGE (s:Species {speciesName: row.speciesName})
                SET s.commonName = CASE WHEN s.commonName IS NULL THEN row.commonName ELSE s.commonName END,
                    s.kingdom = row.kingdom, s.phylum = row.phylum,
                    s.class = row.class, s.order = row.order,
                    s.family = row.family, s.genus = row.genus,
                    s.maxLongevityYrs = row.maxLongevityYrs,
                    s.bodyMassG = row.bodyMassG, s.adultWeightG = row.adultWeightG,
                    s.metabolicRateW = row.metabolicRateW,
                    s.dataQuality = row.dataQuality, s.specimenOrigin = row.specimenOrigin,
                    s.hagrid = row.hagrid, s.anageSource = row.anageSource
            """, batch=chunk)
            print(f"  Loaded {min(i+BATCH_SIZE, len(species_batch))}/{len(species_batch)} species")
    
    # 3. Create geneInSpecies edges for all Gene nodes -> Homo sapiens
    print("\nCreating geneInSpecies edges (Gene -> Homo sapiens)...")
    with driver.session() as session:
        result = session.run("""
            MATCH (g:Gene)
            WHERE NOT (g)-[:geneInSpecies]->()
            MATCH (s:Species {speciesName: "Homo sapiens"})
            MERGE (g)-[r:geneInSpecies {source: "NCBIGene"}]->(s)
            RETURN count(r) AS created
        """)
        created = result.single()["created"]
        print(f"  Created {created} new geneInSpecies edges")
        
        result = session.run("MATCH ()-[r:geneInSpecies]->() RETURN count(r) AS count")
        print(f"  Total geneInSpecies edges: {result.single()['count']}")
    
    # Report counts
    with driver.session() as session:
        result = session.run("MATCH (s:Species) RETURN count(s) AS count")
        print(f"\nTotal Species nodes: {result.single()['count']}")


if __name__ == "__main__":
    print("=== AnAge Parser ===")
    df = load_anage_data()
    save_processed_files(df)
    
    driver = GraphDatabase.driver(MEMGRAPH_URI, auth=None)
    try:
        load_to_memgraph(df, driver)
        print("\nAnAge loading complete!")
    finally:
        driver.close()
