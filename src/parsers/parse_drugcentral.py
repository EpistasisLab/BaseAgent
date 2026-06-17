#!/usr/bin/env python3
"""
DrugCentral Drug-Disease Parser
Uses Hetionet edges (sourced from DrugCentral) to extract drug-disease relationships.
Filters to CVD drugs (by commonName) and CVD diseases (by DOID).
"""
import pandas as pd

HETIONET_PATH = "./data/processed/medline/hetionet-v1.0-edges.sif"
DRUGBANK_VOCAB = "./data/processed/drugbank/drugs.tsv"
TREATS_OUTPUT = "./data/processed/drugcentral/drug_treats_disease_edges.tsv"
PALLIATES_OUTPUT = "./data/processed/drugcentral/drug_palliates_disease_edges.tsv"

def parse_drugcentral(cvd_drug_names, cvd_doids):
    # Load Hetionet edges
    df = pd.read_csv(HETIONET_PATH, sep="\t")
    
    # Build DrugBank ID -> CVD commonName mapping
    df_db = pd.read_csv(DRUGBANK_VOCAB, sep="\t")
    names_lower = {n.lower(): n for n in cvd_drug_names if n}
    db_to_cvd = {}
    for _, row in df_db.iterrows():
        if pd.notna(row["commonName"]) and row["commonName"].lower() in names_lower:
            db_to_cvd[row["drugbankId"]] = names_lower[row["commonName"].lower()]
    
    # Parse CtD (treats) and CpD (palliates)
    for rel_type, out_path, rel_name in [
        ("CtD", TREATS_OUTPUT, "drugTreatsDisease"),
        ("CpD", PALLIATES_OUTPUT, "drugPalliatesDisease"),
    ]:
        df_rel = df[df["metaedge"] == rel_type].copy()
        df_rel["drugBankId"] = df_rel["source"].str.replace("Compound::", "")
        df_rel["doid"] = df_rel["target"].str.replace("Disease::", "")
        df_filtered = df_rel[
            df_rel["drugBankId"].isin(db_to_cvd) & df_rel["doid"].isin(cvd_doids)
        ].copy()
        df_filtered["commonName"] = df_filtered["drugBankId"].map(db_to_cvd)
        df_filtered["source"] = "DrugCentral"
        df_filtered["relationship"] = rel_name
        df_filtered[["commonName", "doid", "source", "relationship"]].to_csv(
            out_path, sep="\t", index=False
        )
        print(f"Saved {len(df_filtered):,} {rel_name} edges to {out_path}")

if __name__ == "__main__":
    print("Run via disease_association_loader.py")
