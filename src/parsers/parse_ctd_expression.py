#!/usr/bin/env python3
"""
CTD (Comparative Toxicogenomics Database) Chemical-Gene Expression Parser for CardioKB
Source: https://ctdbase.org/downloads/
Creates: compoundUpregulatesGene, compoundDownregulatesGene edges (source: "CTD")
"""

import gzip
import pandas as pd
import json
import re
import os


def normalize_drug(s):
    return s.lower().strip().replace("-", " ").replace("_", " ") if s else ""

def normalize_strict(s):
    return re.sub(r"[^a-z0-9]", "", s.lower()) if s else ""

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
                drug_names[name.lower().strip()] = name
                drug_names[normalize_drug(name)] = name
                drug_names[normalize_strict(name)] = name
            if r["aliases"]:
                for alias in r["aliases"]:
                    if alias:
                        drug_names[alias.lower().strip()] = name
                        drug_names[normalize_drug(alias)] = name
                        drug_names[normalize_strict(alias)] = name
    return drug_names


def classify_expression(action):
    """Classify interaction as up/down-regulation of expression."""
    if pd.isna(action):
        return None
    if "increases^expression" in action:
        return "up"
    elif "decreases^expression" in action:
        return "down"
    return None


def parse_ctd_expression(
    ctd_gz_file: str,
    cvd_genes_file: str,
    drug_lookup: dict,
    output_dir: str
):
    """Parse CTD chemical-gene interactions for expression changes in CVD genes."""

    with open(cvd_genes_file) as f:
        cvd_data = json.load(f)
    cvd_symbols = set(cvd_data["symbols"])
    print(f"CVD gene symbols: {len(cvd_symbols)}")

    col_names = ["ChemicalName","ChemicalID","CasRN","GeneSymbol","GeneID",
                 "GeneForms","Organism","OrganismID","Interaction",
                 "InteractionActions","PubMedIDs"]

    chunks = []
    total = 0
    with gzip.open(ctd_gz_file, "rt") as f:
        reader = pd.read_csv(f, sep="\t", comment="#", names=col_names, chunksize=100_000)
        for chunk in reader:
            total += len(chunk)
            human = chunk[chunk["Organism"] == "Homo sapiens"]
            expr = human[human["InteractionActions"].str.contains("expression", na=False)]
            if len(expr) > 0:
                chunks.append(expr)

    df = pd.concat(chunks, ignore_index=True)
    print(f"Total rows: {total:,}, human expression rows: {len(df):,}")

    # Classify direction
    df["direction"] = df["InteractionActions"].apply(classify_expression)
    df = df[df["direction"].notna() & df["GeneSymbol"].isin(cvd_symbols)].copy()

    # Match drugs to DB
    def match_drug(s):
        return (drug_lookup.get(s.lower().strip()) or
                drug_lookup.get(normalize_drug(s)) or
                drug_lookup.get(normalize_strict(s)))

    df["commonName"] = df["ChemicalName"].apply(match_drug)
    df = df[df["commonName"].notna()].copy()

    # Split and deduplicate
    df_up = df[df["direction"] == "up"][["commonName", "GeneSymbol"]]\
        .rename(columns={"GeneSymbol": "geneSymbol"})\
        .drop_duplicates(subset=["commonName", "geneSymbol"])

    df_down = df[df["direction"] == "down"][["commonName", "GeneSymbol"]]\
        .rename(columns={"GeneSymbol": "geneSymbol"})\
        .drop_duplicates(subset=["commonName", "geneSymbol"])

    os.makedirs(output_dir, exist_ok=True)
    up_path = os.path.join(output_dir, "ctd_compound_upregulates_gene.tsv")
    down_path = os.path.join(output_dir, "ctd_compound_downregulates_gene.tsv")
    df_up.to_csv(up_path, sep="\t", index=False)
    df_down.to_csv(down_path, sep="\t", index=False)

    print(f"CTD up edges: {len(df_up):,} ({df_up['commonName'].nunique()} drugs, {df_up['geneSymbol'].nunique()} genes) -> {up_path}")
    print(f"CTD down edges: {len(df_down):,} ({df_down['commonName'].nunique()} drugs, {df_down['geneSymbol'].nunique()} genes) -> {down_path}")
    return df_up, df_down


if __name__ == "__main__":
    from neo4j import GraphDatabase
    driver = GraphDatabase.driver("bolt://localhost:7688", auth=None)
    drug_lookup = build_drug_lookup(driver)
    driver.close()

    parse_ctd_expression(
        ctd_gz_file="./data/processed/ctd/CTD_chem_gene_ixns.tsv.gz",
        cvd_genes_file="./data/processed/cvd_genes.json",
        drug_lookup=drug_lookup,
        output_dir="./data/processed/lincs_l1000"
    )
