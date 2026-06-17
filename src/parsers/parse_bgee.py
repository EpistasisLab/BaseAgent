#!/usr/bin/env python3
"""
Bgee Expression Parser for CardioKB
Source: https://www.bgee.org/ftp/
Creates: bodyPartOverexpressesGene, bodyPartUnderexpressesGene edges
"""

import gzip
import pandas as pd
import json
import os
import sys

# Thresholds
OVER_EXPRESSION_SCORE_THRESHOLD = 75.0  # Expression score >= 75 = overexpressed
UNDER_EXPRESSION_CALL = "absent"         # Expression = absent = underexpressed

def parse_bgee(
    bgee_gz_file: str,
    cvd_genes_file: str,
    db_uberon_set: set,
    output_dir: str
):
    """Parse Bgee simple expression file and extract over/underexpression for CVD genes."""
    
    # Load CVD gene mapping (Ensembl -> symbol)
    with open(cvd_genes_file) as f:
        cvd_data = json.load(f)
    ensembl_to_symbol = {g["ensembl"]: g["symbol"] for g in cvd_data["full"] if g["ensembl"]}
    print(f"CVD Ensembl IDs: {len(ensembl_to_symbol)}")

    # Process in chunks
    chunks = []
    total_rows = 0
    chunk_size = 100_000

    with gzip.open(bgee_gz_file, "rt") as f:
        reader = pd.read_csv(f, sep="\t", quotechar='"', chunksize=chunk_size)
        for chunk in reader:
            total_rows += len(chunk)
            cvd_mask = chunk["Gene ID"].isin(ensembl_to_symbol)
            uberon_mask = chunk["Anatomical entity ID"].str.match(r"^UBERON:\d+$")
            filtered = chunk[cvd_mask & uberon_mask].copy()
            filtered = filtered[filtered["Anatomical entity ID"].isin(db_uberon_set)]
            if len(filtered) > 0:
                chunks.append(filtered)

    df = pd.concat(chunks, ignore_index=True)
    df["geneSymbol"] = df["Gene ID"].map(ensembl_to_symbol)
    df = df.rename(columns={"Anatomical entity ID": "xrefUberon"})
    print(f"Total rows processed: {total_rows:,}, filtered: {len(df):,}")

    # Overexpressed: present + high score
    df_over = df[
        (df["Expression"] == "present") &
        (df["Expression score"] >= OVER_EXPRESSION_SCORE_THRESHOLD)
    ][["geneSymbol", "xrefUberon", "Expression score", "Expression rank", "Call quality"]].copy()
    df_over = df_over.sort_values("Expression score", ascending=False)\
        .drop_duplicates(subset=["geneSymbol", "xrefUberon"])

    # Underexpressed: absent
    df_under = df[
        df["Expression"] == UNDER_EXPRESSION_CALL
    ][["geneSymbol", "xrefUberon", "Expression score", "Expression rank", "Call quality"]].copy()
    df_under = df_under.sort_values("Expression score", ascending=True)\
        .drop_duplicates(subset=["geneSymbol", "xrefUberon"])

    # Save
    os.makedirs(output_dir, exist_ok=True)
    over_path = os.path.join(output_dir, "bodypart_overexpresses_gene.tsv")
    under_path = os.path.join(output_dir, "bodypart_underexpresses_gene.tsv")
    df_over.to_csv(over_path, sep="\t", index=False)
    df_under.to_csv(under_path, sep="\t", index=False)

    print(f"Overexpressed edges: {len(df_over):,} -> {over_path}")
    print(f"Underexpressed edges: {len(df_under):,} -> {under_path}")
    return df_over, df_under


if __name__ == "__main__":
    from neo4j import GraphDatabase
    driver = GraphDatabase.driver("bolt://localhost:7688", auth=None)
    with driver.session() as session:
        result = session.run("MATCH (b:BodyPart) RETURN b.xrefUberon as uberon")
        db_uberon = {r["uberon"] for r in result}
    driver.close()

    parse_bgee(
        bgee_gz_file="./data/processed/bgee/Homo_sapiens_expr_simple.tsv.gz",
        cvd_genes_file="./data/processed/cvd_genes.json",
        db_uberon_set=db_uberon,
        output_dir="./data/processed/bgee"
    )
