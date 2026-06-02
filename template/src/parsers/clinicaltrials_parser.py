"""
ClinicalTrials.gov Parser for the knowledge graph.

Queries the ClinicalTrials.gov REST API v2 for studies related to
cardiovascular diseases (using disease terms from config/project.yaml)
and produces:
  - trial_nodes.tsv                  : ClinicalTrial nodes
  - trial_disease_associations.tsv   : STUDIES_CONDITION edges
  - trial_intervention_associations.tsv : TESTS_INTERVENTION edges

API: https://clinicaltrials.gov/api/v2/studies
"""

import logging
import time
from typing import Dict, List, Optional

import pandas as pd
import requests

from .base_parser import BaseParser
from config_loader import get_disease_scope

logger = logging.getLogger(__name__)

_DEFAULT_BASE_URL = "https://clinicaltrials.gov/api/v2/studies"

TRIAL_NODES    = "trial_nodes"
TRIAL_DISEASE  = "trial_disease_associations"
TRIAL_INTERV   = "trial_intervention_associations"

# Max results per API page
_PAGE_SIZE = 1000
# Max pages to fetch per search term (to avoid excessive API calls)
_MAX_PAGES = 10
# Delay between API calls (seconds) to be polite
_CALL_DELAY = 0.3


class ClinicalTrialsParser(BaseParser):
    """
    Parser for ClinicalTrials.gov REST API v2.

    Queries for studies related to cardiovascular disease terms from
    config/project.yaml and produces ClinicalTrial nodes plus
    STUDIES_CONDITION and TESTS_INTERVENTION relationship edges.

    Constructor args (injected from databases.yaml):
        data_dir      – base directory for raw/cached files
        base_url      – ClinicalTrials.gov API v2 base URL
        disease_filter – whether to filter by disease scope (bool)
        disease_scope  – disease scope dict (injected by main.py)
    """

    def __init__(
        self,
        data_dir: str,
        base_url: Optional[str] = None,
        disease_filter: bool = True,
        disease_scope: Optional[Dict] = None,
        max_pages: int = 10,
        page_size: int = 1000,
        call_delay: float = 0.3,
    ):
        super().__init__(data_dir)
        self.source_name = "clinicaltrials"
        self.source_dir = self.data_dir / self.source_name
        self.source_dir.mkdir(parents=True, exist_ok=True)

        self.base_url = (base_url or _DEFAULT_BASE_URL).rstrip("/")
        self.disease_filter = disease_filter
        self._max_pages = max_pages
        self._page_size = page_size
        self._call_delay = call_delay

        _scope = disease_scope if disease_scope else get_disease_scope()
        self._primary_terms: List[str] = _scope.get("primary_terms", [])

    # ------------------------------------------------------------------
    # Download
    # ------------------------------------------------------------------

    def download_data(self) -> bool:
        """Data is fetched via API in parse_data(); no pre-download needed."""
        return True

    # ------------------------------------------------------------------
    # Parse
    # ------------------------------------------------------------------

    def parse_data(self) -> Dict[str, pd.DataFrame]:
        """
        Query ClinicalTrials.gov API v2 for each primary disease term,
        collect unique studies, and return node/edge DataFrames.
        """
        if not self._primary_terms:
            logger.error("No primary_terms in disease_scope; cannot query ClinicalTrials.")
            return {}

        # Use a representative subset of terms to avoid excessive API calls
        # (many terms are synonymous; the API does substring matching)
        search_terms = self._select_search_terms()
        logger.info("ClinicalTrials: querying %d search terms ...", len(search_terms))

        all_studies: Dict[str, dict] = {}  # nct_id -> study dict

        for term in search_terms:
            studies = self._fetch_studies_for_term(term)
            for s in studies:
                nct_id = s.get("nct_id", "")
                if nct_id and nct_id not in all_studies:
                    all_studies[nct_id] = s
            logger.info("  '%s': %d studies (total unique: %d)", term, len(studies), len(all_studies))

        if not all_studies:
            logger.warning("No ClinicalTrials studies found.")
            return {}

        studies_list = list(all_studies.values())

        # ---- Trial nodes ----
        trial_rows = []
        disease_rows = []
        interv_rows = []

        for s in studies_list:
            nct_id = s.get("nct_id", "")
            trial_rows.append({
                "nct_id":          nct_id,
                "brief_title":     s.get("brief_title", ""),
                "official_title":  s.get("official_title", ""),
                "status":          s.get("status", ""),
                "phase":           s.get("phase", ""),
                "study_type":      s.get("study_type", ""),
                "start_date":      s.get("start_date", ""),
                "completion_date": s.get("completion_date", ""),
                "sponsor":         s.get("sponsor", ""),
                "enrollment":      s.get("enrollment", ""),
                "source_database": "ClinicalTrials",
            })
            for cond in s.get("conditions", []):
                disease_rows.append({
                    "nct_id":          nct_id,
                    "condition":       cond,
                    "source_database": "ClinicalTrials",
                })
            for interv in s.get("interventions", []):
                interv_rows.append({
                    "nct_id":              nct_id,
                    "intervention_name":   interv.get("name", ""),
                    "intervention_type":   interv.get("type", ""),
                    "source_database":     "ClinicalTrials",
                })

        trial_df   = pd.DataFrame(trial_rows).drop_duplicates(subset=["nct_id"]).reset_index(drop=True)
        disease_df = pd.DataFrame(disease_rows).drop_duplicates().reset_index(drop=True)
        interv_df  = pd.DataFrame(interv_rows).drop_duplicates().reset_index(drop=True)

        logger.info(
            "ClinicalTrials: %d trials | %d disease edges | %d intervention edges",
            len(trial_df), len(disease_df), len(interv_df),
        )

        return {
            TRIAL_NODES:   trial_df,
            TRIAL_DISEASE: disease_df,
            TRIAL_INTERV:  interv_df,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _select_search_terms(self) -> List[str]:
        """
        Select a representative subset of primary terms to query.
        Avoids redundant queries for very similar terms.
        """
        # Use up to 20 terms; prefer shorter/broader terms first
        sorted_terms = sorted(self._primary_terms, key=len)
        # Deduplicate terms that are substrings of shorter ones
        selected = []
        seen_lower = set()
        for term in sorted_terms:
            tl = term.lower()
            if not any(tl in s for s in seen_lower):
                selected.append(term)
                seen_lower.add(tl)
            if len(selected) >= 20:
                break
        return selected

    def _fetch_studies_for_term(self, term: str) -> List[dict]:
        """Fetch all studies for a single search term via paginated API."""
        studies = []
        next_page_token = None
        page = 0

        while page < _MAX_PAGES:
            params = {
                "query.cond": term,
                "pageSize": _PAGE_SIZE,
                "format": "json",
                "fields": (
                    "NCTId,BriefTitle,OfficialTitle,OverallStatus,Phase,"
                    "StudyType,StartDate,CompletionDate,LeadSponsorName,"
                    "EnrollmentCount,Condition,InterventionName,InterventionType"
                ),
            }
            if next_page_token:
                params["pageToken"] = next_page_token

            try:
                resp = requests.get(self.base_url, params=params, timeout=60)
                resp.raise_for_status()
                data = resp.json()
            except Exception as exc:
                logger.warning("ClinicalTrials API error for '%s': %s", term, exc)
                break

            for study in data.get("studies", []):
                parsed = self._parse_study(study)
                if parsed:
                    studies.append(parsed)

            next_page_token = data.get("nextPageToken")
            if not next_page_token:
                break

            page += 1
            time.sleep(_CALL_DELAY)

        return studies

    @staticmethod
    def _parse_study(study: dict) -> Optional[dict]:
        """Extract relevant fields from a ClinicalTrials API v2 study record."""
        try:
            proto = study.get("protocolSection", {})
            id_mod  = proto.get("identificationModule", {})
            stat_mod = proto.get("statusModule", {})
            design_mod = proto.get("designModule", {})
            cond_mod = proto.get("conditionsModule", {})
            interv_mod = proto.get("armsInterventionsModule", {})
            sponsor_mod = proto.get("sponsorCollaboratorsModule", {})

            nct_id = id_mod.get("nctId", "")
            if not nct_id:
                return None

            # Interventions
            interventions = []
            for interv in interv_mod.get("interventions", []):
                interventions.append({
                    "name": interv.get("name", ""),
                    "type": interv.get("type", ""),
                })

            return {
                "nct_id":          nct_id,
                "brief_title":     id_mod.get("briefTitle", ""),
                "official_title":  id_mod.get("officialTitle", ""),
                "status":          stat_mod.get("overallStatus", ""),
                "phase":           "|".join(design_mod.get("phases", [])),
                "study_type":      design_mod.get("studyType", ""),
                "start_date":      stat_mod.get("startDateStruct", {}).get("date", ""),
                "completion_date": stat_mod.get("completionDateStruct", {}).get("date", ""),
                "sponsor":         sponsor_mod.get("leadSponsor", {}).get("name", ""),
                "enrollment":      str(design_mod.get("enrollmentInfo", {}).get("count", "")),
                "conditions":      cond_mod.get("conditions", []),
                "interventions":   interventions,
            }
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    def get_schema(self) -> Dict[str, Dict[str, str]]:
        return {
            TRIAL_NODES: {
                "nct_id":          "ClinicalTrials.gov NCT identifier",
                "brief_title":     "Brief study title",
                "official_title":  "Official study title",
                "status":          "Overall recruitment status",
                "phase":           "Study phase (I, II, III, IV)",
                "study_type":      "Study type (Interventional, Observational)",
                "start_date":      "Study start date",
                "completion_date": "Study completion date",
                "sponsor":         "Lead sponsor name",
                "enrollment":      "Enrollment count",
                "source_database": "Source database (ClinicalTrials)",
            },
            TRIAL_DISEASE: {
                "nct_id":          "ClinicalTrials.gov NCT identifier",
                "condition":       "Disease/condition studied",
                "source_database": "Source database (ClinicalTrials)",
            },
            TRIAL_INTERV: {
                "nct_id":              "ClinicalTrials.gov NCT identifier",
                "intervention_name":   "Intervention name (drug, device, etc.)",
                "intervention_type":   "Intervention type",
                "source_database":     "Source database (ClinicalTrials)",
            },
        }
