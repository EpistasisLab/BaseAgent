"""
ClinVar Variant Parser for the knowledge graph.

Downloads variant_summary.txt.gz from NCBI FTP and extracts:
  - Variant nodes with clinical significance
  - variantInGene edges (Variant → Gene)
  - variantAssociatedWithDisease edges (Variant → Disease)

Filters to variants associated with cardiovascular diseases using
disease terms from config/project.yaml — no hardcoded disease values.

Uses the enhanced IDMapper for comprehensive disease ID resolution
(UMLS CUI, MedGen, OMIM, MONDO → DOID).

Data Source: https://ftp.ncbi.nlm.nih.gov/pub/clinvar/tab_delimited/variant_summary.txt.gz
"""

import logging
from pathlib import Path
from typing import Dict, Optional

import pandas as pd

from .base_parser import BaseParser
from config_loader import get_disease_scope

logger = logging.getLogger(__name__)

_DEFAULT_URL = (
    "https://ftp.ncbi.nlm.nih.gov/pub/clinvar/tab_delimited/variant_summary.txt.gz"
)

VARIANT_NODES         = "variant_nodes"
VARIANT_GENE_ASSOC    = "variant_gene_associations"
VARIANT_DISEASE_ASSOC = "variant_disease_associations"

_HUMAN_TAXON = 9606
_CHUNK_ROWS  = 200_000


