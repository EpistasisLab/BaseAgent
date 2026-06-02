"""
Cross-ontology ID mapping module for the KG pipeline.

Provides mappings between different identifier systems:
- EFO → DOID (Experimental Factor Ontology to Disease Ontology)
- MESH → DOID (Medical Subject Headings to Disease Ontology)
- UMLS → DOID (UMLS CUI to Disease Ontology)
- OMIM → DOID (OMIM to Disease Ontology)
- NCI → DOID (NCI Thesaurus to Disease Ontology)
- BTO → UBERON (BRENDA Tissue Ontology to Uberon)
- ENSP → NCBIGene (Ensembl Protein to NCBI Gene)

Mappings are built primarily from doid.obo xrefs, supplemented by
explicit mapping files and cross-references in node data.
"""

import csv
import gzip
import logging
import re
from collections import defaultdict
from pathlib import Path
from typing import Dict, FrozenSet, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


class IDMapper:
    """
    Central ID mapping service for cross-ontology resolution.

    Builds mappings from:
    1. doid.obo cross-references (primary — 7K UMLS, 4K MESH, 5K NCI, 110 EFO)
    2. Explicit mapping files (data/mappings/*.tsv)
    3. Cross-references extracted from node TSV files
    """

    def __init__(self, data_dir: str):
        self.data_dir = Path(data_dir)
        self.mappings_dir = self.data_dir / "mappings"
        self.mappings_dir.mkdir(parents=True, exist_ok=True)

        self.efo_to_doid: Dict[str, str] = {}
        self.mesh_to_doid: Dict[str, str] = {}
        self.bto_to_uberon: Dict[str, str] = {}
        self.ensp_to_ncbigene: Dict[str, str] = {}
        self.umls_to_doid: Dict[str, str] = {}
        self.omim_to_doid: Dict[str, str] = {}
        self.nci_to_doid: Dict[str, str] = {}
        self.mondo_to_doid: Dict[str, str] = {}
        self.icd10_to_doid: Dict[str, str] = {}

        # DOID subtype tree: child → set of parents
        self._doid_parents: Dict[str, Set[str]] = defaultdict(set)
        # All DOID terms: doid → name
        self._doid_names: Dict[str, str] = {}
        # Reverse: doid → set of mesh ids
        self._doid_to_mesh: Dict[str, Set[str]] = defaultdict(set)
        self._doid_to_umls: Dict[str, Set[str]] = defaultdict(set)

    def load_all_mappings(self, processed_dir: Path):
        """Load all available mappings from OBO, files, and node cross-references."""
        logger.info("Loading ID mappings...")

        # Primary: parse doid.obo for comprehensive xref coverage
        obo_path = processed_dir / "disease_ontology" / "doid.obo"
        if not obo_path.exists():
            obo_path = self.data_dir / "raw" / "doid.obo"
        if obo_path.exists():
            self._parse_doid_obo(obo_path)

        # Supplement with explicit mapping files (including parquet-derived)
        self._load_mapping_file("efo_to_doid.tsv", self.efo_to_doid)
        self._load_mapping_file("mondo_to_doid.tsv", self.mondo_to_doid)
        self._load_mapping_file("mesh_to_doid.tsv", self.mesh_to_doid)
        self._load_mapping_file("bto_to_uberon.tsv", self.bto_to_uberon)
        self._load_mapping_file("ensp_to_ncbigene.tsv", self.ensp_to_ncbigene)

        # Supplement with node cross-references
        self._extract_disease_xrefs(processed_dir)
        self._extract_gene_xrefs(processed_dir)

        logger.info(
            f"Loaded mappings: EFO→DOID: {len(self.efo_to_doid)}, "
            f"MESH→DOID: {len(self.mesh_to_doid)}, "
            f"UMLS→DOID: {len(self.umls_to_doid)}, "
            f"OMIM→DOID: {len(self.omim_to_doid)}, "
            f"NCI→DOID: {len(self.nci_to_doid)}, "
            f"MONDO→DOID: {len(self.mondo_to_doid)}, "
            f"DOID terms: {len(self._doid_names)}, "
            f"is_a edges: {sum(len(v) for v in self._doid_parents.values())}"
        )

    # ------------------------------------------------------------------
    # OBO parsing — primary source of xref mappings
    # ------------------------------------------------------------------

    def _parse_doid_obo(self, obo_path: Path):
        """
        Parse doid.obo to extract:
        - All DOID terms with names
        - is_a subtype relationships
        - Cross-references to UMLS, MeSH, EFO, OMIM, NCI, MONDO, ICD10
        """
        logger.info("Parsing doid.obo for cross-references: %s", obo_path)

        current_id = None
        current_name = None
        current_xrefs = []
        current_parents = []
        is_obsolete = False
        in_term = False

        def _flush_term():
            if current_id and not is_obsolete:
                self._doid_names[current_id] = current_name or ""
                for parent in current_parents:
                    self._doid_parents[current_id].add(parent)
                for xref in current_xrefs:
                    self._index_xref(current_id, xref)

        with open(obo_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.rstrip()

                if line == "[Term]":
                    if in_term:
                        _flush_term()
                    current_id = None
                    current_name = None
                    current_xrefs = []
                    current_parents = []
                    is_obsolete = False
                    in_term = True
                    continue

                if line.startswith("[") and line.endswith("]"):
                    if in_term:
                        _flush_term()
                    in_term = False
                    continue

                if not in_term:
                    continue

                if line.startswith("id: "):
                    current_id = line[4:].strip()
                elif line.startswith("name: "):
                    current_name = line[6:].strip()
                elif line.startswith("is_obsolete: true"):
                    is_obsolete = True
                elif line.startswith("is_a: "):
                    parent = line[6:].split("!")[0].strip()
                    if parent.startswith("DOID:"):
                        current_parents.append(parent)
                elif line.startswith("xref: "):
                    xref = line[6:].strip()
                    current_xrefs.append(xref)

        if in_term:
            _flush_term()

        logger.info(
            "Parsed doid.obo: %d terms, %d xrefs indexed",
            len(self._doid_names),
            sum(len(v) for v in [
                self.umls_to_doid, self.mesh_to_doid, self.efo_to_doid,
                self.omim_to_doid, self.nci_to_doid,
            ])
        )

    def _index_xref(self, doid: str, xref: str):
        """Index a single xref string from the OBO file."""
        if xref.startswith("UMLS_CUI:"):
            cui = xref[9:].strip()
            self.umls_to_doid[cui] = doid
            self.umls_to_doid[f"UMLS:{cui}"] = doid
            self._doid_to_umls[doid].add(cui)
        elif xref.startswith("MESH:"):
            mesh = xref[5:].strip()
            self.mesh_to_doid[mesh] = doid
            self.mesh_to_doid[f"MESH:{mesh}"] = doid
            self._doid_to_mesh[doid].add(mesh)
        elif xref.startswith("EFO:"):
            efo = xref[4:].strip()
            self.efo_to_doid[f"EFO:{efo}"] = doid
            self.efo_to_doid[f"EFO_{efo}"] = doid
            self.efo_to_doid[efo] = doid
        elif xref.startswith("NCI:"):
            nci = xref[4:].strip()
            self.nci_to_doid[nci] = doid
            self.nci_to_doid[f"NCI:{nci}"] = doid
        elif xref.startswith("OMIM:"):
            omim = xref[5:].strip()
            self.omim_to_doid[omim] = doid
            self.omim_to_doid[f"OMIM:{omim}"] = doid
        elif xref.startswith("MONDO:"):
            mondo = xref.strip()
            self.mondo_to_doid[mondo] = doid
        elif xref.startswith("ICD10CM:"):
            icd = xref[8:].strip()
            self.icd10_to_doid[icd] = doid
            self.icd10_to_doid[f"ICD10:{icd}"] = doid

    # ------------------------------------------------------------------
    # DOID subtype tree operations
    # ------------------------------------------------------------------

    def get_doid_descendants(self, root_doids: List[str]) -> Set[str]:
        """
        Get all DOID IDs that are descendants (subtypes) of the given root DOIDs.
        Uses BFS over the is_a tree (child → parent).
        """
        # Build child → parents already stored; we need parent → children
        parent_to_children: Dict[str, Set[str]] = defaultdict(set)
        for child, parents in self._doid_parents.items():
            for parent in parents:
                parent_to_children[parent].add(child)

        descendants = set(root_doids)
        queue = list(root_doids)
        while queue:
            current = queue.pop(0)
            for child in parent_to_children.get(current, set()):
                if child not in descendants:
                    descendants.add(child)
                    queue.append(child)

        return descendants

    def get_cvd_mesh_ids(self, cvd_root_doids: List[str]) -> Set[str]:
        """Get all MeSH IDs for CVD diseases (including subtypes)."""
        cvd_doids = self.get_doid_descendants(cvd_root_doids)
        mesh_ids = set()
        for doid in cvd_doids:
            mesh_ids.update(self._doid_to_mesh.get(doid, set()))
        return mesh_ids

    def get_cvd_umls_cuis(self, cvd_root_doids: List[str]) -> Set[str]:
        """Get all UMLS CUIs for CVD diseases (including subtypes)."""
        cvd_doids = self.get_doid_descendants(cvd_root_doids)
        umls_cuis = set()
        for doid in cvd_doids:
            umls_cuis.update(self._doid_to_umls.get(doid, set()))
        return umls_cuis

    def get_cvd_doid_set(self, cvd_root_doids: List[str]) -> Set[str]:
        """Get all DOID IDs in the CVD subtree."""
        return self.get_doid_descendants(cvd_root_doids)

    # ------------------------------------------------------------------
    # Mapping file I/O
    # ------------------------------------------------------------------

    def _load_mapping_file(self, filename: str, target_dict: Dict[str, str]):
        """Load a TSV mapping file into a dictionary."""
        filepath = self.mappings_dir / filename
        if not filepath.exists():
            return

        try:
            count = 0
            with open(filepath, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f, delimiter='\t')
                for row in reader:
                    source_id = row.get('source_id', '').strip()
                    target_id = row.get('target_id', '').strip()
                    if source_id and target_id and source_id not in target_dict:
                        target_dict[source_id] = target_id
                        target_dict[source_id.lower()] = target_id
                        count += 1
            if count:
                logger.info(f"Loaded {count} new mappings from {filename}")
        except Exception as e:
            logger.warning(f"Failed to load {filename}: {e}")

    def _extract_disease_xrefs(self, processed_dir: Path):
        """Extract additional mappings from Disease Ontology slim_terms.tsv."""
        do_path = processed_dir / "disease_ontology" / "slim_terms.tsv"
        if not do_path.exists():
            return

        try:
            added = 0
            with open(do_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f, delimiter='\t')
                for row in reader:
                    doid = row.get('doid', '').strip()
                    if not doid:
                        continue
                    doid_full = f"DOID:{doid}" if not doid.startswith("DOID:") else doid

                    umls = row.get('umls_cui', '').strip()
                    if umls and umls not in self.umls_to_doid:
                        self.umls_to_doid[umls] = doid_full
                        self.umls_to_doid[f"UMLS:{umls}"] = doid_full
                        added += 1

            if added:
                logger.info(f"Extracted {added} additional UMLS→DOID mappings from slim_terms")
        except Exception as e:
            logger.warning(f"Failed to extract disease xrefs: {e}")

    def _extract_gene_xrefs(self, processed_dir: Path):
        """Extract ENSP → NCBIGene mappings from gene data."""
        gene_path = processed_dir / "ncbigene" / "genes.tsv"
        if not gene_path.exists():
            return
        logger.info("Gene xref extraction: ENSP mapping requires external data")

    # ------------------------------------------------------------------
    # Public mapping methods
    # ------------------------------------------------------------------

    def map_to_doid(self, disease_id: str) -> Optional[str]:
        """
        Map any disease ID to DOID format.
        Supports: EFO, MESH, UMLS, MONDO, OMIM, NCI, ICD10, and raw DOID IDs.
        """
        if not disease_id:
            return None

        disease_id = disease_id.strip()

        if disease_id.startswith("DOID:"):
            return disease_id

        # EFO format: EFO_0000318 or EFO:0000318
        if disease_id.startswith("EFO"):
            if disease_id in self.efo_to_doid:
                return self.efo_to_doid[disease_id]
            alt = disease_id.replace("EFO_", "EFO:").replace("EFO:", "EFO_")
            if alt in self.efo_to_doid:
                return self.efo_to_doid[alt]

        # MESH format
        if disease_id.startswith("MESH:") or disease_id.startswith("MeSH:"):
            clean = disease_id.split(":", 1)[1]
            if clean in self.mesh_to_doid:
                return self.mesh_to_doid[clean]
            if f"MESH:{clean}" in self.mesh_to_doid:
                return self.mesh_to_doid[f"MESH:{clean}"]
        elif disease_id.startswith("D") and disease_id[1:].isdigit():
            if disease_id in self.mesh_to_doid:
                return self.mesh_to_doid[disease_id]

        # UMLS format
        if disease_id.startswith("UMLS:") or disease_id.startswith("UMLS_CUI:"):
            clean = disease_id.split(":", 1)[1]
            if clean in self.umls_to_doid:
                return self.umls_to_doid[clean]
        if disease_id.startswith("C") and len(disease_id) >= 7 and disease_id[1:].isdigit():
            if disease_id in self.umls_to_doid:
                return self.umls_to_doid[disease_id]

        # MONDO format
        if disease_id.startswith("MONDO:"):
            if disease_id in self.mondo_to_doid:
                return self.mondo_to_doid[disease_id]

        # OMIM format
        if disease_id.startswith("OMIM:"):
            clean = disease_id[5:]
            if clean in self.omim_to_doid:
                return self.omim_to_doid[clean]
            if disease_id in self.omim_to_doid:
                return self.omim_to_doid[disease_id]

        # MedGen format: MedGen:CXXXXXXX → extract CUI
        if disease_id.startswith("MedGen:"):
            cui = disease_id[7:]
            if cui.startswith("C") and cui[1:].isdigit():
                if cui in self.umls_to_doid:
                    return self.umls_to_doid[cui]

        # NCI format
        if disease_id.startswith("NCI:"):
            clean = disease_id[4:]
            if clean in self.nci_to_doid:
                return self.nci_to_doid[clean]

        # ICD10 format
        if disease_id.startswith("ICD10:") or disease_id.startswith("ICD10CM:"):
            clean = disease_id.split(":", 1)[1]
            if clean in self.icd10_to_doid:
                return self.icd10_to_doid[clean]

        return None

    def map_to_uberon(self, tissue_id: str) -> Optional[str]:
        """Map BTO or other tissue ID to UBERON format."""
        if not tissue_id:
            return None
        if tissue_id.startswith("UBERON:"):
            return tissue_id
        if tissue_id.startswith("BTO:"):
            return self.bto_to_uberon.get(tissue_id)
        return None

    def map_to_ncbigene(self, gene_id: str) -> Optional[str]:
        """Map ENSP or other gene ID to NCBIGene format."""
        if not gene_id:
            return None
        if gene_id.startswith("NCBIGene:"):
            return gene_id
        if gene_id.startswith("ENSP"):
            return self.ensp_to_ncbigene.get(gene_id)
        return None
