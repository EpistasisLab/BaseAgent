"""
DisGeNETParser: Parser for DisGeNET gene-disease association data.

DisGeNET is a comprehensive database of gene-disease associations
from various sources including literature and databases.

Source: https://www.disgenet.org/
New API: https://api.disgenet.com/api/v1/
API Documentation: https://api.disgenet.com/swagger-ui.html

Disease scope is configurable via the disease_scope parameter, which
is read from config/project.yaml by the pipeline.
"""

import logging
import os
import time
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd
import requests

from .base_parser import BaseParser
from config_loader import get_disease_scope

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Output DataFrame names (stems for TSV files under data/processed/disgenet/)
# These MUST match the source_filename values in config/ontology_mappings.yaml
# where applicable.
# ---------------------------------------------------------------------------
GENES_OUTPUT = "genes"                          # → genes.tsv
DISEASES_OUTPUT = "diseases"                    # → diseases.tsv  (ontology_mappings.yaml)
GDA_OUTPUT = "gene_disease_associations"        # → gene_disease_associations.tsv

# Raw cache file names written to data/raw/disgenet/
RAW_GDA_FILE = "api_gene_disease_associations.tsv"
RAW_DISEASES_FILE = "api_diseases.tsv"

API_BASE = "https://api.disgenet.com/api/v1"

VOCAB_COLS = ["MSH", "ICD10", "NCI", "OMIM", "ICD9CM", "HPO", "DO",
              "MONDO", "UMLS", "EFO", "ORDO"]

# Maps prefixes used in diseaseVocabularies entries to our VOCAB_COLS names.
# Only entries that differ need an explicit mapping (MESH → MSH).
_VOCAB_PREFIX_MAP = {
    "MESH": "MSH", "ICD10": "ICD10", "NCI": "NCI", "OMIM": "OMIM",
    "ICD9CM": "ICD9CM", "HPO": "HPO", "DO": "DO", "MONDO": "MONDO",
    "UMLS": "UMLS", "EFO": "EFO", "ORDO": "ORDO",
}


