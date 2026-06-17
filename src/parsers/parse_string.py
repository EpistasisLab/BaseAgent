#!/usr/bin/env python3
"""
parse_string.py
Parser for STRING protein-protein interactions (human, taxon 9606)
Filters: combined_score >= 700, both proteins must be CVD genes in CardioKB
"""

import gzip
import pandas as pd
import os

# Configuration
LINKS_FILE = "./data/processed/string/9606.protein.links.v12.0.txt.gz"
INFO_FILE  = "./data/processed/string/9606.protein.info.v12.0.txt.gz"
CVD_GENES_FILE = "./data/processed/cvd_genes.txt"
OUTPUT_FILE = "./data/processed/string/string_cvd_interactions.tsv"
SCORE_THRESHOLD = 700

def build_protein_map(info_file):
    """Build mapping from STRING protein ID -> gene symbol."""
    protein_to_gene = {}
    with gzip.open(info_file, "rt") as f:
        f.readline()  # skip header
        for line in f:
            parts = line.strip().split("\t")
            if len(parts) >= 2:
                protein_to_gene[parts[0]] = parts[1]
    return protein_to_gene

def parse_links(links_file, protein_to_gene, cvd_gene_set, score_threshold):
    """Parse STRING links and filter for CVD-CVD interactions above threshold."""
    interactions = []
    with gzip.open(links_file, "rt") as f:
        f.readline()  # skip header
        for line in f:
            parts = line.strip().split(" ")
            if len(parts) < 3:
                continue
            p1, p2, score = parts[0], parts[1], int(parts[2])
            if score < score_threshold:
                continue
            g1 = protein_to_gene.get(p1)
            g2 = protein_to_gene.get(p2)
            if g1 and g2 and g1 in cvd_gene_set and g2 in cvd_gene_set:
                interactions.append({"gene1": g1, "gene2": g2, "combined_score": score})
    return interactions

def main():
    with open(CVD_GENES_FILE) as f:
        cvd_gene_set = set(line.strip() for line in f if line.strip())
    print(f"Loaded {len(cvd_gene_set)} CVD genes")

    protein_to_gene = build_protein_map(INFO_FILE)
    print(f"Mapped {len(protein_to_gene)} proteins")

    interactions = parse_links(LINKS_FILE, protein_to_gene, cvd_gene_set, SCORE_THRESHOLD)
    df = pd.DataFrame(interactions)

    # Deduplicate (A-B == B-A), keep highest score
    df["pair"] = df.apply(lambda r: tuple(sorted([r["gene1"], r["gene2"]])), axis=1)
    df = df.sort_values("combined_score", ascending=False).drop_duplicates(subset="pair")
    df = df.drop(columns=["pair"]).reset_index(drop=True)

    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    df.to_csv(OUTPUT_FILE, sep="\t", index=False)
    print(f"Saved {len(df):,} interactions to {OUTPUT_FILE}")
    return df

if __name__ == "__main__":
    main()
