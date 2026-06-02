"""
OpenTargets Platform Parser for the knowledge graph.

Uses the OpenTargets GraphQL API to retrieve target-disease associations
filtered to cardiovascular diseases from config/project.yaml.

API: https://api.platform.opentargets.org/api/v4/graphql

Output:
  - target_disease_associations.tsv : geneAssociatesWithDisease edges
    Columns: target_id, gene_symbol, gene_name, disease_id, disease_name,
             overall_score, efo_id, source_database
"""

import logging
import time
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd
import requests

from .base_parser import BaseParser
from config_loader import get_disease_scope
from id_mappings import IDMapper

logger = logging.getLogger(__name__)

_GRAPHQL_URL = "https://api.platform.opentargets.org/api/v4/graphql"

_DEFAULT_BASE_URL = (
    "https://ftp.ebi.ac.uk/pub/databases/opentargets/platform/latest/output/etl/parquet/"
)

TARGET_DISEASE_OUTPUT = "target_disease_associations"

_MIN_SCORE_DEFAULT = 0.1
_PAGE_SIZE = 500
_CALL_DELAY = 0.25
_MAX_PAGES_PER_DISEASE = 10

# Broad CVD search terms to maximize EFO disease discovery
_SEARCH_TERMS = [
    "heart failure",
    "coronary artery disease",
    "atrial fibrillation",
    "cardiomyopathy",
    "hypertension",
    "myocardial infarction",
    "stroke",
    "arrhythmia",
    "aortic aneurysm",
    "valvular heart disease",
    "congenital heart disease",
    "pulmonary hypertension",
    "peripheral arterial disease",
    "ventricular tachycardia",
    "heart block",
    "atherosclerosis",
    "cardiac arrest",
    "endocarditis",
    "pericarditis",
    "deep vein thrombosis",
    "pulmonary embolism",
    "angina",
    "aortic stenosis",
    "mitral valve",
    "myocarditis",
    "heart defect",
    "vascular disease",
    "cardiovascular",
    "coronary syndrome",
    "ischemic heart",
]


