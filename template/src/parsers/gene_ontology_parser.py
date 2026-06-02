"""
Gene Ontology Parser for the knowledge graph.

Downloads and parses the Gene Ontology (GO) to extract:
- Biological Process (BP) nodes
- Molecular Function (MF) nodes
- Cellular Component (CC) nodes
- Gene-GO associations (BP, MF, CC)

Data Sources:
  - GO OBO: http://purl.obolibrary.org/obo/go.obo
  - GOA Human: http://current.geneontology.org/annotations/goa_human.gaf.gz

Output (6 DataFrames):
  - biological_process_nodes.tsv  (go_id, name, definition)
  - molecular_function_nodes.tsv  (go_id, name, definition)
  - cellular_component_nodes.tsv  (go_id, name, definition)
  - gene_bp_associations.tsv      (gene_symbol, go_id, evidence)
  - gene_mf_associations.tsv      (gene_symbol, go_id, evidence)
  - gene_cc_associations.tsv      (gene_symbol, go_id, evidence)
"""

import gzip
import logging
from pathlib import Path
from typing import Dict

import pandas as pd

try:
    import obonet
    HAS_OBONET = True
except ImportError:
    HAS_OBONET = False

from .base_parser import BaseParser

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Output name constants — must match source_filename in ontology_mappings.yaml
# ---------------------------------------------------------------------------
BP_NODES = "biological_process_nodes"
MF_NODES = "molecular_function_nodes"
CC_NODES = "cellular_component_nodes"
GENE_BP  = "gene_bp_associations"
GENE_MF  = "gene_mf_associations"
GENE_CC  = "gene_cc_associations"

_NODE_COLUMNS = ["go_id", "name", "definition"]

# GAF column names (17 columns in GAF 2.2)
_GAF_COLUMNS = [
    "DB", "DB_Object_ID", "DB_Object_Symbol", "Qualifier", "GO_ID",
    "DB_Reference", "Evidence_Code", "With_From", "Aspect",
    "DB_Object_Name", "DB_Object_Synonym", "DB_Object_Type",
    "Taxon", "Date", "Assigned_By", "Annotation_Extension",
    "Gene_Product_Form_ID",
]

# Evidence code priority: lower index = higher quality.
# Experimental > high-throughput > phylogenetic > author/curator > computational > electronic.
_EVIDENCE_PRIORITY: Dict[str, int] = {
    code: rank for rank, code in enumerate([
        "EXP", "IDA", "IPI", "IMP", "IGI", "IEP",   # experimental
        "HTP", "HDA", "HMP", "HGI", "HEP",           # high-throughput
        "IBA", "IBD", "IKR", "IRD",                   # phylogenetic
        "TAS", "IC",                                  # author/curator statement
        "ISS", "ISO", "ISA", "ISM", "IGC", "RCA",    # computational
        "NAS", "ND",                                  # non-traceable / no data
        "IEA",                                        # electronic (least reliable)
    ])
}
_EVIDENCE_FALLBACK = len(_EVIDENCE_PRIORITY)


def _best_evidence(codes: pd.Series) -> str:
    """Return the highest-quality GO evidence code from a group."""
    return min(codes, key=lambda c: _EVIDENCE_PRIORITY.get(c, _EVIDENCE_FALLBACK))


def _extract_aspect(df: pd.DataFrame, aspect_code: str) -> pd.DataFrame:
    """Extract gene-GO associations for one GO aspect and keep best evidence per pair."""
    sub = df[df["Aspect"] == aspect_code][
        ["DB_Object_Symbol", "GO_ID", "Evidence_Code"]
    ].copy()
    sub.columns = ["gene_symbol", "go_id", "evidence"]
    if sub.empty:
        return sub.reset_index(drop=True)
    sub = (
        sub.groupby(["gene_symbol", "go_id"], as_index=False)["evidence"]
        .agg(_best_evidence)
    )
    return sub.reset_index(drop=True)


