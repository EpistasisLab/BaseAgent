#!/usr/bin/env python3
"""
DrugAge Parser for CardioKB
Processes DrugAge dataset and loads aging associations into Memgraph
"""

import pandas as pd
import os
import sys
from neo4j import GraphDatabase

# Config
DRUGAGE_CSV = "./data/processed/drugage/drugage_dataset.csv"
OUTPUT_DIR = "./data/processed/drugage/"
MEMGRAPH_URI = "bolt://localhost:7688"

def load_drugage_data():
    """Load and preprocess DrugAge dataset."""
    df = pd.read_csv(DRUGAGE_CSV)
    print(f"Loaded DrugAge: {df.shape[0]} rows, {df.shape[1]} columns")
    
    # Categorize lifespan effects
    df["effect"] = df["avg_lifespan_change_percent"].apply(
        lambda x: "Lifespan Extension" if pd.notna(x) and x > 0
        else ("Lifespan Reduction" if pd.notna(x) and x < 0
        else "No Significant Effect")
    )
    
    # Clean compound names
    df["compound_name"] = df["compound_name"].str.strip()
    df["species"] = df["species"].str.strip()
    
    return df


def save_processed_files(df):
    """Save processed TSV files."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    # AgeingProperty nodes
    ageing_props = pd.DataFrame({
        "propertyName": ["Lifespan Extension", "Lifespan Reduction", "No Significant Effect"],
        "description": [
            "Compound extends average lifespan in model organism",
            "Compound reduces average lifespan in model organism",
            "Compound has no significant effect on lifespan"
        ],
        "source": ["DrugAge"] * 3
    })
    ageing_props.to_csv(f"{OUTPUT_DIR}ageing_properties.tsv", sep="\t", index=False)
    print(f"Saved {len(ageing_props)} AgeingProperty nodes to TSV")
    
    # Drug-aging associations
    associations = df[[
        "compound_name", "species", "strain", "dosage",
        "avg_lifespan_change_percent", "avg_lifespan_significance",
        "max_lifespan_change_percent", "max_lifespan_significance",
        "gender", "ITP", "pubmed_id", "effect"
    ]].copy()
    associations.to_csv(f"{OUTPUT_DIR}drug_aging_associations.tsv", sep="\t", index=False)
    print(f"Saved {len(associations)} drug-aging associations to TSV")
    
    return ageing_props, associations


def load_to_memgraph(df, driver):
    """Load DrugAge data into Memgraph."""
    
    with driver.session() as session:
        # 1. Create AgeingProperty nodes
        print("\nCreating AgeingProperty nodes...")
        ageing_properties = [
            {"propertyName": "Lifespan Extension", 
             "description": "Compound extends average lifespan in model organism"},
            {"propertyName": "Lifespan Reduction", 
             "description": "Compound reduces average lifespan in model organism"},
            {"propertyName": "No Significant Effect", 
             "description": "Compound has no significant effect on lifespan"}
        ]
        
        for prop in ageing_properties:
            session.run("""
                MERGE (a:AgeingProperty {propertyName: $propertyName})
                SET a.description = $description,
                    a.source = "DrugAge"
            """, prop)
        print(f"  Created/merged {len(ageing_properties)} AgeingProperty nodes")
        
        # 2. Create Drug nodes (MERGE) and associatedWithAging edges
        print("\nCreating Drug nodes and associatedWithAging edges...")
        
        batch = []
        for _, row in df.iterrows():
            record = {
                "compoundName": row["compound_name"],
                "species": str(row["species"]) if pd.notna(row["species"]) else "",
                "strain": str(row["strain"]) if pd.notna(row["strain"]) else "",
                "dosage": str(row["dosage"]) if pd.notna(row["dosage"]) else "",
                "avgLifespanChange": float(row["avg_lifespan_change_percent"]) if pd.notna(row["avg_lifespan_change_percent"]) else None,
                "avgLifespanSignificance": str(row["avg_lifespan_significance"]) if pd.notna(row["avg_lifespan_significance"]) else "",
                "maxLifespanChange": float(row["max_lifespan_change_percent"]) if pd.notna(row["max_lifespan_change_percent"]) else None,
                "gender": str(row["gender"]) if pd.notna(row["gender"]) else "",
                "itp": str(row["ITP"]) if pd.notna(row["ITP"]) else "",
                "pubmedId": str(row["pubmed_id"]) if pd.notna(row["pubmed_id"]) else "",
                "effect": row["effect"]
            }
            batch.append(record)
            
            if len(batch) >= 500:
                session.run("""
                    UNWIND $batch AS row
                    MERGE (d:Drug {commonName: row.compoundName})
                    WITH d, row
                    MATCH (a:AgeingProperty {propertyName: row.effect})
                    MERGE (d)-[r:associatedWithAging {
                        source: "DrugAge",
                        species: row.species,
                        gender: row.gender,
                        pubmedId: row.pubmedId
                    }]->(a)
                    SET r.avgLifespanChangePct = row.avgLifespanChange,
                        r.avgLifespanSignificance = row.avgLifespanSignificance,
                        r.maxLifespanChangePct = row.maxLifespanChange,
                        r.dosage = row.dosage,
                        r.strain = row.strain,
                        r.itp = row.itp
                """, batch=batch)
                batch = []
        
        if batch:
            session.run("""
                UNWIND $batch AS row
                MERGE (d:Drug {commonName: row.compoundName})
                WITH d, row
                MATCH (a:AgeingProperty {propertyName: row.effect})
                MERGE (d)-[r:associatedWithAging {
                    source: "DrugAge",
                    species: row.species,
                    gender: row.gender,
                    pubmedId: row.pubmedId
                }]->(a)
                SET r.avgLifespanChangePct = row.avgLifespanChange,
                    r.avgLifespanSignificance = row.avgLifespanSignificance,
                    r.maxLifespanChangePct = row.maxLifespanChange,
                    r.dosage = row.dosage,
                    r.strain = row.strain,
                    r.itp = row.itp
            """, batch=batch)
        
        # Count results
        result = session.run("MATCH (a:AgeingProperty) RETURN count(a) AS count")
        print(f"  Total AgeingProperty nodes: {result.single()['count']}")
        
        result = session.run("MATCH ()-[r:associatedWithAging]->() RETURN count(r) AS count")
        print(f"  Total associatedWithAging edges: {result.single()['count']}")




def create_gene_aging_edges(driver):
    """Create Gene -> AgeingProperty edges via drug-gene targets."""
    print("\nCreating Gene -> AgeingProperty edges (via drug targets)...")
    with driver.session() as session:
        result = session.run("""
            MATCH (d:Drug)-[r:associatedWithAging]->(a:AgeingProperty)
            MATCH (d)-[:drugTargetsGene]->(g:Gene)
            MERGE (g)-[ga:associatedWithAging {
                source: "DrugAge",
                drug: d.commonName
            }]->(a)
            SET ga.species = r.species,
                ga.avgLifespanChangePct = r.avgLifespanChangePct,
                ga.gender = r.gender,
                ga.pubmedId = r.pubmedId
            RETURN count(ga) AS created
        """)
        created = result.single()["created"]
        print(f"  Created {created} Gene->AgeingProperty edges")
    return created

if __name__ == "__main__":
    print("=== DrugAge Parser ===")
    df = load_drugage_data()
    save_processed_files(df)
    
    driver = GraphDatabase.driver(MEMGRAPH_URI, auth=None)
    try:
        load_to_memgraph(df, driver)
        create_gene_aging_edges(driver)
        print("\nDrugAge loading complete!")
    finally:
        driver.close()
