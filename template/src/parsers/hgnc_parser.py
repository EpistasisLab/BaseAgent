"""
HGNC Gene Families Parser for the knowledge graph.

Downloads gene family data from HGNC and produces:
  - gene_family_nodes.tsv       : GeneFamily nodes
  - gene_family_associations.tsv: geneInFamily edges (Gene → GeneFamily)

Data Source: https://www.genenames.org/cgi-bin/genegroup/download-all
"""

import logging
from pathlib import Path
from typing import Dict, Optional

import pandas as pd

from .base_parser import BaseParser

logger = logging.getLogger(__name__)

_DEFAULT_URL = "https://storage.googleapis.com/public-download-files/hgnc/tsv/tsv/hgnc_complete_set.txt"
_FILENAME = "hgnc_gene_families.tsv"

FAMILY_NODES = "gene_family_nodes"
FAMILY_ASSOC = "gene_family_associations"


class HGNCFamiliesParser(BaseParser):
    """
    Parser for HGNC Gene Families.

    Downloads the HGNC gene group/family TSV and extracts GeneFamily nodes
    and geneInFamily edges.

    Constructor args (injected from databases.yaml):
        data_dir   – base directory for raw/cached files
        source_url – URL of the HGNC gene families download
    """

    def __init__(self, data_dir: str, source_url: Optional[str] = None):
        super().__init__(data_dir)
        self.source_name = "hgnc"
        self.source_dir = self.data_dir / self.source_name
        self.source_dir.mkdir(parents=True, exist_ok=True)
        # Use the HGNC complete set TSV (the custom download URL requires JS)
        self.source_url = _DEFAULT_URL

    # ------------------------------------------------------------------
    # Download
    # ------------------------------------------------------------------

    def download_data(self) -> bool:
        logger.info("Downloading HGNC gene families from %s ...", self.source_url)
        result = self.download_file(self.source_url, _FILENAME)
        if not result:
            logger.error("Failed to download HGNC gene families.")
            return False
        return True

    # ------------------------------------------------------------------
    # Parse
    # ------------------------------------------------------------------

    def parse_data(self) -> Dict[str, pd.DataFrame]:
        filepath = self.source_dir / _FILENAME
        if not filepath.exists():
            logger.error("HGNC gene families file not found: %s", filepath)
            return {}

        logger.info("Parsing HGNC gene families from %s ...", filepath)

        try:
            df = pd.read_csv(filepath, sep="\t", dtype=str, low_memory=False)
        except Exception as exc:
            logger.error("Failed to read HGNC file: %s", exc)
            return {}

        logger.info("HGNC raw: %d rows, columns: %s", len(df), list(df.columns))

        # HGNC complete set TSV columns include:
        # hgnc_id, symbol, name, gene_group, gene_group_id, entrez_id, etc.
        df.columns = [c.strip() for c in df.columns]

        # Identify key columns flexibly
        col_map = {}
        for col in df.columns:
            cl = col.lower()
            if cl == "gene_group_id":
                col_map[col] = "family_id"
            elif cl == "gene_group":
                col_map[col] = "family_name"
            elif cl == "hgnc_id":
                col_map[col] = "hgnc_id"
            elif cl == "symbol":
                col_map[col] = "gene_symbol"
            elif cl == "name":
                col_map[col] = "gene_name"
            elif cl == "entrez_id":
                col_map[col] = "ncbi_gene_id"

        df = df.rename(columns=col_map)
        # Filter out rows with no family assignment
        if "family_id" in df.columns:
            df = df[df["family_id"].notna() & (df["family_id"].astype(str).str.strip() != "")]

        # ---- GeneFamily nodes ----
        family_cols = [c for c in ["family_id", "family_name"] if c in df.columns]
        if not family_cols:
            logger.warning("Could not identify family columns in HGNC file.")
            family_df = pd.DataFrame(columns=["family_id", "family_name", "source_database"])
        else:
            family_df = (
                df[family_cols]
                .drop_duplicates(subset=["family_id"])
                .reset_index(drop=True)
            )
            family_df["source_database"] = "HGNC"
            logger.info("HGNC: %d gene families", len(family_df))

        # ---- geneInFamily edges ----
        assoc_cols = [c for c in ["family_id", "family_name", "hgnc_id", "gene_symbol", "ncbi_gene_id"]
                      if c in df.columns]
        if not assoc_cols or "family_id" not in assoc_cols:
            logger.warning("Could not build gene-family associations from HGNC file.")
            assoc_df = pd.DataFrame(columns=["family_id", "gene_symbol", "hgnc_id", "source_database"])
        else:
            assoc_df = df[assoc_cols].dropna(subset=["family_id"]).drop_duplicates().reset_index(drop=True)
            assoc_df["source_database"] = "HGNC"
            logger.info("HGNC: %d gene-family associations", len(assoc_df))

        return {
            FAMILY_NODES: family_df,
            FAMILY_ASSOC: assoc_df,
        }

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    def get_schema(self) -> Dict[str, Dict[str, str]]:
        return {
            FAMILY_NODES: {
                "family_id":       "HGNC gene family/group ID",
                "family_name":     "HGNC gene family/group name",
                "source_database": "Source database (HGNC)",
            },
            FAMILY_ASSOC: {
                "family_id":       "HGNC gene family/group ID",
                "family_name":     "HGNC gene family/group name",
                "hgnc_id":         "HGNC ID of the gene",
                "gene_symbol":     "Approved gene symbol",
                "ncbi_gene_id":    "NCBI Gene ID (Entrez)",
                "source_database": "Source database (HGNC)",
            },
        }
