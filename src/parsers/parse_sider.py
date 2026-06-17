#!/usr/bin/env python3
"""
SIDER Side Effects Parser
Extracts drug-side effect relationships from SIDER meddra_all_se.gz.
Filters to CVD drugs (by commonName). Creates SideEffect nodes with xrefUmlsCUI.
"""
import pandas as pd
import gzip

MEDDRA_PATH = "./data/processed/sider/meddra_all_se.gz"
DRUG_NAMES_PATH = "./data/processed/sider/drug_names.tsv"
EDGES_OUTPUT = "./data/processed/sider/cvd_drug_side_effect_edges.tsv"
NODES_OUTPUT = "./data/processed/sider/side_effect_nodes.tsv"

COL_NAMES = ["cid_stereo", "cid_flat", "umls_cui_label", "meddra_type", "umls_cui_concept", "side_effect_name"]

def parse_sider(cvd_drug_names):
    # Build CID -> CVD drug name mapping
    df_names = pd.read_csv(DRUG_NAMES_PATH, sep="\t", header=None, names=["cid", "drugName"])
    names_lower = {n.lower(): n for n in cvd_drug_names if n}
    cid_to_cvd = {
        row["cid"]: names_lower[str(row["drugName"]).lower().strip()]
        for _, row in df_names.iterrows()
        if str(row["drugName"]).lower().strip() in names_lower
    }

    # Load and filter meddra PT entries
    df = pd.read_csv(MEDDRA_PATH, sep="\t", header=None, names=COL_NAMES, compression="gzip")
    df_pt = df[df["meddra_type"] == "PT"].copy()
    df_cvd = df_pt[df_pt["cid_stereo"].isin(cid_to_cvd)].copy()
    df_cvd["commonName"] = df_cvd["cid_stereo"].map(cid_to_cvd)
    df_cvd["xrefUmlsCUI"] = df_cvd["umls_cui_concept"]
    df_cvd["sideEffectName"] = df_cvd["side_effect_name"]
    df_cvd["source"] = "SIDER"

    df_dedup = df_cvd[["commonName", "xrefUmlsCUI", "sideEffectName", "source"]].drop_duplicates(
        subset=["commonName", "xrefUmlsCUI"]
    )
    df_dedup.to_csv(EDGES_OUTPUT, sep="\t", index=False)

    df_nodes = df_dedup[["xrefUmlsCUI", "sideEffectName"]].drop_duplicates(subset=["xrefUmlsCUI"])
    df_nodes.to_csv(NODES_OUTPUT, sep="\t", index=False)

    print(f"Saved {len(df_dedup):,} edges to {EDGES_OUTPUT}")
    print(f"Saved {len(df_nodes):,} SideEffect nodes to {NODES_OUTPUT}")
    return df_dedup, df_nodes

if __name__ == "__main__":
    print("Run via disease_association_loader.py")
