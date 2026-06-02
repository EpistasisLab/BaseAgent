"""
PubTator Central Parser for the knowledge graph.

Uses bulk FTP files from NCBI PubTator Central to extract gene-disease
and disease-disease co-occurrences for cardiovascular diseases.

FTP: https://ftp.ncbi.nlm.nih.gov/pub/lu/PubTator/

Output:
  - pubtator_gene_disease.tsv : gene-disease co-occurrences from literature
    Columns: gene_id, gene_symbol, disease_id, disease_name, pmid_count, source_database
"""

import gzip
import logging
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Set

import pandas as pd

from .base_parser import BaseParser
from config_loader import get_disease_scope

logger = logging.getLogger(__name__)

_FTP_BASE = "https://ftp.ncbi.nlm.nih.gov/pub/lu/PubTator3/"
_DISEASE_FILE = "disease2pubtator3.gz"
_GENE_FILE = "gene2pubtator3.gz"
# Legacy file names from earlier PubTator versions
_DISEASE_FILE_LEGACY = "disease2pubtatorcentral.gz"
_GENE_FILE_LEGACY = "gene2pubtatorcentral.gz"

GENE_DISEASE_OUTPUT = "pubtator_gene_disease"

_CVD_ROOT_DOIDS = [
    "DOID:1287",    # cardiovascular system disease
    "DOID:114",     # heart disease
    "DOID:3393",    # coronary artery disease
    "DOID:5844",    # myocardial infarction
    "DOID:0060224", # atrial fibrillation
    "DOID:0050700", # cardiomyopathy
    "DOID:1712",    # aortic valve stenosis
    "DOID:10763",   # hypertension
    "DOID:6713",    # cerebrovascular disease
]


