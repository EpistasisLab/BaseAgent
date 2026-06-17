#!/usr/bin/env python3
"""
ClinVar Variant Parser & Loader for CardioKB Knowledge Graph
==============================================================
Downloads and parses ClinVar variant_summary.txt.gz, filters for
CVD-relevant variants (linked via CVD genes or CVD-scoped Disease
nodes through OMIM/MedGen xrefs), and loads them into Memgraph
at bolt://localhost:7688 with idempotent MERGE-only semantics.

Edges created (all carry `source: 'ClinVar'`):
  (Gene)-[:hasVariant]->(Variant)
  (Variant)-[:variantInGene]->(Gene)
  (Disease)-[:associatedWithVariant]->(Variant)
  (Variant)-[:variantAssociatedWithDisease]->(Disease)

Usage:
    python clinvar_parser.py [--download] [--parse] [--load]
"""

import gzip
import re
import json
import argparse
import os
import urllib.request
import pandas as pd
from neo4j import GraphDatabase

# ── Configuration ───────────────────────────────────────────────────────────────
CLINVAR_URL = "https://ftp.ncbi.nlm.nih.gov/pub/clinvar/tab_delimited/variant_summary.txt.gz"
RAW_PATH    = "./data/raw/variant_summary.txt.gz"
OUT_DIR     = "./data/processed/clinvar"
BOLT_URI    = "bolt://localhost:7688"
BATCH_SIZE  = 500

PATHOGENIC_TERMS = ["Pathogenic", "Likely pathogenic", "Pathogenic/Likely pathogenic"]

USECOLS = [
    "#AlleleID", "VariationID", "Type", "GeneSymbol", "GeneID",
    "ClinicalSignificance", "RS# (dbSNP)", "PhenotypeIDS", "PhenotypeList",
    "Assembly", "Chromosome", "Start", "Stop",
    "ReferenceAllele", "AlternateAllele",
    "ReferenceAlleleVCF", "AlternateAlleleVCF", "PositionVCF",
    "ReviewStatus", "Name", "ClinSigSimple",
]

# ── Helpers ─────────────────────────────────────────────────────────────────────
def clean_value(val, default=""):
    if pd.isna(val) or str(val).strip() in ["-", "na", "NA", "N/A", ""]:
        return default
    return str(val).strip()


def build_chrom_pos(row):
    chrom = clean_value(row["Chromosome"])
    start = clean_value(row["Start"])
    if chrom and start and start != "0":
        return f"chr{chrom}:{start}"
    return ""


def build_rs_id(val):
    s = str(val)
    if pd.isna(val) or s in ["-1", "na", "-", ""]:
        return ""
    try:
        return f"rs{int(float(s))}"
    except (ValueError, TypeError):
        return ""


def parse_phenotype_ids(phenotype_str, omim_map, umls_map):
    """Extract matched DOIDs from ClinVar PhenotypeIDS string."""
    if pd.isna(phenotype_str) or str(phenotype_str).strip() in ["-", "na", ""]:
        return []
    doids = set()
    for part in re.split(r"[|,]+", str(phenotype_str)):
        part = part.strip()
        omim_m = re.search(r"OMIM:(\d+)", part)
        if omim_m and omim_m.group(1) in omim_map:
            doids.add(omim_map[omim_m.group(1)])
        umls_m = re.search(r"MedGen:(C\d+)", part)
        if umls_m and umls_m.group(1) in umls_map:
            doids.add(umls_map[umls_m.group(1)])
    return list(doids)


def has_cvd_gene(gene_str, gene_symbols):
    if pd.isna(gene_str):
        return False
    return any(g.strip() in gene_symbols for g in str(gene_str).split(";"))


def is_pathogenic(sig):
    if pd.isna(sig):
        return False
    return any(t in str(sig) for t in PATHOGENIC_TERMS)


# ── Download ────────────────────────────────────────────────────────────────────
def download_clinvar(force=False):
    if os.path.exists(RAW_PATH) and not force:
        print(f"ClinVar already present: {RAW_PATH}")
        return
    os.makedirs(os.path.dirname(RAW_PATH), exist_ok=True)
    print(f"Downloading {CLINVAR_URL}...")
    urllib.request.urlretrieve(CLINVAR_URL, RAW_PATH)
    print("Download complete.")