class DisGeNETParser(BaseParser):
    """
    Parser for DisGeNET gene-disease association data via REST API.

    Queries the DisGeNET REST API to retrieve gene-disease associations (GDAs)
    for diseases configured in config/project.yaml.  Disease scope is never
    hard-coded; it is read from the disease_scope parameter or from
    config/project.yaml via get_disease_scope().

    Outputs
    -------
    genes
        Gene nodes: geneId, geneSymbol, ensemblId, proteinId,
        pLI, DSI, DPI.
    diseases
        Disease nodes and cross-references: diseaseId, diseaseName,
        diseaseType, diseaseClass, diseaseSemanticType, MSH, ICD10, DO, …
    gene_disease_associations
        GDA edges: geneId, diseaseId, gdaScore, evidenceIndex,
        numberOfPublications, numberOfSnps.
    """

    def __init__(
        self,
        data_dir: str,
        api_key: Optional[str] = None,
        disease_scope: Optional[Dict] = None,
    ):
        """
        Parameters
        ----------
        data_dir:
            Directory for storing raw data files.
        api_key:
            DisGeNET API key.  Falls back to the DISGENET_API_KEY env var.
        disease_scope:
            Disease scope dict from project config (auto-injected by pipeline).
            Falls back to config/project.yaml via get_disease_scope().
        """
        super().__init__(data_dir)
        self.api_key = api_key or os.getenv("DISGENET_API_KEY")

        self.session = requests.Session()

        _cfg_scope = disease_scope if disease_scope else get_disease_scope()
        self.disease_terms: List[str] = _cfg_scope.get("primary_terms", [])
        self.umls_cuis: List[str] = _cfg_scope.get("umls_cuis", [])

        if self.api_key:
            self.session.headers.update({
                "Authorization": f"Bearer {self.api_key}",
                "accept": "application/json",
            })
            logger.info("DisGeNET API key configured; base URL: %s", API_BASE)
        else:
            logger.warning(
                "No DisGeNET API key provided — set DISGENET_API_KEY or pass api_key."
            )

        if not self.disease_terms and not self.umls_cuis:
            logger.warning(
                "No disease terms or UMLS CUIs in disease_scope; "
                "API queries will return nothing."
            )

    # ------------------------------------------------------------------
    # download_data
    # ------------------------------------------------------------------

    def download_data(self) -> bool:
        """
        Download GDA data from the DisGeNET REST API and derive disease files.

        Strategy
        --------
        1. Start with explicit umls_cuis from project.yaml.
        2. Search by primary_terms to discover additional disease CUIs.
        3. Fetch GDAs for every unique CUI (with pagination).
        4. Derive disease classification and mapping files from GDA data.

        Returns True when data is ready (freshly downloaded or cached).
        """
        if not self.api_key:
            logger.error("No API key — cannot download DisGeNET data.")
            return False

        raw_gda = self.get_file_path(RAW_GDA_FILE)

        raw_diseases = self.get_file_path(RAW_DISEASES_FILE)

        if (Path(raw_gda).exists() and Path(raw_diseases).exists()
                and not self.force):
            logger.info("DisGeNET raw files already present; skipping download.")
            return True

        # ---- Step 1: Collect disease CUIs --------------------------------
        all_cuis: List[str] = list(self.umls_cuis)

        if self.disease_terms:
            logger.info(
                "Searching for additional disease CUIs by term(s): %s",
                self.disease_terms,
            )
            term_cuis = self._search_disease_cuis(self.disease_terms)
            for cui in term_cuis:
                if cui not in all_cuis:
                    all_cuis.append(cui)

        if not all_cuis:
            logger.error(
                "No disease CUIs available. "
                "Check disease_scope.umls_cuis / primary_terms in project.yaml."
            )
            return False

        logger.info(
            "Will query GDAs for %d disease CUI(s): %s", len(all_cuis), all_cuis
        )

        # ---- Step 2: Fetch GDAs for each CUI -----------------------------
        all_gda_records: List[Dict] = []
        for cui in all_cuis:
            records = self._fetch_gdas_for_disease(cui)
            logger.info("  %s → %d GDA record(s)", cui, len(records))
            all_gda_records.extend(records)
            time.sleep(0.5)

        if not all_gda_records:
            logger.error(
                "No GDA records retrieved from DisGeNET API for disease(s): %s. ",
                all_cuis,
            )
            return False

        gda_df = pd.DataFrame(all_gda_records).drop_duplicates()
        gda_df.to_csv(raw_gda, sep="\t", index=False)
        logger.info("✓ Saved %d GDA records → %s", len(gda_df), raw_gda)

        # ---- Step 3: Combined disease file (classification + vocab mappings) ----
        disease_cols = [c for c in
                        ["diseaseId", "diseaseName", "diseaseType",
                         "diseaseClass", "diseaseSemanticType"] + VOCAB_COLS
                        if c in gda_df.columns]
        diseases_df = (gda_df[disease_cols].drop_duplicates(subset=["diseaseId"]).copy()
                       if "diseaseId" in disease_cols
                       else pd.DataFrame(columns=disease_cols))
        for col in VOCAB_COLS:
            if col not in diseases_df.columns:
                diseases_df[col] = None
        diseases_df.to_csv(raw_diseases, sep="\t", index=False)
        logger.info("✓ Saved %d disease records → %s", len(diseases_df), raw_diseases)

        return True

    # ------------------------------------------------------------------
    # API helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_vocab_list(vocab_list: Optional[List[str]]) -> Dict[str, Optional[str]]:
        """Parse a diseaseVocabularies list into a VOCAB_COLS dict (first code per vocab)."""
        codes: Dict[str, Optional[str]] = {col: None for col in VOCAB_COLS}
        for entry in (vocab_list or []):
            if "_" in entry:
                prefix, code = entry.split("_", 1)
                col = _VOCAB_PREFIX_MAP.get(prefix.upper())
                if col and codes[col] is None:
                    codes[col] = f"DOID:{code}" if col == "DO" else code
        return codes

    def _search_disease_cuis(self, terms: List[str]) -> List[str]:
        """Search for disease CUIs using GET /entity/disease."""
        cuis: List[str] = []
        for term in terms:
            endpoint = f"{API_BASE}/entity/disease"
            params = {"disease_free_text_search_string": term, "page_number": 0}
            try:
                resp = self.session.get(endpoint, params=params, timeout=30)
                resp.raise_for_status()
                if not resp.text.strip():
                    logger.warning(
                        "Disease search for '%s': HTTP %d with empty body "
                        "(check API key / Bearer token)",
                        term, resp.status_code,
                    )
                    continue
                data = resp.json()
                if data.get("status") != "OK":
                    logger.warning(
                        "Disease search for '%s': non-OK status '%s' — %s",
                        term, data.get("status"), resp.text[:200],
                    )
                    continue
                payload = data.get("payload", [])
                for item in payload:
                    cui = item.get("diseaseUMLSCUI", "")
                    if cui and cui not in cuis:
                        cuis.append(cui)
                logger.info("  '%s' → %d disease(s) found", term, len(payload))
                time.sleep(0.3)
            except requests.RequestException as exc:
                logger.warning("Disease search failed for '%s': %s", term, exc)
        return cuis

    def _fetch_gdas_for_disease(self, disease_cui: str) -> List[Dict]:
        """
        Fetch all GDA records for a disease CUI via GET /gda/summary.
        Handles pagination via paging.totalElements / paging.pageSize.
        """
        endpoint = f"{API_BASE}/gda/summary"
        all_records: List[Dict] = []
        page = 0

        while True:
            params = {"disease": f"UMLS_{disease_cui}", "page_number": page}
            try:
                resp = self.session.get(endpoint, params=params, timeout=60)

                if resp.status_code == 404:
                    logger.debug("No GDAs for %s (404)", disease_cui)
                    break
                if resp.status_code == 429:
                    logger.warning("Rate limited by DisGeNET; sleeping 10 s…")
                    time.sleep(10)
                    continue
                if resp.status_code == 403:
                    logger.warning(
                        "Access denied for %s (403) — academic accounts are "
                        "restricted to curated sources only",
                        disease_cui,
                    )
                    break

                resp.raise_for_status()
                if not resp.text.strip():
                    logger.error(
                        "GDA fetch for %s: HTTP %d with empty body "
                        "(check API key / Bearer token)",
                        disease_cui, resp.status_code,
                    )
                    break
                data = resp.json()

                if data.get("status") != "OK":
                    logger.warning(
                        "GDA fetch for %s: non-OK status '%s' — %s",
                        disease_cui, data.get("status"), resp.text[:200],
                    )
                    break

                paging = data.get("paging", {})
                payload = data.get("payload", [])
                if not payload:
                    break

                for item in payload:
                    all_records.append({
                        "geneId": item.get("geneNcbiID"),
                        "geneSymbol": item.get("symbolOfGene"),
                        "ensemblId": (item.get("geneEnsemblIDs") or [None])[0],
                        "proteinId": (item.get("geneProteinStrIDs") or [None])[0],
                        "DSI": item.get("geneDSI"),
                        "DPI": item.get("geneDPI"),
                        "pLI": item.get("genepLI"),
                        "diseaseId": item.get("diseaseUMLSCUI"),
                        "diseaseName": item.get("diseaseName"),
                        "diseaseType": item.get("diseaseType"),
                        "diseaseClass": "; ".join(item.get("diseaseClasses_MSH") or []) or None,
                        "diseaseSemanticType": "; ".join(item.get("diseaseClasses_UMLS_ST") or []) or None,
                        "gdaScore": item.get("score"),
                        "evidenceIndex": item.get("ei"),
                        "numberOfPublications": item.get("numPMIDs"),
                        **self._parse_vocab_list(item.get("diseaseVocabularies")),
                    })
                logger.debug("  %s page %d: %d record(s)", disease_cui, page, len(payload))

                total = paging.get("totalElements", 0)
                page_size = paging.get("pageSize", 100)
                if (page + 1) * page_size >= total:
                    break

                page += 1
                time.sleep(0.3)

            except requests.RequestException as exc:
                logger.error("Failed to fetch GDAs for %s: %s", disease_cui, exc)
                break

        return all_records

    # ------------------------------------------------------------------
    # parse_data
    # ------------------------------------------------------------------

    def parse_data(self) -> Dict[str, pd.DataFrame]:
        """
        Parse DisGeNET raw files into four clean DataFrames.

        Returns
        -------
        dict with keys:
          genes                       Gene nodes
          diseases                    Disease nodes and cross-references
          gene_disease_associations   GDA edges
        """
        logger.info("Parsing DisGeNET data…")

        # Load GDA data
        raw_gda = self.get_file_path(RAW_GDA_FILE)
        if not Path(raw_gda).exists():
            logger.warning("No raw GDA file found at %s", raw_gda)
            return {}

        id_cols = ["diseaseId", "geneId", "ensemblId", "proteinId"] + VOCAB_COLS
        str_dtypes = {col: str for col in id_cols}
        gda_df = self.read_tsv(raw_gda, dtype=str_dtypes)
        if gda_df is None or gda_df.empty:
            logger.warning("Raw GDA file is empty or unreadable.")
            return {}

        logger.info(
            "Loaded %d GDA record(s); columns: %s", len(gda_df), list(gda_df.columns)
        )

        result: Dict[str, pd.DataFrame] = {
            GENES_OUTPUT: self._build_gene_nodes(gda_df),
            DISEASES_OUTPUT: self._build_disease_nodes(gda_df),
            GDA_OUTPUT: self._build_gda_edges(gda_df),
        }

        for df in result.values():
            df["source_database"] = "DisGeNET"

        for key, df in result.items():
            logger.info("  %s: %d rows × %d cols", key, len(df), len(df.columns))

        return result

    # ------------------------------------------------------------------
    # DataFrame builders
    # ------------------------------------------------------------------

    def _build_gene_nodes(self, gda_df: pd.DataFrame) -> pd.DataFrame:
        col_order = ["geneId", "geneSymbol", "ensemblId",
                     "proteinId", "pLI", "DSI", "DPI"]
        present = [c for c in col_order if c in gda_df.columns]
        if "geneId" not in present:
            logger.warning("No gene-level columns found in GDA data.")
            return pd.DataFrame(columns=col_order)
        genes = gda_df[present].drop_duplicates(subset=["geneId"]).copy()
        for col in col_order:
            if col not in genes.columns:
                genes[col] = None
        return genes[col_order].reset_index(drop=True)

    def _build_disease_nodes(self, gda_df: pd.DataFrame) -> pd.DataFrame:
        cols = (["diseaseId", "diseaseName", "diseaseType", "diseaseClass",
                 "diseaseSemanticType"] + VOCAB_COLS)
        if "diseaseId" not in gda_df.columns:
            return pd.DataFrame(columns=cols)
        present = [c for c in cols if c in gda_df.columns]
        diseases = gda_df[present].drop_duplicates(subset=["diseaseId"]).copy()
        for col in cols:
            if col not in diseases.columns:
                diseases[col] = None
        # Replace pandas NA strings from dtype=str reads with actual None
        diseases.replace("nan", None, inplace=True)
        # Ensure DO values carry the DOID: prefix (raw files may predate this convention)
        if "DO" in diseases.columns:
            diseases["DO"] = diseases["DO"].apply(
                lambda v: f"DOID:{v}" if pd.notna(v) and not str(v).startswith("DOID:") else v
            )
        return diseases[cols].reset_index(drop=True)

    def _build_gda_edges(self, gda_df: pd.DataFrame) -> pd.DataFrame:
        cols = ["geneId", "diseaseId", "gdaScore",
                "evidenceIndex", "numberOfPublications", "numberOfSnps"]
        edges = gda_df[[c for c in cols if c in gda_df.columns]].copy()
        for col in cols:
            if col not in edges.columns:
                edges[col] = None
        return edges[cols].reset_index(drop=True)

    # ------------------------------------------------------------------
    # get_schema
    # ------------------------------------------------------------------

    def get_schema(self) -> Dict[str, Dict[str, str]]:
        """Return the column schema for all DisGeNET output DataFrames."""
        return {
            GENES_OUTPUT: {
                "geneId": "NCBI Gene ID",
                "geneSymbol": "HGNC gene symbol",
                "ensemblId": "Ensembl gene identifier",
                "proteinId": "UniProt protein identifier",
                "pLI": "Probability of loss-of-function intolerance (gnomAD)",
                "DSI": "Disease Specificity Index (0–1; higher = more disease-specific)",
                "DPI": "Disease Pleiotropy Index (0–1; higher = more disease classes)",
            },
            DISEASES_OUTPUT: {
                "diseaseId": "Disease identifier (UMLS CUI)",
                "diseaseName": "Disease name",
                "diseaseType": "Disease type (disease, group, phenotype)",
                "diseaseClass": "Disease class (MeSH hierarchy code)",
                "diseaseSemanticType": "UMLS semantic type",
                "MSH": "MeSH code",
                "ICD10": "ICD-10 code",
                "NCI": "NCI Thesaurus code",
                "OMIM": "OMIM identifier",
                "ICD9CM": "ICD-9-CM code",
                "HPO": "Human Phenotype Ontology code",
                "DO": "Disease Ontology identifier (DOID:XXXXXXX format)",
                "MONDO": "MONDO identifier",
                "UMLS": "UMLS CUI cross-reference",
                "EFO": "Experimental Factor Ontology code",
                "ORDO": "Orphanet code",
            },
            GDA_OUTPUT: {
                "geneId": "NCBI Gene ID",
                "diseaseId": "Disease identifier (UMLS CUI)",
                "gdaScore": "GDA score (0–1)",
                "evidenceIndex": "Evidence Index (0–1; proportion of supporting evidence)",
                "numberOfPublications": "Number of supporting PubMed publications",
                "numberOfSnps": "Number of associated SNPs",
            },
        }
