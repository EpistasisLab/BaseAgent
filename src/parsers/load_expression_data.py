#!/usr/bin/env python3
"""
Expression Data Loader for CardioKB
Loads Bgee, Jensen TISSUES, and LINCS L1000 expression data into Neo4j/Memgraph.
"""

import pandas as pd
from neo4j import GraphDatabase
import time

DB_URI = "bolt://localhost:7688"
BATCH_SIZE = 500


def get_driver():
    return GraphDatabase.driver(DB_URI, auth=None)


def load_bgee_overexpression(driver, tsv_file: str):
    """Load bodyPartOverexpressesGene edges from Bgee."""
    df = pd.read_csv(tsv_file, sep="\t")
    print(f"Loading {len(df):,} bodyPartOverexpressesGene edges...")

    query = """
    UNWIND $rows AS row
    MATCH (b:BodyPart {xrefUberon: row.xrefUberon})
    MATCH (g:Gene {geneSymbol: row.geneSymbol})
    MERGE (b)-[r:bodyPartOverexpressesGene {source: "Bgee"}]->(g)
    ON CREATE SET r.expressionScore = row.expressionScore,
                  r.expressionRank  = row.expressionRank,
                  r.callQuality     = row.callQuality
    """

    count = 0
    with driver.session() as session:
        for i in range(0, len(df), BATCH_SIZE):
            batch = df.iloc[i:i+BATCH_SIZE]
            rows = [
                {
                    "xrefUberon":    row["xrefUberon"],
                    "geneSymbol":    row["geneSymbol"],
                    "expressionScore": float(row["Expression score"]),
                    "expressionRank":  float(row["Expression rank"]) if pd.notna(row["Expression rank"]) else None,
                    "callQuality":     row["Call quality"],
                }
                for _, row in batch.iterrows()
            ]
            session.run(query, rows=rows)
            count += len(rows)
            if count % 10000 == 0:
                print(f"  Loaded {count:,}/{len(df):,}")
    print(f"  Done: {count:,} bodyPartOverexpressesGene edges")
    return count


def load_bgee_underexpression(driver, tsv_file: str):
    """Load bodyPartUnderexpressesGene edges from Bgee."""
    df = pd.read_csv(tsv_file, sep="\t")
    print(f"Loading {len(df):,} bodyPartUnderexpressesGene edges...")

    query = """
    UNWIND $rows AS row
    MATCH (b:BodyPart {xrefUberon: row.xrefUberon})
    MATCH (g:Gene {geneSymbol: row.geneSymbol})
    MERGE (b)-[r:bodyPartUnderexpressesGene {source: "Bgee"}]->(g)
    ON CREATE SET r.expressionScore = row.expressionScore,
                  r.expressionRank  = row.expressionRank,
                  r.callQuality     = row.callQuality
    """

    count = 0
    with driver.session() as session:
        for i in range(0, len(df), BATCH_SIZE):
            batch = df.iloc[i:i+BATCH_SIZE]
            rows = [
                {
                    "xrefUberon":    row["xrefUberon"],
                    "geneSymbol":    row["geneSymbol"],
                    "expressionScore": float(row["Expression score"]),
                    "expressionRank":  float(row["Expression rank"]) if pd.notna(row["Expression rank"]) else None,
                    "callQuality":     row["Call quality"],
                }
                for _, row in batch.iterrows()
            ]
            session.run(query, rows=rows)
            count += len(rows)
            if count % 5000 == 0:
                print(f"  Loaded {count:,}/{len(df):,}")
    print(f"  Done: {count:,} bodyPartUnderexpressesGene edges")
    return count


def load_jensen_tissues(driver, tsv_file: str):
    """Load geneExpressedInBodyPart edges from Jensen TISSUES."""
    df = pd.read_csv(tsv_file, sep="\t")
    print(f"Loading {len(df):,} geneExpressedInBodyPart (Jensen TISSUES) edges...")

    query = """
    UNWIND $rows AS row
    MATCH (g:Gene {geneSymbol: row.geneSymbol})
    MATCH (b:BodyPart {xrefUberon: row.xrefUberon})
    MERGE (g)-[r:geneExpressedInBodyPart {source: "Jensen TISSUES"}]->(b)
    ON CREATE SET r.confidence = row.confidence
    """

    count = 0
    with driver.session() as session:
        for i in range(0, len(df), BATCH_SIZE):
            batch = df.iloc[i:i+BATCH_SIZE]
            rows = [
                {
                    "geneSymbol": row["geneSymbol"],
                    "xrefUberon": row["xrefUberon"],
                    "confidence": float(row["confidence"]),
                }
                for _, row in batch.iterrows()
            ]
            session.run(query, rows=rows)
            count += len(rows)
            if count % 1000 == 0:
                print(f"  Loaded {count:,}/{len(df):,}")
    print(f"  Done: {count:,} geneExpressedInBodyPart edges")
    return count


def load_lincs_upregulation(driver, tsv_file: str):
    """Load compoundUpregulatesGene edges from LINCS L1000."""
    df = pd.read_csv(tsv_file, sep="\t")
    print(f"Loading {len(df):,} compoundUpregulatesGene edges...")

    query = """
    UNWIND $rows AS row
    MATCH (d:Drug {commonName: row.commonName})
    MATCH (g:Gene {geneSymbol: row.geneSymbol})
    MERGE (d)-[r:compoundUpregulatesGene {source: "LINCS L1000"}]->(g)
    """

    count = 0
    with driver.session() as session:
        for i in range(0, len(df), BATCH_SIZE):
            batch = df.iloc[i:i+BATCH_SIZE]
            rows = batch.to_dict("records")
            session.run(query, rows=rows)
            count += len(rows)
            if count % 1000 == 0:
                print(f"  Loaded {count:,}/{len(df):,}")
    print(f"  Done: {count:,} compoundUpregulatesGene edges")
    return count