class GeneOntologyParser(BaseParser):
    """
    Parser for the Gene Ontology (GO).

    Extracts GO terms (BP, MF, CC) and human gene-GO associations from
    the GO OBO file and GOA human annotation file.
    """

    GO_OBO_URL    = "http://purl.obolibrary.org/obo/go.obo"
    GOA_HUMAN_URL = "http://current.geneontology.org/annotations/goa_human.gaf.gz"

    GO_BASIC_OBO = "go-basic.obo"
    GO_OBO_FILE  = "go.obo"
    GAF_FILE     = "goa_human.gaf.gz"

    def __init__(self, data_dir: str):
        super().__init__(data_dir)
        # BaseParser sets source_name = "geneontology" (from class name).
        # Override to "gene_ontology" so it matches the databases.yaml key.
        # Note: source_dir stays as data_dir/geneontology (where raw files live).
        self.source_name = "gene_ontology"

    # ------------------------------------------------------------------
    # download_data
    # ------------------------------------------------------------------

    def download_data(self) -> bool:
        """Download GO OBO and GOA human annotation files."""
        logger.info("Downloading Gene Ontology files …")
        success = True

        # download_file respects self.force and skips if already cached.
        if not self.download_file(self.GO_OBO_URL, self.GO_OBO_FILE):
            logger.error("Failed to download GO OBO file")
            success = False

        if not self.download_file(self.GOA_HUMAN_URL, self.GAF_FILE):
            logger.error("Failed to download GOA human annotation file")
            success = False

        return success

    # ------------------------------------------------------------------
    # parse_data
    # ------------------------------------------------------------------

    def parse_data(self) -> Dict[str, pd.DataFrame]:
        """Parse GO OBO and GOA annotation files; return 6 DataFrames."""
        result: Dict[str, pd.DataFrame] = {}

        obo_path = self._find_obo_file()
        if obo_path is None:
            logger.error("No GO OBO file found — cannot parse GO terms")
        else:
            result.update(self._parse_go_ontology(obo_path))

        gaf_path = self.source_dir / self.GAF_FILE
        if gaf_path.exists():
            result.update(self._parse_goa_annotations(gaf_path))
        else:
            logger.error(f"GOA annotation file not found: {gaf_path}")

        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _find_obo_file(self):
        """Return the path to the best available OBO file."""
        for fname in (self.GO_OBO_FILE, self.GO_BASIC_OBO):
            p = self.source_dir / fname
            if p.exists():
                logger.info(f"Using OBO file: {p}")
                return p
        return None

    def _parse_go_ontology(self, obo_path: Path) -> Dict[str, pd.DataFrame]:
        """Parse GO OBO file and return BP/MF/CC node DataFrames."""
        if not HAS_OBONET:
            logger.error("obonet is not installed — cannot parse OBO file")
            return {}

        logger.info(f"Parsing GO ontology from {obo_path} …")
        try:
            graph = obonet.read_obo(str(obo_path))
        except Exception as exc:
            logger.error(f"Failed to read OBO file: {exc}")
            return {}

        bp_terms, mf_terms, cc_terms = [], [], []

        for node_id, node_data in graph.nodes(data=True):
            if not node_id.startswith("GO:"):
                continue
            if node_data.get("is_obsolete", False):
                continue

            namespace = node_data.get("namespace", "")
            term = {
                "go_id":      node_id,
                "name":       node_data.get("name", ""),
                "definition": self._clean_definition(node_data.get("def", "")),
            }

            if namespace == "biological_process":
                bp_terms.append(term)
            elif namespace == "molecular_function":
                mf_terms.append(term)
            elif namespace == "cellular_component":
                cc_terms.append(term)

        logger.info(
            f"Parsed {len(bp_terms)} BP, {len(mf_terms)} MF, {len(cc_terms)} CC terms"
        )

        bp_df = pd.DataFrame(bp_terms, columns=_NODE_COLUMNS)
        mf_df = pd.DataFrame(mf_terms, columns=_NODE_COLUMNS)
        cc_df = pd.DataFrame(cc_terms, columns=_NODE_COLUMNS)
        for df in [bp_df, mf_df, cc_df]:
            df["source_database"] = "Gene Ontology"
        return {BP_NODES: bp_df, MF_NODES: mf_df, CC_NODES: cc_df}

    def _parse_goa_annotations(self, gaf_path: Path) -> Dict[str, pd.DataFrame]:
        """
        Parse GOA human GAF file and return gene-BP/MF/CC association DataFrames.

        Columns: gene_symbol, go_id, evidence
        """
        logger.info(f"Parsing GOA annotations from {gaf_path} …")

        rows = []
        try:
            with gzip.open(gaf_path, "rt", encoding="utf-8") as fh:
                for line in fh:
                    if line.startswith("!"):
                        continue
                    parts = line.rstrip("\n").split("\t")
                    if len(parts) < 15:
                        continue
                    while len(parts) < 17:
                        parts.append("")
                    rows.append(parts[:17])
        except Exception as exc:
            logger.error(f"Failed to read GAF file: {exc}")
            return {}

        df = pd.DataFrame(rows, columns=_GAF_COLUMNS)
        logger.info(f"Loaded {len(df):,} raw GAF records")

        df = df[df["Taxon"].str.contains("taxon:9606", na=False)]
        logger.info(f"After human filter: {len(df):,} records")

        # Restrict to UniProtKB entries; ComplexPortal and RNAcentral rows use
        # complex/RNA names in DB_Object_Symbol, not gene symbols.
        n_before = len(df)
        df = df[df["DB"] == "UniProtKB"]
        n_dropped = n_before - len(df)
        if n_dropped:
            logger.info(f"Dropped {n_dropped:,} non-UniProtKB records (ComplexPortal/RNAcentral)")

        # Exclude NOT-qualified annotations (explicit negative associations).
        n_before = len(df)
        df = df[~df["Qualifier"].str.contains("NOT", na=False)]
        n_dropped = n_before - len(df)
        if n_dropped:
            logger.info(f"Dropped {n_dropped:,} NOT-qualified records")

        bp_df = _extract_aspect(df, "P")
        mf_df = _extract_aspect(df, "F")
        cc_df = _extract_aspect(df, "C")

        logger.info(
            f"Associations — BP: {len(bp_df):,}, MF: {len(mf_df):,}, CC: {len(cc_df):,}"
        )

        for assoc_df in [bp_df, mf_df, cc_df]:
            assoc_df["source_database"] = "Gene Ontology"
        return {GENE_BP: bp_df, GENE_MF: mf_df, GENE_CC: cc_df}

    @staticmethod
    def _clean_definition(definition: str) -> str:
        """Strip OBO-format quotes and citation brackets from a definition.

        OBO format: "Definition text." [citation]
        """
        if not definition:
            return ""
        if definition.startswith('"'):
            definition = definition[1:]
        if " [" in definition:
            definition = definition.split(" [")[0]
        if definition.endswith('"'):
            definition = definition[:-1]
        return definition.replace('\t', ' ').strip()

    # ------------------------------------------------------------------
    # get_schema
    # ------------------------------------------------------------------

    def get_schema(self) -> Dict[str, Dict[str, str]]:
        """Return the schema for all 6 output DataFrames."""
        node_schema = {
            "go_id":           "Gene Ontology ID (e.g. GO:0008150)",
            "name":            "Human-readable GO term name",
            "definition":      "Text definition of the GO term",
            "source_database": "Source database name",
        }
        assoc_schema = {
            "gene_symbol":     "HGNC gene symbol (matches Gene node geneSymbol property)",
            "go_id":           "Gene Ontology ID",
            "evidence":        "GO evidence code (e.g. IDA, IEA, TAS)",
            "source_database": "Source database name",
        }
        return {
            BP_NODES: node_schema,
            MF_NODES: node_schema,
            CC_NODES: node_schema,
            GENE_BP:  assoc_schema,
            GENE_MF:  assoc_schema,
            GENE_CC:  assoc_schema,
        }