class OpenTargetsParser(BaseParser):
    """
    Parser for OpenTargets Platform target-disease associations.

    Queries the OpenTargets GraphQL API for cardiovascular disease associations,
    using broad search terms to discover EFO IDs, then maps them to DOID
    using the enhanced IDMapper (OBO + parquet-derived mappings).

    Constructor args (injected from databases.yaml):
        data_dir          – base directory for raw/cached files
        base_url          – kept for compat
        source_url        – kept for compat
        disease_scope     – disease scope dict (injected by main.py)
        min_score         – minimum association score to include
        max_parquet_files – kept for compat
    """

    def __init__(
        self,
        data_dir: str,
        base_url: Optional[str] = None,
        source_url: Optional[str] = None,
        disease_scope: Optional[Dict] = None,
        min_score: float = _MIN_SCORE_DEFAULT,
        max_parquet_files: int = 5,
    ):
        super().__init__(data_dir)
        self.source_name = "opentargets"
        self.source_dir = self.data_dir / self.source_name
        self.source_dir.mkdir(parents=True, exist_ok=True)

        self._min_score = float(min_score)
        self._max_parquet_files = max_parquet_files

        _scope = disease_scope if disease_scope else get_disease_scope()
        self._primary_terms = [t.lower() for t in _scope.get("primary_terms", [])]

    # ------------------------------------------------------------------
    # Download
    # ------------------------------------------------------------------

    def download_data(self) -> bool:
        """Data fetched via GraphQL API in parse_data(); no pre-download needed."""
        return True

    # ------------------------------------------------------------------
    # Parse
    # ------------------------------------------------------------------

    def parse_data(self) -> Dict[str, pd.DataFrame]:
        """
        Query OpenTargets GraphQL API for cardiovascular disease associations.

        1. Discover EFO disease IDs using broad search terms (no strict filter)
        2. Fetch target associations for each disease
        3. Map EFO/MONDO IDs to DOID using enhanced IDMapper
        """
        # Step 1: Discover all CVD-related EFO disease IDs
        logger.info("Querying OpenTargets for cardiovascular disease IDs ...")
        disease_ids = self._discover_disease_ids()
        if not disease_ids:
            logger.warning("No OpenTargets disease IDs found for disease scope.")
            return {}

        logger.info("OpenTargets: found %d matching disease IDs", len(disease_ids))

        # Step 2: Fetch associations for each disease
        all_rows: List[dict] = []
        seen_pairs = set()

        for disease_id, disease_name in disease_ids[:50]:
            rows = self._fetch_associations_for_disease(disease_id, disease_name)
            new_rows = 0
            for r in rows:
                pair = (r["target_id"], r["disease_id"])
                if pair not in seen_pairs:
                    seen_pairs.add(pair)
                    all_rows.append(r)
                    new_rows += 1
            if new_rows:
                logger.info("  %s (%s): %d associations (total: %d)",
                            disease_name, disease_id, new_rows, len(all_rows))
            time.sleep(_CALL_DELAY)

        if not all_rows:
            logger.warning("No OpenTargets associations returned.")
            return {}

        df = pd.DataFrame(all_rows)
        df["source_database"] = "OpenTargets"

        # Step 3: Map EFO/MONDO disease IDs to DOID
        logger.info("Mapping EFO/MONDO disease IDs to DOID...")
        base_data_dir = self.data_dir.parent  # data/raw → data/
        mapper = IDMapper(str(base_data_dir))
        processed_dir = base_data_dir / "processed"
        if processed_dir.exists():
            mapper.load_all_mappings(processed_dir)

        original_count = len(df)
        df["efo_id"] = df["disease_id"]
        df["doid"] = df["disease_id"].apply(mapper.map_to_doid)

        mapped_df = df[df["doid"].notna()].copy()
        mapped_df["disease_id"] = mapped_df["doid"]
        mapped_df = mapped_df.drop(columns=["doid"])

        unmapped_efo = df[df["doid"].isna()]["efo_id"].unique()
        mapped_count = len(mapped_df)
        logger.info("OpenTargets EFO→DOID mapping: %d/%d (%.1f%%) successfully mapped",
                    mapped_count, original_count, 100.0 * mapped_count / max(original_count, 1))
        if len(unmapped_efo) > 0:
            logger.info("  %d unmapped EFO IDs (sample: %s)",
                        len(unmapped_efo), list(unmapped_efo[:5]))

        if mapped_df.empty:
            logger.warning("No OpenTargets associations after DOID mapping.")
            return {}

        mapped_df = mapped_df.sort_values("overall_score", ascending=False).reset_index(drop=True)

        logger.info("OpenTargets: %d target-disease associations (score >= %.2f)",
                    len(mapped_df), self._min_score)
        return {TARGET_DISEASE_OUTPUT: mapped_df}

    # ------------------------------------------------------------------
    # GraphQL helpers
    # ------------------------------------------------------------------

    def _gql(self, query: str, variables: dict) -> Optional[dict]:
        """Execute a GraphQL query and return the data dict."""
        try:
            resp = requests.post(
                _GRAPHQL_URL,
                json={"query": query, "variables": variables},
                timeout=60,
            )
            resp.raise_for_status()
            result = resp.json()
            if "errors" in result:
                logger.debug("GraphQL errors: %s", result["errors"])
                return None
            return result.get("data")
        except Exception as exc:
            logger.warning("OpenTargets GraphQL error: %s", exc)
            return None

    def _discover_disease_ids(self) -> List[tuple]:
        """
        Search OpenTargets for disease IDs matching CVD search terms.
        Accepts ALL search results (no strict name-matching filter).
        Returns list of (efo_id, disease_name) tuples.
        """
        search_query = """
        query SearchDisease($term: String!) {
          search(queryString: $term, entityNames: ["disease"], page: {index: 0, size: 25}) {
            hits {
              id
              name
            }
          }
        }
        """

        seen_ids: set = set()
        results: List[tuple] = []

        for term in _SEARCH_TERMS:
            data = self._gql(search_query, {"term": term})
            if not data:
                continue
            for hit in data.get("search", {}).get("hits", []):
                eid = hit.get("id", "")
                ename = hit.get("name", "")
                if eid and eid not in seen_ids:
                    seen_ids.add(eid)
                    results.append((eid, ename))
            time.sleep(_CALL_DELAY)

        logger.info("OpenTargets: discovered %d unique disease IDs from %d search terms",
                    len(results), len(_SEARCH_TERMS))
        return results

    def _fetch_associations_for_disease(
        self, disease_id: str, disease_name: str
    ) -> List[dict]:
        """
        Fetch target-disease associations for a single disease using
        page-based pagination.
        """
        assoc_query = """
        query DiseaseAssociations($efoId: String!, $index: Int!, $size: Int!) {
          disease(efoId: $efoId) {
            associatedTargets(page: {index: $index, size: $size}) {
              count
              rows {
                target {
                  id
                  approvedSymbol
                  approvedName
                }
                score
              }
            }
          }
        }
        """

        rows: List[dict] = []
        page_index = 0

        while page_index < _MAX_PAGES_PER_DISEASE:
            data = self._gql(assoc_query, {
                "efoId": disease_id,
                "index": page_index,
                "size": _PAGE_SIZE,
            })
            if not data:
                break

            disease_data = (data.get("disease") or {})
            assoc = disease_data.get("associatedTargets", {})
            batch = assoc.get("rows", [])
            if not batch:
                break

            for row in batch:
                target = row.get("target", {})
                score = float(row.get("score", 0.0))
                if score < self._min_score:
                    continue
                target_id = target.get("id", "")
                if target_id:
                    rows.append({
                        "target_id":    target_id,
                        "gene_symbol":  target.get("approvedSymbol", ""),
                        "gene_name":    target.get("approvedName", ""),
                        "disease_id":   disease_id,
                        "disease_name": disease_name,
                        "overall_score": score,
                    })

            page_index += 1
            if len(batch) < _PAGE_SIZE:
                break
            time.sleep(_CALL_DELAY)

        return rows

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    def get_schema(self) -> Dict[str, Dict[str, str]]:
        return {
            TARGET_DISEASE_OUTPUT: {
                "target_id":     "Ensembl gene ID (ENSG)",
                "gene_symbol":   "HGNC gene symbol",
                "gene_name":     "Gene full name",
                "disease_id":    "DOID disease identifier (mapped from EFO)",
                "efo_id":        "Original EFO disease identifier",
                "disease_name":  "Disease name",
                "overall_score": "OpenTargets overall association score (0-1)",
                "source_database": "Source database (OpenTargets)",
            },
        }
