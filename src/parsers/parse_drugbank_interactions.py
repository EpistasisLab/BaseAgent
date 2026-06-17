#!/usr/bin/env python3
"""
parse_drugbank_interactions.py
Parser for DrugBank drug-gene binding interactions
Source: dhimmel/drugbank proteins.tsv + drugbank.tsv
Filters: Human organism, target gene in CVD gene set, match to existing Drug nodes
"""

import requests
import pandas as pd
import io
import time
import os

CVD_GENES_FILE = "./data/processed/cvd_genes.txt"
OUTPUT_FILE = "./data/processed/drugbank/drugbank_cvd_interactions.tsv"
PROTEINS_URL = "https://raw.githubusercontent.com/dhimmel/drugbank/gh-pages/data/proteins.tsv"
DRUGS_URL = "https://raw.githubusercontent.com/dhimmel/drugbank/master/data/drugbank.tsv"

def get_gene_symbols_from_uniprot(uniprot_ids, batch_size=100):
    uniprot_to_gene = {}
    for i in range(0, len(uniprot_ids), batch_size):
        batch = uniprot_ids[i:i+batch_size]
        query = " OR ".join([f"accession:{uid}" for uid in batch])
        url = "https://rest.uniprot.org/uniprotkb/search"
        params = {"query": query, "fields": "accession,gene_names", "format": "tsv", "size": 500}
        try:
            r = requests.get(url, params=params, timeout=60)
            if r.status_code == 200 and r.text.strip():
                for line in r.text.strip().split("\n")[1:]:
                    parts = line.split("\t")
                    if len(parts) >= 2:
                        gene = parts[1].strip().split()[0] if parts[1].strip() else ""
                        if gene:
                            uniprot_to_gene[parts[0].strip()] = gene
        except Exception as e:
            print(f"  UniProt batch {i} error: {e}")
        time.sleep(0.2)
    return uniprot_to_gene

def main():
    with open(CVD_GENES_FILE) as f:
        cvd_gene_set = set(line.strip() for line in f if line.strip())

    df_proteins = pd.read_csv(PROTEINS_URL, sep="\t")
    df_drugs = pd.read_csv(DRUGS_URL, sep="\t", usecols=["drugbank_id", "name"])

    df_human = df_proteins[df_proteins["organism"] == "Human"].copy()
    uniprot_ids = df_human["uniprot_id"].dropna().unique().tolist()
    uniprot_to_gene = get_gene_symbols_from_uniprot(uniprot_ids)

    df_human["gene_symbol"] = df_human["uniprot_id"].map(uniprot_to_gene)
    df_cvd = df_human[df_human["gene_symbol"].isin(cvd_gene_set)].copy()
    df_cvd = df_cvd.merge(df_drugs, on="drugbank_id", how="left")
    df_cvd["action"] = df_cvd["actions"].fillna("unknown").str.split("|").str[0]

    df_out = df_cvd[["drugbank_id", "name", "gene_symbol", "action", "category"]].copy()
    df_out.columns = ["drugbank_id", "drug_name", "gene_symbol", "action", "category"]

    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    df_out.to_csv(OUTPUT_FILE, sep="\t", index=False)
    print(f"Saved {len(df_out):,} interactions to {OUTPUT_FILE}")
    return df_out

if __name__ == "__main__":
    main()
