"""
SIDER (Side Effect Resource) Parser for the knowledge graph.

Downloads two SIDER bulk files and produces one clean TSV file:

  chemical_causes_effect.tsv  — chemicalCausesEffect edges (drug → side effect)

Data Sources:
  http://sideeffects.embl.de/media/download/meddra_all_se.tsv.gz
  http://sideeffects.embl.de/media/download/meddra.tsv.gz

Processing:
  - meddra_all_se: filter to PT (Preferred Term) concept type
  - meddra cross-reference: filter to PT, join on umls_cui to get numeric MedDRA IDs
  - PubChem CID derived by stripping the "CID1" prefix from STITCH flat ID
    and removing leading zeros (STITCH uses CID1XXXXXXXX where XXXXXXXX is the
    zero-padded 8-digit PubChem CID).
  - Edges cross-reference Drug nodes via xrefPubchemCID and ChemicalEffect nodes
    via xrefMedDRA (populated by DrugCentral).
"""

import logging
from typing import Dict

import pandas as pd

from .base_parser import BaseParser

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Output table names (= TSV filename stems)
# ---------------------------------------------------------------------------
EDGES = "chemical_causes_effect"


class SIDERParser(BaseParser):
    """
    Parser for SIDER 4.1 drug–side-effect associations.

    Produces chemicalCausesEffect edges cross-referenced by PubChem CID (Drug)
    and numeric MedDRA ID (ChemicalEffect). No credentials required.
    """

    _SE_URL = "http://sideeffects.embl.de/media/download/meddra_all_se.tsv.gz"
    _MEDDRA_URL = "http://sideeffects.embl.de/media/download/meddra.tsv.gz"

    _SE_FILENAME = "meddra_all_se.tsv.gz"
    _MEDDRA_FILENAME = "meddra.tsv.gz"

    _SE_COLS = [
        "stitch_id_flat",
        "stitch_id_stereo",
        "umls_label",
        "meddra_concept_type",
        "umls_cui",
        "side_effect_name",
    ]
    _MEDDRA_COLS = ["umls_cui", "meddra_concept_type", "meddra_id", "meddra_name"]

    # ------------------------------------------------------------------
    # Download
    # ------------------------------------------------------------------

    def download_data(self) -> bool:
        """Download SIDER source files."""
        logger.info("Downloading SIDER meddra_all_se …")
        if not self.download_file(self._SE_URL, self._SE_FILENAME):
            logger.error("Failed to download SIDER side-effect file.")
            return False

        logger.info("Downloading SIDER meddra cross-reference …")
        if not self.download_file(self._MEDDRA_URL, self._MEDDRA_FILENAME):
            logger.error("Failed to download SIDER meddra cross-reference file.")
            return False

        return True

    # ------------------------------------------------------------------
    # Parse
    # ------------------------------------------------------------------

    def parse_data(self) -> Dict[str, pd.DataFrame]:
        """
        Parse SIDER files and return one DataFrame:
          - chemical_causes_effect
        """
        se_path = self.get_file_path(self._SE_FILENAME)
        meddra_path = self.get_file_path(self._MEDDRA_FILENAME)

        # ---- Load meddra_all_se ----
        logger.info("Parsing SIDER side effects from %s …", se_path)
        try:
            df_se = pd.read_csv(
                se_path,
                sep="\t",
                compression="gzip",
                header=None,
                names=self._SE_COLS,
                low_memory=False,
                dtype=str,
            )
        except Exception as exc:
            logger.exception("Failed to read SIDER side-effect file: %s", exc)
            return {}

        logger.info("Loaded %d raw side-effect rows.", len(df_se))

        # ---- Load meddra cross-reference ----
        logger.info("Parsing SIDER meddra cross-reference from %s …", meddra_path)
        try:
            df_meddra = pd.read_csv(
                meddra_path,
                sep="\t",
                compression="gzip",
                header=None,
                names=self._MEDDRA_COLS,
                low_memory=False,
                dtype=str,
            )
        except Exception as exc:
            logger.exception("Failed to read SIDER meddra cross-reference file: %s", exc)
            return {}

        logger.info("Loaded %d meddra cross-reference rows.", len(df_meddra))

        # ---- Filter to Preferred Terms (PT) only ----
        df_se = df_se[df_se["meddra_concept_type"] == "PT"].copy()
        logger.info("Side-effect rows after PT filter: %d", len(df_se))

        df_meddra_pt = df_meddra[df_meddra["meddra_concept_type"] == "PT"].copy()
        logger.info("MedDRA cross-reference rows after PT filter: %d", len(df_meddra_pt))

        # ---- Drop rows missing essential identifiers ----
        df_se = df_se.dropna(subset=["stitch_id_flat", "umls_cui"])
        df_se["stitch_id_flat"] = df_se["stitch_id_flat"].str.strip()
        df_se["umls_cui"] = df_se["umls_cui"].str.strip()

        df_meddra_pt = df_meddra_pt.dropna(subset=["umls_cui", "meddra_id"])
        df_meddra_pt["umls_cui"] = df_meddra_pt["umls_cui"].str.strip()
        df_meddra_pt["meddra_id"] = df_meddra_pt["meddra_id"].str.strip()
        df_meddra_pt = (
            df_meddra_pt[["umls_cui", "meddra_id"]]
            .drop_duplicates(subset=["umls_cui"])
        )

        # ==================================================================
        # chemical_causes_effect.tsv
        # ==================================================================
        # Derive PubChem CID from STITCH flat ID for cross-referencing Drug nodes
        edges = (
            df_se[["stitch_id_flat", "umls_cui"]]
            .drop_duplicates()
            .copy()
        )
        edges["pubchem_cid"] = edges["stitch_id_flat"].apply(self._stitch_to_pubchem)

        # Join meddra cross-reference to get numeric MedDRA ID for cross-referencing
        # ChemicalEffect nodes (populated by DrugCentral via xrefMedDRA)
        edges = edges.merge(df_meddra_pt, on="umls_cui", how="inner")

        edges = (
            edges[["pubchem_cid", "meddra_id"]]
            .drop_duplicates()
            .reset_index(drop=True)
        )
        edges["source_database"] = "SIDER"

        logger.info("chemicalCausesEffect edges: %d", len(edges))

        return {EDGES: edges}

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    def get_schema(self) -> Dict[str, Dict[str, str]]:
        """Return the column schema for each output table."""
        return {
            EDGES: {
                "pubchem_cid": (
                    "PubChem Compound ID derived from STITCH flat ID — cross-references "
                    "Drug nodes via xrefPubchemCID"
                ),
                "meddra_id": (
                    "Numeric MedDRA concept ID — cross-references ChemicalEffect nodes "
                    "via xrefMedDRA (populated by DrugCentral)"
                ),
                "source_database": "Source name string (SIDER)",
            },
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _stitch_to_pubchem(stitch_id: str) -> str:
        """
        Convert a STITCH flat compound ID to a PubChem CID string.

        STITCH flat IDs use the format CID1XXXXXXXX where XXXXXXXX is the
        zero-padded 8-digit PubChem CID.  Strip the "CID1" prefix and
        convert to an integer string to remove leading zeros.

        Examples:
            "CID100000001"  →  "1"
            "CID100002441"  →  "2441"
            "CID1XXXXXXXX"  →  "" (non-numeric suffix)
        """
        if not isinstance(stitch_id, str):
            return ""
        s = stitch_id.strip()
        if s.upper().startswith("CID1"):
            suffix = s[4:]
            try:
                return str(int(suffix))
            except ValueError:
                return ""
        return ""
