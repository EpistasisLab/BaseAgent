"""
SIDER Side Effects Parser for the knowledge graph.

Downloads meddra_all_se.tsv.gz from SIDER and produces:
  - side_effect_nodes.tsv       : SideEffect nodes (MedDRA terms)
  - drug_side_effect_assoc.tsv  : compoundCausesSideEffect edges

Data Source:
  http://sideeffects.embl.de/media/download/meddra_all_se.tsv.gz

File columns (tab-separated, no header):
  STITCH_compound_flat | STITCH_compound_stereo | UMLS_concept_on_label |
  MedDRA_concept_type | UMLS_concept_meddra | side_effect_name
"""

import logging
from pathlib import Path
from typing import Dict, Optional

import pandas as pd

from .base_parser import BaseParser

logger = logging.getLogger(__name__)

_DEFAULT_URL = "http://sideeffects.embl.de/media/download/meddra_all_se.tsv.gz"
_GZ_FILENAME = "meddra_all_se.tsv.gz"
_FILENAME    = "meddra_all_se.tsv"

SIDE_EFFECT_NODES = "side_effect_nodes"
DRUG_SE_ASSOC     = "drug_side_effect_associations"
SIDER_DRUG_NODES  = "sider_drug_nodes"

# Column names for the SIDER file (no header row)
_SIDER_COLS = [
    "stitch_flat",
    "stitch_stereo",
    "umls_label",
    "meddra_type",
    "umls_meddra",
    "side_effect_name",
]


class SIDERParser(BaseParser):
    """
    Parser for the SIDER side effects database.

    Downloads meddra_all_se.tsv.gz directly from SIDER (not from Hetionet)
    and extracts SideEffect nodes and compoundCausesSideEffect edges.

    Constructor args (injected from databases.yaml):
        data_dir   – base directory for raw/cached files
        source_url – URL of meddra_all_se.tsv.gz
    """

    def __init__(self, data_dir: str, source_url: Optional[str] = None):
        super().__init__(data_dir)
        self.source_name = "sider"
        self.source_dir = self.data_dir / self.source_name
        self.source_dir.mkdir(parents=True, exist_ok=True)
        self.source_url = source_url or _DEFAULT_URL

    # ------------------------------------------------------------------
    # Download
    # ------------------------------------------------------------------

    def download_data(self) -> bool:
        logger.info("Downloading SIDER side effects from %s ...", self.source_url)
        gz_path = self.download_file(self.source_url, _GZ_FILENAME)
        if not gz_path:
            logger.error("Failed to download SIDER file.")
            return False
        extracted = self.extract_gzip(gz_path)
        if not extracted:
            logger.error("Failed to extract SIDER file.")
            return False
        return True

    # ------------------------------------------------------------------
    # Parse
    # ------------------------------------------------------------------

    def parse_data(self) -> Dict[str, pd.DataFrame]:
        tsv_path = self.source_dir / _FILENAME
        if not tsv_path.exists():
            logger.error("SIDER file not found: %s", tsv_path)
            return {}

        logger.info("Parsing SIDER from %s ...", tsv_path)

        try:
            df = pd.read_csv(
                tsv_path,
                sep="\t",
                header=None,
                names=_SIDER_COLS,
                dtype=str,
                low_memory=False,
            )
        except Exception as exc:
            logger.error("Failed to read SIDER file: %s", exc)
            return {}

        logger.info("SIDER raw: %d rows", len(df))

        # Keep only PT (preferred term) MedDRA entries to avoid duplicates
        if "meddra_type" in df.columns:
            df = df[df["meddra_type"] == "PT"].copy()
            logger.info("After PT filter: %d rows", len(df))

        df = df.dropna(subset=["stitch_flat", "side_effect_name"]).copy()

        # ---- SideEffect nodes ----
        se_df = (
            df[["umls_meddra", "side_effect_name"]]
            .drop_duplicates(subset=["umls_meddra"])
            .rename(columns={"umls_meddra": "umls_id", "side_effect_name": "side_effect_name"})
            .reset_index(drop=True)
        )
        se_df["source_database"] = "SIDER"
        logger.info("SIDER: %d side effect nodes", len(se_df))

        # ---- compoundCausesSideEffect edges ----
        # Convert STITCH IDs to PubChem CID format
        # STITCH flat IDs: CID1XXXXXXX (10-digit, 1 prefix = flat)
        assoc_df = df[["stitch_flat", "umls_meddra", "side_effect_name"]].copy()
        assoc_df["pubchem_cid"] = assoc_df["stitch_flat"].apply(self._stitch_to_pubchem)
        assoc_df = assoc_df.rename(columns={
            "umls_meddra": "umls_id",
        })
        assoc_df = assoc_df[["pubchem_cid", "stitch_flat", "umls_id", "side_effect_name"]].copy()
        assoc_df = assoc_df.drop_duplicates().reset_index(drop=True)
        assoc_df["source_database"] = "SIDER"
        logger.info("SIDER: %d drug-side effect associations", len(assoc_df))

        # ---- Drug nodes for all PubChem CIDs ----
        # Creates Drug nodes to ensure all SIDER compounds have matching nodes
        drug_df = assoc_df[["pubchem_cid", "stitch_flat"]].drop_duplicates()
        drug_df = drug_df[drug_df["pubchem_cid"] != ""].copy()
        drug_df = drug_df.rename(columns={"stitch_flat": "stitch_id"})
        drug_df["source_database"] = "SIDER"
        drug_df = drug_df.reset_index(drop=True)
        logger.info("SIDER: %d unique drug nodes (PubChem CID)", len(drug_df))

        return {
            SIDE_EFFECT_NODES: se_df,
            DRUG_SE_ASSOC:     assoc_df,
            SIDER_DRUG_NODES:  drug_df,
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _stitch_to_pubchem(stitch_id: str) -> str:
        """
        Convert a STITCH flat compound ID to a PubChem CID.

        STITCH flat IDs are 10-character zero-padded strings prefixed with
        'CID1' for the flat (non-stereo) form.  The PubChem CID is the
        integer after stripping the leading 'CID1' prefix and leading zeros.
        """
        if not stitch_id or not isinstance(stitch_id, str):
            return ""
        sid = stitch_id.strip()
        if sid.startswith("CID"):
            sid = sid[3:]
        # Remove leading zeros and the stereo/flat prefix digit
        try:
            cid = int(sid)
            # STITCH flat IDs have 1 as the first digit; remove it
            cid_str = str(cid)
            if len(cid_str) == 9 and cid_str.startswith("1"):
                return cid_str[1:].lstrip("0") or "0"
            return str(abs(cid))
        except ValueError:
            return sid

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    def get_schema(self) -> Dict[str, Dict[str, str]]:
        return {
            SIDE_EFFECT_NODES: {
                "umls_id":          "UMLS concept ID for the MedDRA side effect",
                "side_effect_name": "MedDRA side effect preferred term",
                "source_database":  "Source database (SIDER)",
            },
            DRUG_SE_ASSOC: {
                "pubchem_cid":      "PubChem Compound ID (converted from STITCH)",
                "stitch_flat":      "STITCH flat compound ID",
                "umls_id":          "UMLS concept ID for the side effect",
                "side_effect_name": "MedDRA side effect preferred term",
                "source_database":  "Source database (SIDER)",
            },
            SIDER_DRUG_NODES: {
                "pubchem_cid":      "PubChem Compound ID",
                "stitch_id":        "STITCH compound ID (original)",
                "source_database":  "Source database (SIDER)",
            },
        }