class ClinVarParser(BaseParser):
    """
    Parser for ClinVar genetic variant data.

    Streams variant_summary.txt.gz and filters to human variants associated
    with diseases in the project disease scope (config/project.yaml).

    Constructor args (injected from databases.yaml):
        data_dir   – base directory for raw/cached files
        source_url – URL of the variant_summary.txt.gz file
        disease_scope – disease scope dict (injected by main.py)
    """

    def __init__(
        self,
        data_dir: str,
        source_url: Optional[str] = None,
        disease_scope: Optional[Dict] = None,
        filter_pathogenic: bool = True,
    ):
        super().__init__(data_dir)
        self.source_name = "clinvar"
        self.source_dir = self.data_dir / self.source_name
        self.source_dir.mkdir(parents=True, exist_ok=True)
        self.filter_pathogenic = filter_pathogenic

        _url = source_url or _DEFAULT_URL
        if _url.endswith("/") or not _url.endswith(".gz"):
            _url = _DEFAULT_URL
        self.source_url = _url
        _gz = Path(self.source_url).name
        self._gz_filename = _gz
        self._extracted_filename = _gz[:-3] if _gz.endswith(".gz") else _gz

        _scope = disease_scope if disease_scope else get_disease_scope()
        self._primary_terms = [t.lower() for t in _scope.get("primary_terms", [])]

    # ------------------------------------------------------------------
    # Download
    # ------------------------------------------------------------------

    def download_data(self) -> bool:
        logger.info("Downloading ClinVar variant_summary from %s ...", self.source_url)
        gz_path = self.download_file(self.source_url, self._gz_filename)
        if not gz_path:
            logger.error("Failed to download ClinVar variant_summary.")
            return False
        extracted = self.extract_gzip(gz_path)
        if not extracted:
            logger.error("Failed to extract ClinVar variant_summary.")
            return False
        return True

    # ------------------------------------------------------------------
    # Parse
    # ------------------------------------------------------------------

    def parse_data(self) -> Dict[str, pd.DataFrame]:
        """Stream-parse variant_summary.txt filtering by disease scope."""
        tsv_path = self.source_dir / self._extracted_filename
        if not tsv_path.exists():
            logger.error("ClinVar file not found: %s", tsv_path)
            return {}

        logger.info("Parsing ClinVar from %s (chunked) ...", tsv_path)

        all_chunks = []
        try:
            reader = pd.read_csv(
                tsv_path,
                sep="\t",
                low_memory=False,
                dtype=str,
                chunksize=_CHUNK_ROWS,
            )
            for chunk in reader:
                if "TaxID" in chunk.columns:
                    chunk = chunk[chunk["TaxID"].astype(str) == str(_HUMAN_TAXON)]
                if self._primary_terms and "PhenotypeList" in chunk.columns:
                    mask = chunk["PhenotypeList"].str.lower().apply(
                        lambda txt: any(t in str(txt) for t in self._primary_terms)
                        if pd.notna(txt) else False
                    )
                    chunk = chunk[mask]
                if not chunk.empty:
                    all_chunks.append(chunk)
        except Exception as exc:
            logger.error("Failed to parse ClinVar: %s", exc)
            return {}

        if not all_chunks:
            logger.warning("No ClinVar variants matched disease scope filter.")
            return {}

        df = pd.concat(all_chunks, ignore_index=True)
        logger.info("ClinVar: %d variants after filtering", len(df))

        allele_col = "#AlleleID" if "#AlleleID" in df.columns else "AlleleID"

        # ---- Variant nodes ----
        variant_col_map = {
            allele_col: "allele_id",
            "VariationID": "variation_id",
            "Name": "variant_name",
            "Type": "variant_type",
            "ClinicalSignificance": "clinical_significance",
            "ReviewStatus": "review_status",
            "Assembly": "assembly",
            "Chromosome": "chromosome",
            "Start": "start_pos",
            "Stop": "stop_pos",
            "ReferenceAllele": "ref_allele",
            "AlternateAllele": "alt_allele",
            "RS# (dbSNP)": "dbsnp_id",
        }
        avail = {k: v for k, v in variant_col_map.items() if k in df.columns}
        if not avail:
            logger.error("ClinVar: no expected columns found. Got: %s", list(df.columns[:10]))
            return {}
        variant_df = df[list(avail.keys())].rename(columns=avail).copy()
        id_col = "allele_id" if "allele_id" in variant_df.columns else variant_df.columns[0]
        variant_df = variant_df.drop_duplicates(subset=[id_col]).reset_index(drop=True)
        variant_df["source_database"] = "ClinVar"

        # ---- variantInGene edges ----
        gene_need = [allele_col, "GeneID", "GeneSymbol"]
        gene_avail = [c for c in gene_need if c in df.columns]
        if len(gene_avail) >= 2 and allele_col in gene_avail:
            gene_df = df[gene_avail].rename(columns={
                allele_col: "allele_id",
                "GeneID": "gene_id",
                "GeneSymbol": "gene_symbol",
            }).copy()
            gene_df = gene_df[gene_df["gene_id"].notna() & (gene_df["gene_id"] != "-")]
            gene_df = gene_df.drop_duplicates().reset_index(drop=True)
            gene_df["source_database"] = "ClinVar"
        else:
            gene_df = pd.DataFrame(columns=["allele_id", "gene_id", "gene_symbol", "source_database"])

        # ---- variantAssociatedWithDisease edges ----
        # Use enhanced IDMapper for comprehensive disease ID resolution
        from id_mappings import IDMapper
        base_data_dir = self.data_dir.parent  # data/raw → data/
        mapper = IDMapper(str(base_data_dir))
        processed_dir = base_data_dir / "processed"
        if processed_dir.exists():
            mapper.load_all_mappings(processed_dir)

        dis_need = [allele_col, "PhenotypeList", "PhenotypeIDS", "ClinicalSignificance"]
        dis_avail = [c for c in dis_need if c in df.columns]
        if len(dis_avail) >= 2 and allele_col in dis_avail:
            dis_raw = df[dis_avail].rename(columns={
                allele_col: "allele_id",
                "PhenotypeList": "phenotype_list",
                "PhenotypeIDS": "phenotype_ids",
                "ClinicalSignificance": "clinical_significance",
            }).copy()
            dis_raw = dis_raw[dis_raw["phenotype_ids"].notna() & (dis_raw["phenotype_ids"] != "-")]

            expanded_rows = []
            for _, row in dis_raw.iterrows():
                allele_id = row["allele_id"]
                clin_sig = row.get("clinical_significance", "")
                phenotype_ids_str = str(row["phenotype_ids"])

                for group in phenotype_ids_str.split("|"):
                    group = group.strip()
                    if not group or group == "-":
                        continue

                    # Try ALL IDs in the group to find the best DOID mapping
                    best_doid = None
                    umls_cui = None
                    first_id = None

                    for id_str in group.split(","):
                        id_str = id_str.strip()
                        if not id_str:
                            continue
                        if first_id is None:
                            first_id = id_str

                        # Extract UMLS CUI from MedGen:Cxxxxxx
                        if id_str.startswith("MedGen:C") and len(id_str) > 8:
                            cui = id_str[7:]
                            if cui.startswith("C") and cui[1:].isdigit():
                                umls_cui = cui
                                doid = mapper.map_to_doid(cui)
                                if doid:
                                    best_doid = doid
                                    continue

                        # Try direct mapping for all ID types
                        doid = mapper.map_to_doid(id_str)
                        if doid:
                            best_doid = doid

                    if first_id:
                        expanded_rows.append({
                            "variant_id": str(allele_id),
                            "disease_id": best_doid or first_id,
                            "doid_mapped": best_doid is not None,
                            "umls_cui": umls_cui,
                            "clinical_significance": clin_sig,
                            "source_database": "ClinVar",
                        })

            dis_df = pd.DataFrame(expanded_rows).drop_duplicates(
                subset=["variant_id", "disease_id"]
            ).reset_index(drop=True)

            # Report mapping stats
            total = len(dis_df)
            mapped = dis_df["doid_mapped"].sum() if "doid_mapped" in dis_df.columns else 0
            cui_count = dis_df["umls_cui"].notna().sum()
            logger.info(f"ClinVar disease mapping: {mapped}/{total} ({100*mapped/max(total,1):.1f}%) mapped to DOID")
            logger.info(f"ClinVar: extracted UMLS CUIs for {cui_count}/{total} disease associations")

            dis_df = dis_df.drop(columns=["doid_mapped"], errors="ignore")
        else:
            dis_df = pd.DataFrame(columns=["variant_id", "disease_id", "umls_cui",
                                           "clinical_significance", "source_database"])

        logger.info(
            "ClinVar: %d variant nodes | %d gene edges | %d disease edges",
            len(variant_df), len(gene_df), len(dis_df),
        )

        return {
            VARIANT_NODES:         variant_df,
            VARIANT_GENE_ASSOC:    gene_df,
            VARIANT_DISEASE_ASSOC: dis_df,
        }

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    def get_schema(self) -> Dict[str, Dict[str, str]]:
        return {
            VARIANT_NODES: {
                "allele_id":             "ClinVar AlleleID",
                "variation_id":          "ClinVar VariationID",
                "variant_name":          "Variant name (HGVS or common name)",
                "variant_type":          "Variant type (SNV, Indel, etc.)",
                "clinical_significance": "ClinVar clinical significance",
                "review_status":         "ClinVar review status",
                "assembly":              "Genome assembly (GRCh38, GRCh37)",
                "chromosome":            "Chromosome",
                "start_pos":             "Start genomic position",
                "stop_pos":              "Stop genomic position",
                "ref_allele":            "Reference allele",
                "alt_allele":            "Alternate allele",
                "dbsnp_id":              "dbSNP RS number",
                "source_database":       "Source database (ClinVar)",
            },
            VARIANT_GENE_ASSOC: {
                "allele_id":       "ClinVar AlleleID",
                "gene_id":         "NCBI Gene ID",
                "gene_symbol":     "Gene symbol",
                "source_database": "Source database (ClinVar)",
            },
            VARIANT_DISEASE_ASSOC: {
                "variant_id":            "ClinVar Variant ID (ClinVar:{allele_id} format)",
                "disease_id":            "Disease ID (DOID when mapped, otherwise original)",
                "umls_cui":              "UMLS CUI extracted from MedGen ID",
                "clinical_significance": "ClinVar clinical significance",
                "source_database":       "Source database (ClinVar)",
            },
        }
