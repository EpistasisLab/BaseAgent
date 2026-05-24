"""
CTD (Comparative Toxicogenomics Database) Parser for the knowledge graph.

Downloads the CTD chemical-gene interactions bulk TSV and extracts two
expression edge types plus the associated node tables:

  chemical_nodes.tsv                  — Chemical nodes (MeSH)
  chemical_increases_expression.tsv   — chemicalIncreasesExpression edges
  chemical_decreases_expression.tsv   — chemicalDecreasesExpression edges

Data Source: http://ctdbase.org/reports/CTD_chem_gene_ixns.tsv.gz
"""

import logging
from typing import Dict

import pandas as pd

from .base_parser import BaseParser

logger = logging.getLogger(__name__)


class CTDParser(BaseParser):
    """
    Parser for CTD (Comparative Toxicogenomics Database).

    Downloads the chemical-gene interaction file and extracts rows whose
    InteractionActions column contains an "increases^expression" or
    "decreases^expression" action token.

    No credentials required — public download.
    """

    CTD_URL = "http://ctdbase.org/reports/CTD_chem_gene_ixns.tsv.gz"
    _FILENAME = "CTD_chem_gene_ixns.tsv.gz"

    # Column names as they appear in the CTD file (after skipping # comment lines)
    _CTD_COLS = [
        "ChemicalName",
        "ChemicalID",
        "CasRN",
        "GeneSymbol",
        "GeneID",
        "GeneForms",
        "Organism",
        "OrganismID",
        "Interaction",
        "InteractionActions",
        "PubMedIDs",
    ]

    def __init__(self, data_dir: str):
        super().__init__(data_dir)
        self.source_name = "ctd"
        self.source_dir = self.data_dir / self.source_name
        self.source_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Download
    # ------------------------------------------------------------------

    def download_data(self) -> bool:
        """Download the CTD chemical-gene interactions file."""
        logger.info("Downloading CTD chemical-gene interactions …")
        result = self.download_file(self.CTD_URL, self._FILENAME)
        if result:
            logger.info("CTD file available at: %s", result)
            return True
        logger.error("Failed to download CTD chemical-gene interactions.")
        return False

    # ------------------------------------------------------------------
    # Parse
    # ------------------------------------------------------------------

    def parse_data(self) -> Dict[str, pd.DataFrame]:
        """
        Parse the CTD chemical-gene interactions file.

        Returns a dict with up to three DataFrames:
          - chemical_nodes
          - chemical_increases_expression
          - chemical_decreases_expression
        """
        tsv_path = self.source_dir / self._FILENAME
        if not tsv_path.exists():
            logger.error("CTD file not found: %s", tsv_path)
            return {}

        logger.info("Parsing CTD from %s …", tsv_path)

        try:
            df = pd.read_csv(
                tsv_path,
                sep="\t",
                compression="gzip",
                comment="#",
                header=None,
                names=self._CTD_COLS,
                low_memory=False,
                dtype=str,
            )
        except Exception as exc:
            logger.exception("Failed to read CTD file: %s", exc)
            return {}

        logger.info("Loaded %d raw CTD rows.", len(df))

        # ---- Normalise ChemicalID to MESH:XXXXXXX format ----
        df["ChemicalID"] = df["ChemicalID"].apply(self._normalize_mesh_id)

        # ---- Drop rows missing essential fields ----
        df = df.dropna(subset=["ChemicalID", "GeneID", "InteractionActions"])
        df = df[df["ChemicalID"].str.strip() != ""]
        df = df[df["GeneID"].str.strip() != ""]

        # ---- Explode pipe-separated InteractionActions into one row each ----
        df = df.copy()
        df["InteractionActions"] = df["InteractionActions"].str.split("|")
        df = df.explode("InteractionActions")
        df["InteractionActions"] = df["InteractionActions"].str.strip()

        # ---- Keep only expression-related actions ----
        expr_mask = df["InteractionActions"].str.contains(
            r"\^expression", case=False, na=False, regex=True
        )
        df_expr = df[expr_mask].copy()
        logger.info("Rows with expression actions: %d", len(df_expr))

        if df_expr.empty:
            logger.warning("No expression-related interactions found in CTD data.")
            return {}

        # ---- Split into increases / decreases ----
        inc_mask = df_expr["InteractionActions"].str.lower().str.startswith(
            "increases^", na=False
        )
        dec_mask = df_expr["InteractionActions"].str.lower().str.startswith(
            "decreases^", na=False
        )

        df_inc = df_expr[inc_mask].copy()
        df_dec = df_expr[dec_mask].copy()
        logger.info("  increases^expression rows : %d", len(df_inc))
        logger.info("  decreases^expression rows : %d", len(df_dec))

        # ---- Build edge DataFrames ----
        def _build_edges(src: pd.DataFrame) -> pd.DataFrame:
            out = pd.DataFrame(
                {
                    "chemical_id": src["ChemicalID"].str.strip(),
                    "gene_id": src["GeneID"].str.strip(),
                    "interaction_text": src["Interaction"].fillna("").str.strip(),
                    "organism": src["OrganismID"].fillna("").str.strip(),
                    "pubmed_ids": src["PubMedIDs"].fillna(""),
                }
            )
            return out.drop_duplicates().reset_index(drop=True)

        inc_edges = _build_edges(df_inc)
        dec_edges = _build_edges(df_dec)
        inc_edges["source_database"] = "CTD"
        dec_edges["source_database"] = "CTD"

        # ---- Build Chemical node DataFrame ----
        chem_df = (
            df_expr[["ChemicalID", "ChemicalName"]]
            .drop_duplicates(subset=["ChemicalID"])
            .rename(columns={"ChemicalID": "chemical_id", "ChemicalName": "chemical_name"})
            .copy()
        )
        chem_df["mesh_id"] = chem_df["chemical_id"]
        chem_df = chem_df[["chemical_id", "chemical_name", "mesh_id"]].reset_index(drop=True)
        chem_df["source_database"] = "CTD"

        logger.info("Chemical nodes : %d", len(chem_df))
        logger.info(
            "increases_expression edges : %d  |  decreases_expression edges : %d",
            len(inc_edges),
            len(dec_edges),
        )

        result: Dict[str, pd.DataFrame] = {}
        if not chem_df.empty:
            result["chemical_nodes"] = chem_df
        if not inc_edges.empty:
            result["chemical_increases_expression"] = inc_edges
        if not dec_edges.empty:
            result["chemical_decreases_expression"] = dec_edges

        return result

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_mesh_id(mesh_id) -> str:
        """Return a MeSH ID in MESH:XXXXXXX format."""
        if pd.isna(mesh_id):
            return ""
        mesh_id = str(mesh_id).strip()
        if mesh_id and not mesh_id.startswith("MESH:"):
            mesh_id = f"MESH:{mesh_id}"
        return mesh_id

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    def get_schema(self) -> Dict[str, Dict[str, str]]:
        """Return the column schema for each output table."""
        return {
            "chemical_nodes": {
                "chemical_id": "MeSH ID for the chemical (e.g. MESH:D000082)",
                "chemical_name": "Name of the chemical",
                "mesh_id": "MeSH identifier (same as chemical_id)",
                "source_database": "CTD",
            },
            "chemical_increases_expression": {
                "chemical_id": "Source chemical MeSH ID",
                "gene_id": "Target NCBI Gene ID",
                "interaction_text": "Full interaction description from CTD",
                "organism": "Organism taxon ID",
                "pubmed_ids": "Pipe-separated PubMed IDs supporting the interaction",
                "source_database": "CTD",
            },
            "chemical_decreases_expression": {
                "chemical_id": "Source chemical MeSH ID",
                "gene_id": "Target NCBI Gene ID",
                "interaction_text": "Full interaction description from CTD",
                "organism": "Organism taxon ID",
                "pubmed_ids": "Pipe-separated PubMed IDs supporting the interaction",
                "source_database": "CTD",
            },
        }