class PubTatorParser(BaseParser):
    """
    Parser for PubTator Central literature mining data.

    Uses bulk FTP files (gene2pubtatorcentral.gz and disease2pubtatorcentral.gz)
    to extract gene-disease co-occurrences at scale. Filters to CVD diseases
    using MESH→DOID mapping from Disease Ontology.

    Constructor args (injected from databases.yaml):
        data_dir      – base directory for raw/cached files
        source_url    – FTP base URL (optional override)
        disease_scope – disease scope dict (injected by main.py)
    """

    def __init__(
        self,
        data_dir: str,
        source_url: Optional[str] = None,
        disease_scope: Optional[Dict] = None,
        entity_types: Optional[list] = None,
    ):
        super().__init__(data_dir)
        self.source_name = "pubtator"
        self.source_dir = self.data_dir / self.source_name
        self.source_dir.mkdir(parents=True, exist_ok=True)

        _scope = disease_scope if disease_scope else get_disease_scope()
        self._doid_ids = _scope.get("doid_ids", _CVD_ROOT_DOIDS)

    # ------------------------------------------------------------------
    # Download
    # ------------------------------------------------------------------

    def download_data(self) -> bool:
        """Download bulk FTP files for gene and disease annotations."""
        disease_path = self._find_file(_DISEASE_FILE)
        if not disease_path:
            logger.info("Downloading PubTator disease annotations...")
            result = self.download_file(f"{_FTP_BASE}{_DISEASE_FILE}", _DISEASE_FILE)
            if not result:
                logger.error("Failed to download disease file")
                return False

        gene_path = self._find_file(_GENE_FILE)
        if not gene_path:
            logger.info("Downloading PubTator gene annotations (~750MB)...")
            result = self.download_file(f"{_FTP_BASE}{_GENE_FILE}", _GENE_FILE)
            if not result:
                logger.error("Failed to download gene file")
                return False

        return True

    # ------------------------------------------------------------------
    # Parse
    # ------------------------------------------------------------------

    def parse_data(self) -> Dict[str, pd.DataFrame]:
        """
        Parse bulk PubTator FTP files to extract CVD gene-disease co-occurrences.

        Strategy:
        1. Build CVD MeSH ID set from Disease Ontology xrefs
        2. Stream disease file → collect PMIDs with CVD disease annotations
        3. Stream gene file → for matching PMIDs, collect gene annotations
        4. Create gene-disease co-occurrence pairs (deduplicated across articles)
        """
        from id_mappings import IDMapper

        # Build CVD MeSH filter
        base_data_dir = self.data_dir.parent  # data/raw → data/
        mapper = IDMapper(str(base_data_dir))
        processed_dir = base_data_dir / "processed"
        if processed_dir.exists():
            mapper.load_all_mappings(processed_dir)

        cvd_mesh_ids = mapper.get_cvd_mesh_ids(self._doid_ids)
        logger.info("PubTator: %d CVD MeSH IDs for filtering", len(cvd_mesh_ids))

        if not cvd_mesh_ids:
            logger.error("No CVD MeSH IDs found. Cannot filter PubTator data.")
            return {}

        # Also build a mesh_id → doid mapping for the output
        mesh_to_doid = {}
        for mesh in cvd_mesh_ids:
            doid = mapper.map_to_doid(f"MESH:{mesh}")
            if doid:
                mesh_to_doid[mesh] = doid

        # Locate disease file
        disease_path = self._find_file(_DISEASE_FILE)
        if not disease_path:
            logger.error("disease2pubtatorcentral.gz not found")
            return {}

        # Pass 1: Stream disease file → collect CVD PMIDs and their disease annotations
        logger.info("PubTator Pass 1: scanning disease annotations for CVD PMIDs...")
        pmid_diseases: Dict[str, List[tuple]] = defaultdict(list)
        disease_lines = 0
        matched_lines = 0

        with gzip.open(disease_path, 'rt', encoding='utf-8', errors='replace') as f:
            for line in f:
                disease_lines += 1
                if disease_lines % 20_000_000 == 0:
                    logger.info("  Scanned %dM disease lines, %d CVD PMIDs so far",
                                disease_lines // 1_000_000, len(pmid_diseases))

                parts = line.rstrip('\n').split('\t')
                if len(parts) < 4:
                    continue

                pmid = parts[0]
                concept_id = parts[2]  # e.g. "MESH:D006333"
                mention = parts[3]

                # Extract MeSH ID
                if concept_id.startswith("MESH:"):
                    mesh_id = concept_id[5:]
                elif concept_id.startswith("D") and concept_id[1:7].isdigit():
                    mesh_id = concept_id
                else:
                    continue

                if mesh_id in cvd_mesh_ids:
                    doid = mesh_to_doid.get(mesh_id, concept_id)
                    pmid_diseases[pmid].append((doid, mention, mesh_id))
                    matched_lines += 1

        logger.info("PubTator Pass 1 complete: %d disease lines scanned, %d CVD PMIDs, %d matched lines",
                    disease_lines, len(pmid_diseases), matched_lines)

        if not pmid_diseases:
            logger.warning("No CVD PMIDs found in disease annotations.")
            return {}

        cvd_pmids = set(pmid_diseases.keys())

        # Pass 2: Stream gene file → collect gene annotations for CVD PMIDs
        gene_path = self._find_file(_GENE_FILE)
        if not gene_path:
            logger.error("gene2pubtatorcentral.gz not found")
            return {}

        logger.info("PubTator Pass 2: scanning gene annotations for %d CVD PMIDs...", len(cvd_pmids))
        pmid_genes: Dict[str, List[tuple]] = defaultdict(list)
        gene_lines = 0

        with gzip.open(gene_path, 'rt', encoding='utf-8', errors='replace') as f:
            for line in f:
                gene_lines += 1
                if gene_lines % 20_000_000 == 0:
                    logger.info("  Scanned %dM gene lines, %d PMIDs with genes",
                                gene_lines // 1_000_000, len(pmid_genes))

                parts = line.rstrip('\n').split('\t')
                if len(parts) < 4:
                    continue

                pmid = parts[0]
                if pmid not in cvd_pmids:
                    continue

                gene_id = parts[2]
                gene_symbol = parts[3]

                if gene_id and gene_id not in ("-", "", "None"):
                    # Handle composite IDs (e.g. "1234;5678")
                    for gid in gene_id.split(";"):
                        gid = gid.strip()
                        if gid and gid.isdigit():
                            pmid_genes[pmid].append((gid, gene_symbol))

        logger.info("PubTator Pass 2 complete: %d gene lines scanned, %d PMIDs with genes",
                    gene_lines, len(pmid_genes))

        # Create gene-disease co-occurrence pairs
        logger.info("PubTator: creating gene-disease co-occurrences...")
        pair_counts: Dict[tuple, int] = defaultdict(int)
        pair_info: Dict[tuple, tuple] = {}

        for pmid, genes in pmid_genes.items():
            diseases = pmid_diseases.get(pmid, [])
            # Deduplicate within article
            unique_genes = set(genes)
            unique_diseases = set(diseases)

            for gene_id, gene_symbol in unique_genes:
                for doid, disease_name, mesh_id in unique_diseases:
                    key = (gene_id, doid)
                    pair_counts[key] += 1
                    if key not in pair_info:
                        pair_info[key] = (gene_symbol, disease_name)

        logger.info("PubTator: %d unique gene-disease pairs from %d PMIDs",
                    len(pair_counts), len(pmid_genes))

        if not pair_counts:
            logger.warning("No gene-disease co-occurrences found.")
            return {}

        rows = []
        for (gene_id, disease_id), count in pair_counts.items():
            gene_symbol, disease_name = pair_info[(gene_id, disease_id)]
            rows.append({
                "gene_id": gene_id,
                "gene_symbol": gene_symbol,
                "disease_id": disease_id,
                "disease_name": disease_name,
                "pmid_count": count,
                "source_database": "PubTator",
            })

        df = pd.DataFrame(rows)
        df = df.sort_values("pmid_count", ascending=False).reset_index(drop=True)
        logger.info("PubTator: %d gene-disease associations (from %d co-occurrence pairs)",
                    len(df), sum(pair_counts.values()))

        return {GENE_DISEASE_OUTPUT: df}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _find_file(self, filename: str) -> Optional[Path]:
        """Find a file in source_dir, raw dir, or processed dir, trying legacy names too."""
        legacy_map = {
            _DISEASE_FILE: _DISEASE_FILE_LEGACY,
            _GENE_FILE: _GENE_FILE_LEGACY,
        }
        names = [filename]
        if filename in legacy_map:
            names.append(legacy_map[filename])

        search_dirs = [
            self.source_dir,
            self.data_dir / "raw" / "pubtator",
            self.data_dir / "processed" / "pubtator",
        ]
        for name in names:
            for base in search_dirs:
                p = base / name
                if p.exists():
                    return p
        return None

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    def get_schema(self) -> Dict[str, Dict[str, str]]:
        return {
            GENE_DISEASE_OUTPUT: {
                "gene_id":         "NCBI Gene ID",
                "gene_symbol":     "Gene symbol (from PubTator annotation)",
                "disease_id":      "Disease identifier (DOID mapped from MeSH)",
                "disease_name":    "Disease name (text mention)",
                "pmid_count":      "Number of articles with this co-occurrence",
                "source_database": "Source database (PubTator)",
            },
        }
