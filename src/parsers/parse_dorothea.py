#!/usr/bin/env python3
"""
parse_dorothea.py
Parser for DoRothEA TF-gene interactions via OmniPath
Filters: confidence levels A, B, C; target gene must be a CVD gene in CardioKB
"""

import requests
import pandas as pd
import io
import os

CVD_GENES_FILE = "./data/processed/cvd_genes.txt"
OUTPUT_FILE = "./data/processed/dorothea/dorothea_cvd_interactions.tsv"
OMNIPATH_URL = (
    "https://omnipathdb.org/interactions"
    "?datasets=dorothea&dorothea_levels=A,B,C"
    "&fields=dorothea_level&genesymbols=1&format=tsv"
)
CONFIDENCE_LEVELS = {"A", "B", "C"}

def download_dorothea(url):
    """Download DoRothEA interactions from OmniPath."""
    r = requests.get(url, timeout=120)
    r.raise_for_status()
    return pd.read_csv(io.StringIO(r.text), sep="\t")

def main():
    with open(CVD_GENES_FILE) as f:
        cvd_gene_set = set(line.strip() for line in f if line.strip())
    print(f"Loaded {len(cvd_gene_set)} CVD genes")

    df = download_dorothea(OMNIPATH_URL)
    print(f"Downloaded {len(df):,} DoRothEA interactions")

    # Clean combined confidence levels (e.g., "B;D" -> "B")
    df["confidence"] = df["dorothea_level"].str.split(";").str[0]
    df = df[df["confidence"].isin(CONFIDENCE_LEVELS)].copy()

    # Filter for CVD target genes
    df = df[df["target_genesymbol"].isin(cvd_gene_set)].copy()
    print(f"After CVD filter: {len(df):,}")

    # Select and rename columns
    df = df[["source_genesymbol", "target_genesymbol", "confidence"]].copy()
    df.columns = ["tf_symbol", "target_gene", "confidence"]

    # Deduplicate - keep highest confidence
    conf_order = {"A": 0, "B": 1, "C": 2}
    df["conf_rank"] = df["confidence"].map(conf_order)
    df = df.sort_values("conf_rank").drop_duplicates(
        subset=["tf_symbol", "target_gene"]
    ).drop(columns=["conf_rank"]).reset_index(drop=True)

    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    df.to_csv(OUTPUT_FILE, sep="\t", index=False)
    print(f"Saved {len(df):,} interactions to {OUTPUT_FILE}")
    return df

if __name__ == "__main__":
    main()
