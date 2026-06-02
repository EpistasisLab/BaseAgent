"""
LINCS L1000 Parser for the knowledge graph.

Uses the Enrichr LINCS L1000 gene set libraries (via MaayanLab Enrichr API)
to retrieve compound perturbation gene expression signatures and produces:
  - compound_gene_up.tsv   : compoundUpregulatesGene edges
  - compound_gene_down.tsv : compoundDownregulatesGene edges

Data Source:
  Enrichr LINCS L1000 libraries:
    - LINCS_L1000_Chem_Pert_up   (upregulated genes per compound)
    - LINCS_L1000_Chem_Pert_down (downregulated genes per compound)

API: https://maayanlab.cloud/Enrichr/geneSetLibrary
"""

import logging
from typing import Dict, List, Optional

import pandas as pd
import requests

from .base_parser import BaseParser

logger = logging.getLogger(__name__)

_DEFAULT_BASE_URL = "https://maayanlab.cloud/sigcom-lincs"
_ENRICHR_BASE = "https://maayanlab.cloud/Enrichr"

COMPOUND_GENE_UP   = "compound_gene_up"
COMPOUND_GENE_DOWN = "compound_gene_down"

# Enrichr LINCS L1000 library names
_UP_LIBRARY   = "LINCS_L1000_Chem_Pert_up"
_DOWN_LIBRARY = "LINCS_L1000_Chem_Pert_down"

# Max signatures to process per library (to keep runtime reasonable)
_MAX_SIGS = 5000