# ── Parse & Filter ──────────────────────────────────────────────────────────────
def parse_and_filter(driver):
    os.makedirs(OUT_DIR, exist_ok=True)

    with driver.session() as session:
        gene_symbols = {r["sym"] for r in session.run(
            "MATCH (g:Gene) RETURN g.geneSymbol AS sym"
        )}
        omim_map, umls_map = {}, {}
        for r in session.run("""
            MATCH (d:Disease)
            RETURN d.xrefDiseaseOntology AS doid,
                   d.xrefOMIM AS omim, d.xrefUMLS AS umls
        """):
            doid = r["doid"]
            if not doid:
                continue
            if r["omim"]:
                for oid in str(r["omim"]).split("|"):
                    omim_map[oid.strip()] = doid
            if r["umls"]:
                for uid in str(r["umls"]).split("|"):
                    umls_map[uid.strip()] = doid

    print(f"Genes: {len(gene_symbols)}, OMIM->DOID: {len(omim_map)}, "
          f"UMLS->DOID: {len(umls_map)}")

    print("Reading ClinVar (GRCh38)...")
    with gzip.open(RAW_PATH, "rt", encoding="utf-8") as fh:
        df = pd.read_csv(fh, sep="\t", usecols=USECOLS, low_memory=False)

    df = df[df["Assembly"] == "GRCh38"].copy()
    df = df[df["GeneSymbol"].apply(lambda x: has_cvd_gene(x, gene_symbols))].copy()

    df["matched_doids"] = df["PhenotypeIDS"].apply(
        lambda x: parse_phenotype_ids(x, omim_map, umls_map)
    )
    df["has_cvd_disease"] = df["matched_doids"].apply(bool)
    df["is_pathogenic"]   = df["ClinicalSignificance"].apply(is_pathogenic)

    df = df[df["is_pathogenic"] | df["has_cvd_disease"]].copy()
    df = df.drop_duplicates(subset=["VariationID"], keep="first")

    df["variantId"]            = df["VariationID"].astype(str)
    df["rsId"]                 = df["RS# (dbSNP)"].apply(build_rs_id)
    df["clinicalSignificance"] = df["ClinicalSignificance"].apply(clean_value)
    df["reviewStatus"]         = df["ReviewStatus"].apply(clean_value)
    df["variantType"]          = df["Type"].apply(clean_value)
    df["chromosomePosition"]   = df.apply(build_chrom_pos, axis=1)
    df["referenceAllele"]      = df["ReferenceAlleleVCF"].apply(clean_value)
    df["alternateAllele"]      = df["AlternateAlleleVCF"].apply(clean_value)
    df["hgvs"]                 = df["Name"].apply(lambda x: clean_value(x)[:500])

    variant_cols = ["variantId", "rsId", "clinicalSignificance", "reviewStatus",
                    "variantType", "chromosomePosition", "referenceAllele",
                    "alternateAllele", "hgvs"]
    df_variants = df[variant_cols].copy()

    gv_rows, dv_rows = [], []
    for _, row in df.iterrows():
        vid = str(row["VariationID"])
        for g in str(row["GeneSymbol"]).split(";"):
            g = g.strip()
            if g in gene_symbols:
                gv_rows.append({"geneSymbol": g, "variantId": vid, "source": "ClinVar"})
        for doid in row["matched_doids"]:
            dv_rows.append({"xrefDiseaseOntology": doid, "variantId": vid, "source": "ClinVar"})

    df_gv = pd.DataFrame(gv_rows).drop_duplicates()
    df_dv = pd.DataFrame(dv_rows).drop_duplicates() if dv_rows else pd.DataFrame()

    df_variants.to_csv(f"{OUT_DIR}/variant_nodes.tsv",         sep="\t", index=False)
    df_gv.to_csv(      f"{OUT_DIR}/gene_variant_edges.tsv",    sep="\t", index=False)
    df_dv.to_csv(      f"{OUT_DIR}/disease_variant_edges.tsv", sep="\t", index=False)

    summary = {
        "total_variants": len(df_variants),
        "total_gene_variant_edges": len(df_gv),
        "total_disease_variant_edges": len(df_dv),
        "unique_genes": int(df_gv["geneSymbol"].nunique()) if len(df_gv) else 0,
        "unique_diseases": int(df_dv["xrefDiseaseOntology"].nunique()) if len(df_dv) else 0,
    }
    with open(f"{OUT_DIR}/summary.json", "w") as fh:
        json.dump(summary, fh, indent=2)

    print("Saved processed TSVs to", OUT_DIR)
    print(json.dumps(summary, indent=2))
    return df_variants, df_gv, df_dv


