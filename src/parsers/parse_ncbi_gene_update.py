#!/usr/bin/env python3
"""
Parser: NCBI Gene → Memgraph Gene node updater
Updates existing Gene nodes with ncbiGeneId and description properties.
Source: human_protein_coding_genes.tsv (20,598 human protein-coding genes)
"""

import pandas as pd
import sys

def load_human_protein_coding_genes(filepath: str) -> pd.DataFrame:
    """Load and validate the human protein coding genes TSV."""
    df = pd.read_csv(filepath, sep='\t', dtype={'ncbiGeneId': str})
    
    # Rename columns to match schema
    df = df.rename(columns={'fullName': 'geneName'})
    
    # Ensure required columns exist
    required = ['ncbiGeneId', 'geneSymbol', 'geneName', 'chromosome', 'geneType', 'description', 'source']
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Missing columns: {missing}")
    
    # Clean data
    df['ncbiGeneId'] = df['ncbiGeneId'].astype(str).str.strip()
    df['geneSymbol'] = df['geneSymbol'].str.strip()
    df['description'] = df['description'].fillna(df['geneName'])
    
    return df

if __name__ == "__main__":
    filepath = "./data/processed/ncbi_gene/human_protein_coding_genes.tsv"
    df = load_human_protein_coding_genes(filepath)
    print(f"Loaded {len(df)} genes")
    print(df.head(3).to_string())
