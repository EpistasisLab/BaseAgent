"""
HPO (Human Phenotype Ontology) Parser for the knowledge graph.

Downloads:
  - hp.obo from http://purl.obolibrary.org/obo/hp.obo
  - Gene-phenotype annotations from HPO JAX

Produces:
  - phenotype_nodes.tsv      : Phenotype nodes (HPO terms)
  - gene_phenotype_assoc.tsv : geneAssociatesWithPhenotype edges

Data Sources:
  - http://purl.obolibrary.org/obo/hp.obo
  - https://purl.obolibrary.org/obo/hp/hpoa/genes_to_phenotype.txt
"""

import gzip
import logging
from pathlib import Path
from typing import Dict, Optional

import pandas as pd
import requests

from .base_parser import BaseParser
from config_loader import get_disease_scope

logger = logging.getLogger(__name__)

try:
    import obonet
    HAS_OBONET = True
except ImportError:
    HAS_OBONET = False

HP_OBO_URL  = "http://purl.obolibrary.org/obo/hp.obo"
GENES_URL   = "https://purl.obolibrary.org/obo/hp/hpoa/genes_to_phenotype.txt"
DISEASE_URL = "https://purl.obolibrary.org/obo/hp/hpoa/phenotype.hpoa"

HP_OBO_FILE  = "hp.obo"
GENES_FILE   = "genes_to_phenotype.txt"
DISEASE_FILE = "phenotype.hpoa"

PHENOTYPE_NODES = "phenotype_nodes"
GENE_PHENO_ASSOC = "gene_phenotype_associations"


