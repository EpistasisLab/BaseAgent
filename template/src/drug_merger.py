"""
Drug node merge utility for the KG pipeline.

Merges Drug nodes across DrugBank, DrugCentral, and CTD to eliminate
duplicate drug entries. Creates a canonical drug ID for each unique drug
and updates edge files to reference the canonical IDs.

Merge strategy:
1. DrugBank drugs are the primary reference (drugbankId is canonical)
2. DrugCentral drugs match via drugbank_id, then CAS number, then name
3. CTD chemicals match via MeSH ID (against DrugCentral), then name

After merge:
- DrugCentral drugs.tsv uses drugbank_id as primary ID where matched
- CTD chemical_nodes.tsv uses drugbank_id as primary ID where matched
- Edge files are updated to use canonical drug IDs
"""

import logging
import re
from pathlib import Path
from typing import Dict, Optional, Tuple

import pandas as pd

logger = logging.getLogger(__name__)


def normalize_drug_name(name: str) -> str:
    """Normalize a drug name for matching."""
    if not name or not isinstance(name, str):
        return ""
    name = name.lower().strip()
    name = re.sub(r'\s+', ' ', name)
    name = re.sub(r'[^a-z0-9 ]', '', name)
    return name


def merge_drug_nodes(processed_dir: Path) -> Dict[str, int]:
    """
    Merge Drug nodes across DrugBank, DrugCentral, and CTD.

    Returns dict with merge stats.
    """
    stats = {
        "drugbank_total": 0,
        "drugcentral_total": 0,
        "ctd_total": 0,
        "dc_matched_by_dbid": 0,
        "dc_matched_by_cas": 0,
        "dc_matched_by_name": 0,
        "ctd_matched_by_mesh": 0,
        "ctd_matched_by_name": 0,
        "duplicates_eliminated": 0,
    }

    db_dir = processed_dir / "drugbank"
    dc_dir = processed_dir / "drugcentral"
    ctd_dir = processed_dir / "ctd"

    # Load DrugBank drugs (primary)
    db_path = db_dir / "drugs.tsv"
    if not db_path.exists():
        logger.warning("DrugBank drugs.tsv not found; skipping drug merge")
        return stats

    db_df = pd.read_csv(db_path, sep="\t", dtype=str).fillna("")
    stats["drugbank_total"] = len(db_df)

    # Build DrugBank lookup indices
    dbid_col = "drugbankId" if "drugbankId" in db_df.columns else "drugbank_id"
    name_col = "commonName" if "commonName" in db_df.columns else "drug_name"
    cas_col = "casNumber" if "casNumber" in db_df.columns else "cas_number"

    db_by_id = {row[dbid_col]: row[dbid_col] for _, row in db_df.iterrows() if row[dbid_col]}
    db_by_name = {}
    for _, row in db_df.iterrows():
        norm = normalize_drug_name(row.get(name_col, ""))
        if norm and row[dbid_col]:
            db_by_name[norm] = row[dbid_col]
    db_by_cas = {}
    for _, row in db_df.iterrows():
        cas = str(row.get(cas_col, "")).strip()
        if cas and cas != "" and row[dbid_col]:
            db_by_cas[cas] = row[dbid_col]

    logger.info("DrugBank: %d drugs, %d names indexed, %d CAS numbers",
                len(db_df), len(db_by_name), len(db_by_cas))

    # ---- Merge DrugCentral ----
    dc_path = dc_dir / "drugs.tsv"
    dc_remap = {}  # struct_id → canonical drugbank_id

    if dc_path.exists():
        dc_df = pd.read_csv(dc_path, sep="\t", dtype=str).fillna("")
        stats["drugcentral_total"] = len(dc_df)

        # Build DrugCentral mesh_id → struct_id lookup (for CTD matching later)
        dc_mesh_to_struct = {}
        for _, row in dc_df.iterrows():
            mesh = str(row.get("mesh_id", "")).strip()
            if mesh:
                dc_mesh_to_struct[mesh] = row["struct_id"]

        for _, row in dc_df.iterrows():
            struct_id = row["struct_id"]
            dc_dbid = str(row.get("drugbank_id", "")).strip()
            dc_cas = str(row.get("cas_number", "")).strip()
            dc_name = normalize_drug_name(row.get("drug_name", ""))

            canonical = None

            # Match by DrugBank ID
            if dc_dbid and dc_dbid in db_by_id:
                canonical = dc_dbid
                stats["dc_matched_by_dbid"] += 1
            # Match by CAS number
            elif dc_cas and dc_cas in db_by_cas:
                canonical = db_by_cas[dc_cas]
                stats["dc_matched_by_cas"] += 1
            # Match by normalized name
            elif dc_name and dc_name in db_by_name:
                canonical = db_by_name[dc_name]
                stats["dc_matched_by_name"] += 1

            if canonical:
                dc_remap[struct_id] = canonical

        logger.info("DrugCentral merge: %d/%d matched to DrugBank (dbid=%d, cas=%d, name=%d)",
                    len(dc_remap), len(dc_df),
                    stats["dc_matched_by_dbid"], stats["dc_matched_by_cas"],
                    stats["dc_matched_by_name"])

        # Add DrugCentral mesh_id → drugbank_id mappings for CTD
        dc_mesh_to_dbid = {}
        for struct_id, dbid in dc_remap.items():
            for mesh, sid in dc_mesh_to_struct.items():
                if sid == struct_id:
                    dc_mesh_to_dbid[mesh] = dbid

    # ---- Merge CTD ----
    ctd_path = ctd_dir / "chemical_nodes.tsv"
    ctd_remap = {}  # chemical_id → canonical drugbank_id

    if ctd_path.exists():
        ctd_df = pd.read_csv(ctd_path, sep="\t", dtype=str).fillna("")
        stats["ctd_total"] = len(ctd_df)

        for _, row in ctd_df.iterrows():
            chem_id = row["chemical_id"]
            mesh_id = str(row.get("mesh_id", "")).strip()
            chem_name = normalize_drug_name(row.get("chemical_name", ""))

            canonical = None

            # Match via DrugCentral MeSH → DrugBank
            if mesh_id and mesh_id in dc_mesh_to_dbid:
                canonical = dc_mesh_to_dbid[mesh_id]
                stats["ctd_matched_by_mesh"] += 1
            elif mesh_id:
                # Try stripped MeSH ID
                stripped = mesh_id.replace("MESH:", "")
                if stripped in dc_mesh_to_dbid:
                    canonical = dc_mesh_to_dbid[stripped]
                    stats["ctd_matched_by_mesh"] += 1

            # Match by normalized name
            if not canonical and chem_name and chem_name in db_by_name:
                canonical = db_by_name[chem_name]
                stats["ctd_matched_by_name"] += 1

            if canonical:
                ctd_remap[chem_id] = canonical

        logger.info("CTD merge: %d/%d matched to DrugBank (mesh=%d, name=%d)",
                    len(ctd_remap), len(ctd_df),
                    stats["ctd_matched_by_mesh"], stats["ctd_matched_by_name"])

    # ---- Update DrugCentral drugs.tsv ----
    if dc_path.exists() and dc_remap:
        dc_df["canonical_drugbank_id"] = dc_df["struct_id"].map(dc_remap)
        dc_df.to_csv(dc_path, sep="\t", index=False)
        logger.info("Updated DrugCentral drugs.tsv with canonical_drugbank_id")

        # Update DrugCentral edge files
        _update_edge_files(dc_dir, "struct_id", dc_remap)

    # ---- Update CTD chemical_nodes.tsv ----
    if ctd_path.exists() and ctd_remap:
        ctd_df["canonical_drugbank_id"] = ctd_df["chemical_id"].map(ctd_remap)
        ctd_df.to_csv(ctd_path, sep="\t", index=False)
        logger.info("Updated CTD chemical_nodes.tsv with canonical_drugbank_id")

        # Update CTD edge files
        _update_edge_files(ctd_dir, "chemical_id", ctd_remap)

    stats["duplicates_eliminated"] = len(dc_remap) + len(ctd_remap)

    logger.info("Drug merge complete: %d duplicates eliminated "
                "(DrugCentral: %d, CTD: %d)",
                stats["duplicates_eliminated"], len(dc_remap), len(ctd_remap))

    return stats


def _update_edge_files(source_dir: Path, id_column: str, remap: Dict[str, str]):
    """Update edge TSV files to use canonical drug IDs where matched."""
    edge_files = list(source_dir.glob("*_edges.tsv")) + list(source_dir.glob("*_edge*.tsv"))
    for edge_file in edge_files:
        try:
            df = pd.read_csv(edge_file, sep="\t", dtype=str)
            if id_column in df.columns:
                original = df[id_column].copy()
                df[id_column] = df[id_column].map(lambda x: remap.get(x, x))
                changed = (original != df[id_column]).sum()
                if changed > 0:
                    df.to_csv(edge_file, sep="\t", index=False)
                    logger.info("  Updated %s: %d/%d rows remapped", edge_file.name, changed, len(df))
        except Exception as exc:
            logger.warning("  Failed to update %s: %s", edge_file.name, exc)
