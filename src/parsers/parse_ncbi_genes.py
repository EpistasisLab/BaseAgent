#!/usr/bin/env python3
"""
NCBI Gene Parser for CardioKB
Downloads and processes Homo_sapiens.gene_info.gz from NCBI FTP
Filters to protein-coding genes, deduplicates on geneSymbol
"""

import gzip
import pandas as pd
import os

def parse_ncbi_genes(input_gz, output_tsv):
    """Parse NCBI gene info file and return processed DataFrame."""
    
    with gzip.open(input_gz, 'rt') as f:
        df = pd.read_csv(f, sep='\t', low_memory=False)
    
    # Filter to protein-coding genes
    df_genes = df[df['type_of_gene'] == 'protein-coding'].copy()
    
    # Select and rename columns
    df_out = df_genes[['GeneID', 'Symbol', 'Full_name_from_nomenclature_authority', 
                        'type_of_gene', 'chromosome', 'Synonyms', 'description']].copy()
    df_out.columns = ['ncbiGeneId', 'geneSymbol', 'fullName', 'geneType', 
                      'chromosome', 'synonyms', 'description']
    
    # Fill missing full names
    df_out['fullName'] = df_out['fullName'].replace('-', pd.NA)
    df_out['fullName'] = df_out['fullName'].fillna(df_out['description'])
    df_out['chromosome'] = df_out['chromosome'].replace('-', pd.NA)
    df_out['ncbiGeneId'] = df_out['ncbiGeneId'].astype(str)
    df_out['source'] = 'NCBI Gene'
    
    # Deduplicate on geneSymbol (keep lowest GeneID)
    df_out['ncbiGeneId_int'] = df_out['ncbiGeneId'].astype(int)
    df_out = df_out.sort_values('ncbiGeneId_int').drop_duplicates(subset='geneSymbol', keep='first')
    df_out = df_out.drop('ncbiGeneId_int', axis=1)
    
    df_out.to_csv(output_tsv, sep='\t', index=False)
    print(f"Saved {len(df_out):,} genes to {output_tsv}")
    return df_out

if __name__ == "__main__":
    parse_ncbi_genes(
        "./data/processed/ncbi_gene/Homo_sapiens.gene_info.gz",
        "./data/processed/ncbi_gene/human_protein_coding_genes.tsv"
    )