class HPOParser(BaseParser):
    """
    Parser for the Human Phenotype Ontology (HPO).

    Extracts Phenotype nodes from hp.obo and geneAssociatesWithPhenotype
    edges from the gene-to-phenotype annotation file.

    Constructor args (injected from databases.yaml):
        data_dir         – base directory for raw/cached files
        obo_url          – URL of hp.obo
        annotations_url  – URL of genes_to_phenotype.txt (unused; kept for compat)
        disease_scope    – disease scope dict (injected by main.py)
    """

    def __init__(
        self,
        data_dir: str,
        source_url: Optional[str] = None,
        obo_url: Optional[str] = None,
        annotations_url: Optional[str] = None,
        disease_scope: Optional[Dict] = None,
    ):
        super().__init__(data_dir)
        self.source_name = "hpo"
        self.source_dir = self.data_dir / self.source_name
        self.source_dir.mkdir(parents=True, exist_ok=True)

        # Accept either source_url or obo_url (databases.yaml uses source_url)
        self.obo_url = source_url or obo_url or HP_OBO_URL

        _scope = disease_scope if disease_scope else get_disease_scope()
        self._primary_terms = [t.lower() for t in _scope.get("primary_terms", [])]

    # ------------------------------------------------------------------
    # Download
    # ------------------------------------------------------------------

    def download_data(self) -> bool:
        logger.info("Downloading HPO OBO and annotation files ...")
        ok1 = self.download_file(HP_OBO_URL, HP_OBO_FILE)
        ok2 = self.download_file(GENES_URL, GENES_FILE)
        ok3 = self.download_file(DISEASE_URL, DISEASE_FILE)
        success = bool(ok1) and bool(ok2)
        if not success:
            logger.error("Failed to download one or more HPO files.")
        return success

    # ------------------------------------------------------------------
    # Parse
    # ------------------------------------------------------------------

    def parse_data(self) -> Dict[str, pd.DataFrame]:
        results = {}

        obo_path = self.source_dir / HP_OBO_FILE
        if obo_path.exists() and HAS_OBONET:
            nodes_df = self._parse_obo(obo_path)
            if nodes_df is not None:
                results[PHENOTYPE_NODES] = nodes_df

        genes_path = self.source_dir / GENES_FILE
        if genes_path.exists():
            assoc_df = self._parse_gene_annotations(genes_path)
            if assoc_df is not None:
                results[GENE_PHENO_ASSOC] = assoc_df

        return results

    def _parse_obo(self, obo_path: Path) -> Optional[pd.DataFrame]:
        """Parse hp.obo and return phenotype node DataFrame."""
        logger.info("Parsing HPO OBO from %s ...", obo_path)
        try:
            graph = obonet.read_obo(str(obo_path))
        except Exception as exc:
            logger.error("Failed to parse HPO OBO: %s", exc)
            return None

        rows = []
        for node_id, data in graph.nodes(data=True):
            if not str(node_id).startswith("HP:"):
                continue
            if data.get("is_obsolete", False):
                continue
            name = data.get("name", "")
            raw_def = data.get("def", "")
            definition = self._clean_definition(raw_def)
            synonyms = self._parse_synonyms(data.get("synonym", []))
            is_a = [e.split(" ! ")[0].strip() for e in data.get("is_a", [])]
            rows.append({
                "hp_id":        str(node_id),
                "hp_name":      name,
                "definition":   definition,
                "synonyms":     synonyms,
                "is_a":         "|".join(is_a),
                "source_database": "HPO",
            })

        df = pd.DataFrame(rows)
        logger.info("HPO: %d phenotype nodes", len(df))
        return df

    def _parse_gene_annotations(self, genes_path: Path) -> Optional[pd.DataFrame]:
        """Parse genes_to_phenotype.txt and return gene-phenotype association DataFrame."""
        logger.info("Parsing HPO gene-phenotype annotations from %s ...", genes_path)
        try:
            df = pd.read_csv(
                genes_path,
                sep="\t",
                comment="#",
                dtype=str,
                low_memory=False,
            )
        except Exception as exc:
            logger.error("Failed to read HPO gene annotations: %s", exc)
            return None

        logger.info("HPO gene-phenotype raw: %d rows, columns: %s", len(df), list(df.columns))

        # Normalize column names (file format varies by release)
        col_map = {}
        for col in df.columns:
            cl = col.lower().strip("#").strip()
            if "ncbi" in cl and "gene" in cl:
                col_map[col] = "ncbi_gene_id"
            elif "gene_symbol" in cl or col.lower() == "gene_symbol":
                col_map[col] = "gene_symbol"
            elif "hpo_id" in cl or col.lower() == "hpo_id":
                col_map[col] = "hp_id"
            elif "hpo_name" in cl or "phenotype_name" in cl:
                col_map[col] = "hp_name"
            elif "frequency" in cl:
                col_map[col] = "frequency"
            elif "evidence" in cl:
                col_map[col] = "evidence"
        df = df.rename(columns=col_map)

        keep = [c for c in ["ncbi_gene_id", "gene_symbol", "hp_id", "hp_name", "frequency", "evidence"]
                if c in df.columns]
        df = df[keep].drop_duplicates().reset_index(drop=True)
        df["source_database"] = "HPO"
        logger.info("HPO: %d gene-phenotype associations", len(df))
        return df

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _clean_definition(raw: str) -> str:
        import re
        m = re.match(r'^"(.*?)"', raw.strip())
        return m.group(1) if m else raw.strip()

    @staticmethod
    def _parse_synonyms(synonym_list) -> str:
        import re
        texts = []
        for syn in synonym_list:
            m = re.match(r'^"(.*?)"\s+\w', str(syn))
            if m:
                texts.append(m.group(1))
        return "|".join(texts)

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    def get_schema(self) -> Dict[str, Dict[str, str]]:
        return {
            PHENOTYPE_NODES: {
                "hp_id":          "HPO term ID (e.g. HP:0001234)",
                "hp_name":        "HPO term name",
                "definition":     "HPO term definition",
                "synonyms":       "Pipe-separated synonyms",
                "is_a":           "Pipe-separated parent HP IDs",
                "source_database": "Source database (HPO)",
            },
            GENE_PHENO_ASSOC: {
                "ncbi_gene_id":  "NCBI Gene ID",
                "gene_symbol":   "Gene symbol",
                "hp_id":         "HPO term ID",
                "hp_name":       "HPO term name",
                "frequency":     "Frequency annotation",
                "evidence":      "Evidence code",
                "source_database": "Source database (HPO)",
            },
        }
