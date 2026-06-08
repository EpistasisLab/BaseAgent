"""
NCBIGeneParser: Parser for NCBI Gene data.

NCBI Gene provides comprehensive gene information for multiple organisms.
For the knowledge graph, we focus on human genes (Homo sapiens, tax_id 9606).

Source: https://ftp.ncbi.nlm.nih.gov/gene/DATA/GENE_INFO/Mammalia/Homo_sapiens.gene_info.gz
"""

import logging
import pandas as pd

from typing import Dict, Optional
from pathlib import Path
from .base_parser import BaseParser

NCBI_GENES = "genes"

logger = logging.getLogger(__name__)

# Default URL — can be overridden via databases.yaml source_url arg
_DEFAULT_SOURCE_URL = (
    "https://ftp.ncbi.nlm.nih.gov/gene/DATA/GENE_INFO/Mammalia/"
    "Homo_sapiens.gene_info.gz"
)


class NCBIGeneParser(BaseParser):
    """
    Parser for NCBI Gene data.

    Downloads and parses human gene information from NCBI FTP.
    Extracts basic gene information and expands the dbXrefs cross-references
    into individual columns keyed by source database name.

    Constructor args (passed from databases.yaml via main.py):
        data_dir   – base directory for raw/cached files (injected by main.py)
        source_url – URL of the gzipped gene_info file (from databases.yaml args)

    Tissue/expression filtering is intentionally excluded; use BgeeParser.
    """

    # Columns to retain before expanding cross-references
    USEFUL_COLUMNS = [
        "GeneID",
        "Symbol",
        "Synonyms",
        "dbXrefs",
        "chromosome",
        "description",
        "type_of_gene",
        "Full_name_from_nomenclature_authority",
    ]

    def __init__(self, data_dir: str, source_url: Optional[str] = None):
        """
        Initialise the NCBI Gene parser.

        Args:
            data_dir:   Directory for storing raw/cached data files.
            source_url: URL of the gzipped gene_info TSV.  Defaults to the
                        official NCBI FTP path if not supplied.
        """
        super().__init__(data_dir)
        self.source_url: str = source_url or _DEFAULT_SOURCE_URL

        # Derive the local filenames from the URL so nothing is hardcoded
        gz_name = Path(self.source_url).name          # e.g. Homo_sapiens.gene_info.gz
        self._gz_filename = gz_name
        self._extracted_filename = gz_name[:-3] if gz_name.endswith(".gz") else gz_name

    # ------------------------------------------------------------------
    # Download
    # ------------------------------------------------------------------

    def download_data(self) -> bool:
        """
        Download the NCBI Gene gzipped TSV and extract it.

        Returns:
            True if the extracted file is available, False otherwise.
        """
        logger.info(f"Downloading NCBI Gene data from {self.source_url} ...")

        gz_path = self.download_file(self.source_url, self._gz_filename)
        if not gz_path:
            logger.error("Failed to download NCBI gene info file")
            return False

        extracted = self.extract_gzip(gz_path)
        if not extracted:
            logger.error("Failed to extract NCBI gene info file")
            return False

        return True

    # ------------------------------------------------------------------
    # Parse
    # ------------------------------------------------------------------

    def parse_data(self) -> Dict[str, pd.DataFrame]:
        """
        Parse the NCBI Gene TSV into a DataFrame of human gene records.

        Returns:
            ``{"genes": DataFrame}`` with expanded cross-reference columns,
            or an empty dict on failure.
        """
        logger.info("Parsing NCBI Gene data...")

        gene_info_path = Path(self.get_file_path(self._extracted_filename))
        if not gene_info_path.exists():
            logger.error(f"NCBI gene info file not found: {gene_info_path}")
            return {}

        # Official column order for the NCBI gene_info format
        all_columns = [
            "tax_id", "GeneID", "Symbol", "LocusTag", "Synonyms", "dbXrefs",
            "chromosome", "map_location", "description", "type_of_gene",
            "Symbol_from_nomenclature_authority",
            "Full_name_from_nomenclature_authority",
            "Nomenclature_status", "Other_designations",
            "Modification_date", "Feature_type",
        ]

        genes_df = self.read_tsv(
            str(gene_info_path),
            names=all_columns,
            skiprows=1,       # skip the header line (starts with #tax_id)
            low_memory=False,
        )

        if genes_df is None:
            logger.error("Failed to read NCBI gene info file")
            return {}

        # The species-specific file already contains only Homo sapiens, but
        # filter defensively in case the URL is ever changed to the full dump.
        genes_df = genes_df[genes_df["tax_id"] == 9606].copy()
        logger.info(f"Loaded {len(genes_df):,} human gene records (tax_id=9606)")

        # Retain only the columns needed downstream
        genes_df = genes_df[self.USEFUL_COLUMNS].copy()

        # Expand dbXrefs → one column per source database
        genes_df = self._expand_dbxrefs(genes_df)

        # Remove ENSG IDs from non-canonical gene entries (LOC/LINC, readthrough, uncharacterized, overlapping transcripts)
        if "xref_Ensembl" in genes_df.columns:
            genes_df = self._deduplicate_ensembl_ids(genes_df)

        # Provenance label
        genes_df["source_database"] = "NCBI Gene"

        logger.info(
            "Gene type distribution: "
            + str(genes_df["type_of_gene"].value_counts().to_dict())
        )

        return {NCBI_GENES: genes_df}

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    def get_schema(self) -> Dict[str, Dict[str, str]]:
        """Return column semantics for the ``genes`` table."""
        return {
            NCBI_GENES: {
                "GeneID":   "NCBI Gene ID (Entrez)",
                "Symbol":   "Official gene symbol",
                "Synonyms": "Pipe-delimited list of alternative gene symbols",
                "dbXrefs":  "Raw pipe-delimited cross-references string",
                "chromosome":  "Chromosome location",
                "description": "Gene description",
                "type_of_gene": "Gene type (protein-coding, ncRNA, etc.)",
                "Full_name_from_nomenclature_authority": "Official full gene name",
                "source_database": "Source database label",
                # xref_* columns are added dynamically from dbXrefs content
            }
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_xref_string(xref_str) -> dict:
        """
        Parse a single dbXrefs field value into ``{source: identifier}``.

        The field is a ``|``-delimited list of ``SourceDB:Identifier`` entries.
        The source is the token before the *first* colon; everything after is
        the identifier (which may itself contain colons, e.g. ``HGNC:HGNC:5``).

        Missing / empty values (NaN or the literal ``-``) return ``{}``.

        Example::

            "MIM:138670|HGNC:HGNC:5|Ensembl:ENSG00000121410"
            → {"MIM": "138670", "HGNC": "HGNC:5", "Ensembl": "ENSG00000121410"}
        """
        if pd.isna(xref_str) or str(xref_str).strip() in ("", "-"):
            return {}
        result: dict = {}
        for entry in str(xref_str).split("|"):
            entry = entry.strip()
            if ":" not in entry:
                continue
            source, _, identifier = entry.partition(":")
            source = source.strip()
            identifier = identifier.strip()
            if source:
                result[source] = identifier
        return result

    def _deduplicate_ensembl_ids(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Unconditionally clear xref_Ensembl from non-canonical gene entries:

        - Symbol matches ``LOC\\d+`` or ``LINC\\d+``
        - Description contains "uncharacterized" or "readthrough"
        - Symbol ends with an antisense/overlapping-transcript suffix
          (``-AS\\d+``, ``-OT\\d+``, ``-IT\\d+``)
        """
        ensg_col = "xref_Ensembl"
        symbol_col = "Symbol"
        desc_col = "description"

        desc = df[desc_col].fillna("").str.strip()
        is_loc           = df[symbol_col].str.fullmatch(r"LOC\d+|LINC\d+", na=False)
        is_readthrough   = desc.str.contains("readthrough", case=False)
        is_uncharacterized = desc.str.contains("uncharacterized", case=False)
        is_overlap       = df[symbol_col].str.contains(r"-(?:AS|OT|IT)\d+$", na=False)
        is_secondary     = is_loc | is_readthrough | is_uncharacterized | is_overlap

        to_clear = is_secondary & df[ensg_col].notna()
        df.loc[to_clear, ensg_col] = None

        logger.info(f"Cleared xref_Ensembl from {to_clear.sum()} non-canonical gene(s)")
        return df

    def _expand_dbxrefs(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Expand the ``dbXrefs`` column into one column per source database.

        Column names are prefixed with ``xref_`` (e.g. ``xref_Ensembl``,
        ``xref_HGNC``, ``xref_MIM``).  Rows with no entry for a given source
        get ``NaN``.

        Args:
            df: DataFrame containing a ``dbXrefs`` column.

        Returns:
            DataFrame with additional ``xref_*`` columns appended.
        """
        logger.info("Expanding dbXrefs into individual cross-reference columns...")

        xref_dicts = df["dbXrefs"].apply(self._parse_xref_string)
        xref_df = pd.DataFrame(list(xref_dicts), index=df.index)

        if xref_df.empty:
            logger.warning("No cross-references found in dbXrefs column")
            return df

        xref_df.columns = [f"xref_{col}" for col in xref_df.columns]
        logger.info(
            f"Extracted {len(xref_df.columns)} cross-reference source(s): "
            f"{sorted(xref_df.columns)}"
        )

        return pd.concat([df, xref_df], axis=1)
