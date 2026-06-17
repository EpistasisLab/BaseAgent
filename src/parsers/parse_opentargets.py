#!/usr/bin/env python3
"""
OpenTargets Gene-Disease Association Parser
Filters to CVD genes and CVD diseases (by DOID cross-reference)
"""
import pandas as pd
import numpy as np
import glob
import os

OT_DIR = "./data/processed/opentargets/"
OUTPUT_PATH = "./data/processed/opentargets/cvd_gene_disease_edges.tsv"

def load_disease_mapping(ot_dir):
    """Build EFO/MONDO -> DOID mapping from disease parquet files."""
    disease_files = glob.glob(ot_dir + "disease_*.parquet")
    dfs = [pd.read_parquet(f, columns=["id", "dbXRefs"]) for f in disease_files]
    df_diseases = pd.concat(dfs, ignore_index=True)
    
    mapping = {}
    for _, row in df_diseases.iterrows():
        xrefs = row["dbXRefs"]
        if xrefs is not None and not (isinstance(xrefs, float) and np.isnan(xrefs)):
            for xref in xrefs:
                if isinstance(xref, str) and xref.startswith("DOID:"):
                    mapping[row["id"]] = xref
                    break
    return mapping

def parse_opentargets(cvd_genes, cvd_doids):
    """Parse and filter OpenTargets associations."""
    df = pd.read_csv(OT_DIR + "gene_disease_edges.tsv", sep="\t")
    mondo_to_doid = load_disease_mapping(OT_DIR)
    
    df["xrefDiseaseOntology"] = df["diseaseId"].map(mondo_to_doid)
    df_filtered = df[
        df["geneSymbol"].isin(cvd_genes) &
        df["xrefDiseaseOntology"].isin(cvd_doids)
    ].copy()
    
    df_filtered["source"] = "OpenTargets"
    df_filtered[["geneSymbol", "xrefDiseaseOntology", "diseaseName", "score", "source"]].to_csv(
        OUTPUT_PATH, sep="\t", index=False
    )
    print(f"Saved {len(df_filtered):,} associations to {OUTPUT_PATH}")
    return df_filtered

if __name__ == "__main__":
    # These would be loaded from Neo4j in production
    print("Run via disease_association_loader.py")