# ── Idempotent Loaders ──────────────────────────────────────────────────────────
def load_variants(driver, df_variants):
    """MERGE Variant nodes by variantId, only filling in missing properties."""
    print(f"\nLoading {len(df_variants):,} Variant nodes (idempotent)...")
    records = df_variants.to_dict("records")
    with driver.session() as session:
        for i in range(0, len(records), BATCH_SIZE):
            batch = records[i:i + BATCH_SIZE]
            session.run("""
                UNWIND $rows AS row
                MERGE (v:Variant {variantId: row.variantId})
                SET v.rsId                 = coalesce(v.rsId, row.rsId),
                    v.clinicalSignificance = coalesce(v.clinicalSignificance, row.clinicalSignificance),
                    v.reviewStatus         = coalesce(v.reviewStatus, row.reviewStatus),
                    v.variantType          = coalesce(v.variantType, row.variantType),
                    v.chromosomePosition   = coalesce(v.chromosomePosition, row.chromosomePosition),
                    v.referenceAllele      = coalesce(v.referenceAllele, row.referenceAllele),
                    v.alternateAllele      = coalesce(v.alternateAllele, row.alternateAllele),
                    v.hgvs                 = coalesce(v.hgvs, row.hgvs)
            """, rows=batch)
    print("Variant nodes done.")


def load_gene_variant_edges(driver, df_gv):
    """MERGE (Gene)-[:hasVariant]->(Variant) and inverse; only if Gene exists."""
    print(f"\nLoading {len(df_gv):,} Gene-Variant edges...")
    records = df_gv.to_dict("records")
    with driver.session() as session:
        for i in range(0, len(records), BATCH_SIZE):
            batch = records[i:i + BATCH_SIZE]
            session.run("""
                UNWIND $rows AS row
                MATCH (g:Gene    {geneSymbol: row.geneSymbol})
                MATCH (v:Variant {variantId : row.variantId})
                MERGE (g)-[r1:hasVariant]->(v)
                  ON CREATE SET r1.source = row.source
                MERGE (v)-[r2:variantInGene]->(g)
                  ON CREATE SET r2.source = row.source
            """, rows=batch)
    print("Gene-Variant edges done.")


def load_disease_variant_edges(driver, df_dv):
    """MERGE (Disease)-[:associatedWithVariant]->(Variant) and inverse."""
    if df_dv is None or len(df_dv) == 0:
        return
    print(f"\nLoading {len(df_dv):,} Disease-Variant edges...")
    records = df_dv.to_dict("records")
    with driver.session() as session:
        for i in range(0, len(records), BATCH_SIZE):
            batch = records[i:i + BATCH_SIZE]
            session.run("""
                UNWIND $rows AS row
                MATCH (d:Disease {xrefDiseaseOntology: row.xrefDiseaseOntology})
                MATCH (v:Variant {variantId: row.variantId})
                MERGE (d)-[r1:associatedWithVariant]->(v)
                  ON CREATE SET r1.source = row.source
                MERGE (v)-[r2:variantAssociatedWithDisease]->(d)
                  ON CREATE SET r2.source = row.source
            """, rows=batch)
    print("Disease-Variant edges done.")


def report_counts(driver):
    with driver.session() as session:
        v = session.run("MATCH (v:Variant) RETURN count(v) AS c").single()["c"]
        hv = session.run("MATCH ()-[r:hasVariant]->() RETURN count(r) AS c").single()["c"]
        vig = session.run("MATCH ()-[r:variantInGene]->() RETURN count(r) AS c").single()["c"]
        awv = session.run("MATCH ()-[r:associatedWithVariant]->() RETURN count(r) AS c").single()["c"]
        vawd = session.run("MATCH ()-[r:variantAssociatedWithDisease]->() RETURN count(r) AS c").single()["c"]
    print("\n=== ClinVar Load Report ===")
    print(f"Variant nodes:                       {v:,}")
    print(f"hasVariant edges:                    {hv:,}")
    print(f"variantInGene edges:                 {vig:,}")
    print(f"associatedWithVariant edges:         {awv:,}")
    print(f"variantAssociatedWithDisease edges:  {vawd:,}")


# ── Main ────────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--download", action="store_true", help="Download raw file")
    parser.add_argument("--parse",    action="store_true", help="Parse and filter")
    parser.add_argument("--load",     action="store_true", help="Load into Memgraph")
    parser.add_argument("--all",      action="store_true", help="Run all steps")
    args = parser.parse_args()

    if args.all:
        args.download = args.parse = args.load = True

    if args.download:
        download_clinvar()

    driver = GraphDatabase.driver(BOLT_URI, auth=None)
    try:
        if args.parse:
            parse_and_filter(driver)

        if args.load:
            df_v  = pd.read_csv(f"{OUT_DIR}/variant_nodes.tsv",         sep="\t", dtype=str).fillna("")
            df_gv = pd.read_csv(f"{OUT_DIR}/gene_variant_edges.tsv",    sep="\t", dtype=str).fillna("")
            df_dv = pd.read_csv(f"{OUT_DIR}/disease_variant_edges.tsv", sep="\t", dtype=str).fillna("")
            load_variants(driver, df_v)
            load_gene_variant_edges(driver, df_gv)
            load_disease_variant_edges(driver, df_dv)

        report_counts(driver)
    finally:
        driver.close()


if __name__ == "__main__":
    main()