def load_lincs_downregulation(driver, tsv_file: str):
    """Load compoundDownregulatesGene edges from LINCS L1000."""
    df = pd.read_csv(tsv_file, sep="\t")
    print(f"Loading {len(df):,} compoundDownregulatesGene edges...")

    query = """
    UNWIND $rows AS row
    MATCH (d:Drug {commonName: row.commonName})
    MATCH (g:Gene {geneSymbol: row.geneSymbol})
    MERGE (d)-[r:compoundDownregulatesGene {source: "LINCS L1000"}]->(g)
    """

    count = 0
    with driver.session() as session:
        for i in range(0, len(df), BATCH_SIZE):
            batch = df.iloc[i:i+BATCH_SIZE]
            rows = batch.to_dict("records")
            session.run(query, rows=rows)
            count += len(rows)
            if count % 1000 == 0:
                print(f"  Loaded {count:,}/{len(df):,}")
    print(f"  Done: {count:,} compoundDownregulatesGene edges")
    return count




def load_ctd_upregulation(driver, tsv_file: str):
    """Load compoundUpregulatesGene edges from CTD."""
    df = pd.read_csv(tsv_file, sep="\t")
    print(f"Loading {len(df):,} compoundUpregulatesGene (CTD) edges...")
    query = """
    UNWIND $rows AS row
    MATCH (d:Drug {commonName: row.commonName})
    MATCH (g:Gene {geneSymbol: row.geneSymbol})
    MERGE (d)-[r:compoundUpregulatesGene {source: "CTD"}]->(g)
    """
    count = 0
    with driver.session() as session:
        for i in range(0, len(df), BATCH_SIZE):
            rows = df.iloc[i:i+BATCH_SIZE].to_dict("records")
            session.run(query, rows=rows)
            count += len(rows)
    print(f"  Done: {count:,} compoundUpregulatesGene (CTD) edges")
    return count


def load_ctd_downregulation(driver, tsv_file: str):
    """Load compoundDownregulatesGene edges from CTD."""
    df = pd.read_csv(tsv_file, sep="\t")
    print(f"Loading {len(df):,} compoundDownregulatesGene (CTD) edges...")
    query = """
    UNWIND $rows AS row
    MATCH (d:Drug {commonName: row.commonName})
    MATCH (g:Gene {geneSymbol: row.geneSymbol})
    MERGE (d)-[r:compoundDownregulatesGene {source: "CTD"}]->(g)
    """
    count = 0
    with driver.session() as session:
        for i in range(0, len(df), BATCH_SIZE):
            rows = df.iloc[i:i+BATCH_SIZE].to_dict("records")
            session.run(query, rows=rows)
            count += len(rows)
    print(f"  Done: {count:,} compoundDownregulatesGene (CTD) edges")
    return count

def report_counts(driver):
    """Report final edge counts for all expression relationship types."""
    rels = [
        "bodyPartOverexpressesGene",
        "bodyPartUnderexpressesGene",
        "geneExpressedInBodyPart",
        "compoundUpregulatesGene",
        "compoundDownregulatesGene",
    ]
    # Report by source
    print("\n--- Compound Regulation by Source ---")
    for rel in ["compoundUpregulatesGene", "compoundDownregulatesGene"]:
        result = driver.session().run(f"MATCH ()-[r:{rel}]->() RETURN r.source as src, count(r) as cnt ORDER BY cnt DESC")
        for r in result:
            print(f"  {rel} [{r['src']}]: {r['cnt']:,}")
    print("\n=== Final Edge Counts ===")
    with driver.session() as session:
        for rel in rels:
            result = session.run(f"MATCH ()-[r:{rel}]->() RETURN count(r) as cnt")
            cnt = result.single()["cnt"]
            print(f"  {rel}: {cnt:,}")


if __name__ == "__main__":
    driver = get_driver()
    start = time.time()

    print("\n--- Loading Bgee Overexpression ---")
    load_bgee_overexpression(driver, "./data/processed/bgee/bodypart_overexpresses_gene.tsv")

    print("\n--- Loading Bgee Underexpression ---")
    load_bgee_underexpression(driver, "./data/processed/bgee/bodypart_underexpresses_gene.tsv")

    print("\n--- Loading Jensen TISSUES ---")
    load_jensen_tissues(driver, "./data/processed/jensen_tissues/gene_expressed_in_bodypart_cvd.tsv")

    print("\n--- Loading LINCS L1000 Upregulation ---")
    load_lincs_upregulation(driver, "./data/processed/lincs_l1000/compound_upregulates_gene.tsv")

    print("\n--- Loading LINCS L1000 Downregulation ---")
    load_lincs_downregulation(driver, "./data/processed/lincs_l1000/compound_downregulates_gene.tsv")

    print("\n--- Loading CTD Upregulation ---")
    load_ctd_upregulation(driver, "./data/processed/lincs_l1000/ctd_compound_upregulates_gene.tsv")

    print("\n--- Loading CTD Downregulation ---")
    load_ctd_downregulation(driver, "./data/processed/lincs_l1000/ctd_compound_downregulates_gene.tsv")

    report_counts(driver)
    driver.close()

    elapsed = time.time() - start
    print(f"\nTotal time: {elapsed:.1f}s")
