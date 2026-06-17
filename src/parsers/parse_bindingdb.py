#!/usr/bin/env python3
"""
parse_bindingdb.py
Parser for BindingDB chemical-gene binding interactions
Sources: BindingDB_Articles and BindingDB_ChEMBL subsets
Filters: Homo sapiens targets, Ki or Kd <= 10000 nM, target gene in CVD gene set
"""

import requests
import pandas as pd
import zipfile
import io
import os
import time

CVD_GENES_FILE = "./data/processed/cvd_genes.txt"
OUTPUT_FILE = "./data/processed/bindingdb/bindingdb_cvd_interactions.tsv"
ARTICLES_URL = "https://www.bindingdb.org/rwd/bind/downloads/BindingDB_BindingDB_Articles_202604_tsv.zip"
CHEMBL_URL = "https://www.bindingdb.org/rwd/bind/downloads/BindingDB_ChEMBL_202604_tsv.zip"
AFFINITY_THRESHOLD_NM = 10000

KEY_COLS = [
    "BindingDB Ligand Name",
    "Target Name",
    "Target Source Organism According to Curator or DataSource",
    "Ki (nM)",
    "Kd (nM)",
    "DrugBank ID of Ligand",
    "UniProt (SwissProt) Primary ID of Target Chain 1",
]

def parse_affinity(val):
    if pd.isna(val) or val == "":
        return None
    try:
        return float(str(val).strip().replace(">", "").replace("<", "").replace("=", ""))
    except:
        return None

def get_gene_symbols_from_uniprot(uniprot_ids, batch_size=100):
    uniprot_to_gene = {}
    for i in range(0, len(uniprot_ids), batch_size):
        batch = uniprot_ids[i:i+batch_size]
        query = " OR ".join([f"accession:{uid}" for uid in batch])
        params = {"query": query, "fields": "accession,gene_names", "format": "tsv", "size": 500}
        try:
            r = requests.get("https://rest.uniprot.org/uniprotkb/search", params=params, timeout=60)
            if r.status_code == 200:
                for line in r.text.strip().split("\n")[1:]:
                    parts = line.split("\t")
                    if len(parts) >= 2 and parts[1].strip():
                        uniprot_to_gene[parts[0].strip()] = parts[1].strip().split()[0]
        except Exception as e:
            print(f"  UniProt batch {i} error: {e}")
        time.sleep(0.2)
    return uniprot_to_gene

def process_zip(zip_path, tsv_name, uniprot_to_gene, cvd_gene_set, chunk_size=50000):
    results = []
    with zipfile.ZipFile(zip_path, "r") as z:
        with z.open(tsv_name) as f:
            for chunk in pd.read_csv(f, sep="\t", usecols=KEY_COLS, dtype=str,
                                      encoding_errors="replace", chunksize=chunk_size):
                chunk = chunk[
                    chunk["Target Source Organism According to Curator or DataSource"] == "Homo sapiens"
                ].copy()
                chunk["ki_val"] = chunk["Ki (nM)"].apply(parse_affinity)
                chunk["kd_val"] = chunk["Kd (nM)"].apply(parse_affinity)
                chunk["best_affinity"] = chunk[["ki_val", "kd_val"]].min(axis=1)
                chunk = chunk[chunk["best_affinity"] <= AFFINITY_THRESHOLD_NM].copy()
                chunk["gene_symbol"] = chunk["UniProt (SwissProt) Primary ID of Target Chain 1"].map(uniprot_to_gene)
                chunk = chunk[chunk["gene_symbol"].isin(cvd_gene_set)]
                if len(chunk) > 0:
                    results.append(chunk)
    return pd.concat(results, ignore_index=True) if results else pd.DataFrame()

def main():
    with open(CVD_GENES_FILE) as f:
        cvd_gene_set = set(line.strip() for line in f if line.strip())

    # Download files if needed
    for url, path in [(ARTICLES_URL, "./data/processed/bindingdb/articles.zip"),
                      (CHEMBL_URL, "./data/processed/bindingdb/chembl.zip")]:
        if not os.path.exists(path):
            r = requests.get(url, timeout=600, stream=True)
            with open(path, "wb") as f:
                for chunk in r.iter_content(65536):
                    f.write(chunk)

    # Get UniProt IDs
    all_ids = set()
    for zip_path, tsv_name in [
        ("./data/processed/bindingdb/articles.zip", "BindingDB_BindingDB_Articles.tsv"),
        ("./data/processed/bindingdb/chembl.zip", "BindingDB_ChEMBL.tsv"),
    ]:
        with zipfile.ZipFile(zip_path) as z:
            with z.open(tsv_name) as f:
                for chunk in pd.read_csv(f, sep="\t",
                    usecols=["UniProt (SwissProt) Primary ID of Target Chain 1"],
                    dtype=str, chunksize=100000):
                    all_ids.update(chunk.iloc[:, 0].dropna().unique())

    uniprot_to_gene = get_gene_symbols_from_uniprot(list(all_ids))

    dfs = []
    for zip_path, tsv_name in [
        ("./data/processed/bindingdb/articles.zip", "BindingDB_BindingDB_Articles.tsv"),
        ("./data/processed/bindingdb/chembl.zip", "BindingDB_ChEMBL.tsv"),
    ]:
        df = process_zip(zip_path, tsv_name, uniprot_to_gene, cvd_gene_set)
        dfs.append(df)

    df_all = pd.concat(dfs, ignore_index=True)
    df_all = df_all.sort_values("best_affinity").drop_duplicates(
        subset=["BindingDB Ligand Name", "gene_symbol"]
    ).reset_index(drop=True)

    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    df_all.to_csv(OUTPUT_FILE, sep="\t", index=False)
    print(f"Saved {len(df_all):,} interactions to {OUTPUT_FILE}")
    return df_all

if __name__ == "__main__":
    main()
