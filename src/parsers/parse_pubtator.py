#!/usr/bin/env python3
"""
PubTator Disease-Disease Association Parser
Filters to CVD diseases already in the graph (by DOID).
Source: PubTatorCentral disease2pubtatorcentral.gz
"""
import pandas as pd
import gzip

INPUT_PATH = "./data/processed/pubtator/disease_disease_edges.tsv"
OUTPUT_PATH = "./data/processed/pubtator/cvd_disease_disease_edges.tsv"

def parse_pubtator(cvd_doids):
    df = pd.read_csv(INPUT_PATH, sep="\t")
    df_filtered = df[
        df["disease1"].isin(cvd_doids) & df["disease2"].isin(cvd_doids)
    ].copy()
    df_filtered["source"] = "PubTator"
    df_filtered.to_csv(OUTPUT_PATH, sep="\t", index=False)
    print(f"Saved {len(df_filtered):,} disease-disease edges to {OUTPUT_PATH}")
    return df_filtered

if __name__ == "__main__":
    print("Run via disease_association_loader.py")