class LINCSParser(BaseParser):
    """
    Parser for LINCS L1000 gene expression perturbation data.

    Downloads compound perturbation gene expression signatures from the
    Enrichr LINCS L1000 gene set libraries and extracts up- and
    down-regulated genes for each compound.

    Constructor args (injected from databases.yaml):
        data_dir – base directory for raw/cached files
        base_url – SigCom LINCS base URL (kept for API compatibility)
    """

    def __init__(
        self,
        data_dir: str,
        base_url: Optional[str] = None,
        source_url: Optional[str] = None,
        max_files: int = 100,
    ):
        super().__init__(data_dir)
        self.source_name = "lincs"
        self.source_dir = self.data_dir / self.source_name
        self.source_dir.mkdir(parents=True, exist_ok=True)
        self.base_url = (base_url or _DEFAULT_BASE_URL).rstrip("/")
        # source_url and max_files accepted for databases.yaml compatibility
        self.max_files = int(max_files)

    # ------------------------------------------------------------------
    # Download
    # ------------------------------------------------------------------

    def download_data(self) -> bool:
        """Download LINCS L1000 gene set libraries from Enrichr."""
        logger.info("Downloading LINCS L1000 gene set libraries from Enrichr ...")
        ok1 = self._download_library(_UP_LIBRARY, "lincs_up.txt")
        ok2 = self._download_library(_DOWN_LIBRARY, "lincs_down.txt")
        return ok1 or ok2

    def _download_library(self, library_name: str, filename: str) -> bool:
        """Download a single Enrichr gene set library as text."""
        filepath = self.source_dir / filename
        if filepath.exists() and not self.force:
            logger.info("Cached: %s", filepath)
            return True
        url = f"{_ENRICHR_BASE}/geneSetLibrary?mode=text&libraryName={library_name}"
        logger.info("Downloading %s from Enrichr ...", library_name)
        result = self.download_file(url, filename)
        return bool(result)

    # ------------------------------------------------------------------
    # Parse
    # ------------------------------------------------------------------

    def parse_data(self) -> Dict[str, pd.DataFrame]:
        """
        Parse Enrichr LINCS L1000 gene set library files.

        Each line format:
          <compound_signature_name>\\t<tab>\\t<gene1>\\t<gene2>\\t...
        """
        up_df   = self._parse_library("lincs_up.txt",   "up")
        down_df = self._parse_library("lincs_down.txt", "down")

        if up_df is None and down_df is None:
            logger.warning("No LINCS data parsed.")
            return {}

        result = {}
        if up_df is not None and not up_df.empty:
            result[COMPOUND_GENE_UP] = up_df
        else:
            result[COMPOUND_GENE_UP] = pd.DataFrame(
                columns=["compound_name", "cell_line", "time_point",
                         "gene_symbol", "direction", "source_database"]
            )
        if down_df is not None and not down_df.empty:
            result[COMPOUND_GENE_DOWN] = down_df
        else:
            result[COMPOUND_GENE_DOWN] = pd.DataFrame(
                columns=["compound_name", "cell_line", "time_point",
                         "gene_symbol", "direction", "source_database"]
            )

        logger.info("LINCS: %d upregulated edges, %d downregulated edges",
                    len(result[COMPOUND_GENE_UP]), len(result[COMPOUND_GENE_DOWN]))
        return result

    def _parse_library(self, filename: str, direction: str) -> Optional[pd.DataFrame]:
        """
        Parse an Enrichr gene set library file.

        Line format:
          <sig_name>\\t\\t<gene1>\\t<gene2>\\t...

        Signature name format (Enrichr LINCS):
          <compound> <cell_line> <time_point>-<compound>-<dose>
          e.g.: "CPC001 HA1E 24H-hemado-10.0"
        """
        filepath = self.source_dir / filename
        if not filepath.exists():
            logger.warning("LINCS library file not found: %s", filepath)
            return None

        logger.info("Parsing LINCS %s library from %s ...", direction, filepath)

        rows = []
        sig_count = 0

        with open(filepath, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if sig_count >= _MAX_SIGS:
                    break
                line = line.rstrip("\n")
                parts = line.split("\t")
                if len(parts) < 3:
                    continue

                sig_name = parts[0].strip()
                # Skip the empty second field (Enrichr format has double-tab)
                genes = [g.strip() for g in parts[2:] if g.strip()]

                if not sig_name or not genes:
                    continue

                # Parse compound name and cell line from signature name
                compound, cell_line, time_point = self._parse_sig_name(sig_name)

                for gene in genes:
                    rows.append({
                        "compound_name": compound,
                        "cell_line":     cell_line,
                        "time_point":    time_point,
                        "gene_symbol":   gene,
                        "direction":     direction,
                        "source_database": "LINCS L1000",
                    })

                sig_count += 1

        if not rows:
            logger.warning("No rows parsed from %s", filename)
            return None

        df = pd.DataFrame(rows)
        # Deduplicate: keep one edge per compound-gene pair
        df = df.drop_duplicates(subset=["compound_name", "gene_symbol"]).reset_index(drop=True)
        logger.info("LINCS %s: %d compound-gene edges (%d signatures)", direction, len(df), sig_count)
        return df

    @staticmethod
    def _parse_sig_name(sig_name: str):
        """
        Parse Enrichr LINCS signature name into (compound, cell_line, time_point).

        Format: "<compound_code> <cell_line> <time>-<compound_name>-<dose>"
        Example: "CPC001 HA1E 24H-hemado-10.0"
        """
        parts = sig_name.split(" ")
        compound = sig_name  # Default: use full name
        cell_line = ""
        time_point = ""

        if len(parts) >= 3:
            cell_line = parts[1] if len(parts) > 1 else ""
            time_info = parts[2] if len(parts) > 2 else ""
            # time_info format: "24H-compound_name-dose"
            time_parts = time_info.split("-")
            time_point = time_parts[0] if time_parts else ""
            # Extract compound name from time_info
            if len(time_parts) >= 2:
                compound = "-".join(time_parts[1:-1]) if len(time_parts) > 2 else time_parts[1]
            else:
                compound = parts[0]

        return compound, cell_line, time_point

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    def get_schema(self) -> Dict[str, Dict[str, str]]:
        return {
            COMPOUND_GENE_UP: {
                "compound_name":   "Compound/drug name",
                "cell_line":       "Cell line used in experiment",
                "time_point":      "Time point of measurement",
                "gene_symbol":     "Upregulated gene symbol",
                "direction":       "Direction of regulation (up)",
                "source_database": "Source database (LINCS L1000)",
            },
            COMPOUND_GENE_DOWN: {
                "compound_name":   "Compound/drug name",
                "cell_line":       "Cell line used in experiment",
                "time_point":      "Time point of measurement",
                "gene_symbol":     "Downregulated gene symbol",
                "direction":       "Direction of regulation (down)",
                "source_database": "Source database (LINCS L1000)",
            },
        }
