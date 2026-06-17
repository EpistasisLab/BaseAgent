#!/usr/bin/env python3
"""
LINCS L1000 Compound Expression Parser for CardioKB
Source: https://maayanlab.cloud/sigcom-lincs/
Creates: compoundUpregulatesGene, compoundDownregulatesGene edges
"""

import pandas as pd
import json
import os


def normalize(s):
    return s.lower().strip() if s else ""


def build_drug_lookup(driver):
    """Build normalized drug name -> commonName mapping from DB."""
    drug_names = {}
    with driver.session() as session:
        result = session.run(
            "MATCH (d:Drug) RETURN d.commonName as name, d.drugAliases as aliases"
        )
        for r in result:
            name = r["name"]
            if name:
                drug_names[normalize(name)] = name
            if r["aliases"]:
                for alias in r["aliases"]:
                    if alias:
                        drug_names[normalize(alias)] = name
    return drug_names


def parse_lincs_l1000(
    up_file: str,
    down_file: str,
    cvd_genes_file: str,
    drug_lookup: dict,
    output_dir: str
):
    """Parse LINCS L1000 compound expression files for CVD genes and DB drugs."""

    # Load CVD gene symbols
    with open(cvd_genes_file) as f:
        cvd_data = json.load(f)
    cvd_symbols = set(cvd_data["symbols"])
    print(f"CVD gene symbols: {len(cvd_symbols)}")

    def filter_and_match(df, direction):
        # Filter to CVD genes
        df_cvd = df[df["gene"].isin(cvd_symbols)].copy()
        print(f"  {direction} after CVD filter: {len(df_cvd):,}")

        # Match drugs to DB
        df_cvd["drug_norm"] = df_cvd["drug"].apply(normalize)
        df_cvd["commonName"] = df_cvd["drug_norm"].map(drug_lookup)
        df_matched = df_cvd[df_cvd["commonName"].notna()].copy()
        print(f"  {direction} after drug-in-DB filter: {len(df_matched):,}")

        # Rename and deduplicate
        df_final = df_matched[["commonName", "gene"]].rename(
            columns={"gene": "geneSymbol"}
        ).drop_duplicates(subset=["commonName", "geneSymbol"])
        print(f"  {direction} after dedup: {len(df_final):,}")
        print(f"  Unique drugs: {df_final['commonName'].nunique()}")
        print(f"  Unique CVD genes: {df_final['geneSymbol'].nunique()}")
        return df_final

    df_up = pd.read_csv(up_file, sep="\t")
    df_down = pd.read_csv(down_file, sep="\t")
    print(f"Raw up edges: {len(df_up):,}, down edges: {len(df_down):,}")

    df_up_final = filter_and_match(df_up, "UP")
    df_down_final = filter_and_match(df_down, "DOWN")

    # Save
    os.makedirs(output_dir, exist_ok=True)
    up_path = os.path.join(output_dir, "compound_upregulates_gene.tsv")
    down_path = os.path.join(output_dir, "compound_downregulates_gene.tsv")
    df_up_final.to_csv(up_path, sep="\t", index=False)
    df_down_final.to_csv(down_path, sep="\t", index=False)
    print(f"Saved: {up_path}")
    print(f"Saved: {down_path}")
    return df_up_final, df_down_final


if __name__ == "__main__":
    from neo4j import GraphDatabase
    driver = GraphDatabase.driver("bolt://localhost:7688", auth=None)
    drug_lookup = build_drug_lookup(driver)
    driver.close()

    parse_lincs_l1000(
        up_file="./data/processed/lincs/compound_up_edges.tsv",
        down_file="./data/processed/lincs/compound_down_edges.tsv",
        cvd_genes_file="./data/processed/cvd_genes.json",
        drug_lookup=drug_lookup,
        output_dir="./data/processed/lincs_l1000"
    )
