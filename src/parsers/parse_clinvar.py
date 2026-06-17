#!/usr/bin/env python3
"""
ClinVar Variant Parser for CardioKB Knowledge Graph
====================================================
Downloads and parses ClinVar variant_summary.txt.gz,
filters for CVD-relevant variants, and loads them into
Memgraph at bolt://localhost:7688.

Usage:
    python parse_clinvar.py [--download] [--load]
"""

import gzip
import re
import json
import argparse
import os
import urllib.request
import pandas as pd
from neo4j import GraphDatabase

# ── Configuration ──────────────────────────────────────────────────────────────
CLINVAR_URL = "https://ftp.ncbi.nlm.nih.gov/pub/clinvar/tab_delimited/variant_summary.txt.gz"
RAW_PATH    = "./data/raw/variant_summary.txt.gz"
OUT_DIR     = "./data/processed/clinvar"
BOLT_URI    = "bolt://localhost:7688"

CVD_KEYWORDS = [
    "heart", "coronary", "myocardial", "atrial", "cardiomyopathy", "aortic",
    "hypertension", "stroke", "atherosclerosis", "cardiac", "ventricular",
    "pulmonary", "valve", "endocarditis", "pericarditis", "aneurysm",
    "artery", "vein", "thrombosis", "embolism", "congenital", "arrhythmia",
    "angina"
]

PATHOGENIC_TERMS = ["Pathogenic", "Likely pathogenic", "Pathogenic/Likely pathogenic"]

USECOLS = [
    "#AlleleID", "VariationID", "Type", "GeneSymbol", "GeneID",
    "ClinicalSignificance", "RS# (dbSNP)", "PhenotypeIDS", "PhenotypeList",
    "Assembly", "Chromosome", "Start", "Stop",
    "ReferenceAllele", "AlternateAllele",
    "ReferenceAlleleVCF", "AlternateAlleleVCF", "PositionVCF",
    "ReviewStatus", "Name", "ClinSigSimple"
]

# ── Helpers ────────────────────────────────────────────────────────────────────

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
    parts = re.split(r"[|,]+", str(phenotype_str))
    for part in parts:
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


# ── Download ───────────────────────────────────────────────────────────────────

def download_clinvar(force=False):
    if os.path.exists(RAW_PATH) and not force:
        print(f"ClinVar file already exists at {RAW_PATH}")
        return
    os.makedirs(os.path.dirname(RAW_PATH), exist_ok=True)
    print(f"Downloading {CLINVAR_URL} ...")

    def progress(count, block, total):
        if total > 0 and count % 500 == 0:
            pct = count * block * 100 / total
            print(f"  {pct:.1f}%", end="\r")

    urllib.request.urlretrieve(CLINVAR_URL, RAW_PATH, reporthook=progress)
    print("\nDownload complete.")


# ── Parse & Filter ─────────────────────────────────────────────────────────────

def parse_and_filter(driver):
    """Parse ClinVar file and return filtered DataFrames."""
    os.makedirs(OUT_DIR, exist_ok=True)

    # ── Fetch gene & disease info from Memgraph ──
    with driver.session() as session:
        gene_recs = session.run("MATCH (g:Gene) RETURN g.geneSymbol AS sym")
        gene_symbols = {r["sym"] for r in gene_recs}

        dis_recs = session.run("""
            MATCH (d:Disease)
            RETURN d.xrefDiseaseOntology AS doid,
                   d.xrefOMIM AS omim, d.xrefUMLS AS umls
        """)
        omim_map, umls_map = {}, {}
        for r in dis_recs:
            doid = r["doid"]
            if not doid:
                continue
            if r["omim"]:
                for oid in str(r["omim"]).split("|"):
                    omim_map[oid.strip()] = doid
            if r["umls"]:
                for uid in str(r["umls"]).split("|"):
                    umls_map[uid.strip()] = doid

    print(f"Loaded {len(gene_symbols)} gene symbols, "
          f"{len(omim_map)} OMIM->DOID, {len(umls_map)} UMLS->DOID mappings")

    # ── Read ClinVar (GRCh38 only) ──
    print("Reading ClinVar file (GRCh38)...")
    with gzip.open(RAW_PATH, "rt", encoding="utf-8") as fh:
        df = pd.read_csv(fh, sep="\t", usecols=USECOLS, low_memory=False)

    df = df[df["Assembly"] == "GRCh38"].copy()
    print(f"GRCh38 rows: {len(df):,}")

    # ── Filter CVD genes ──
    df = df[df["GeneSymbol"].apply(lambda x: has_cvd_gene(x, gene_symbols))].copy()
    print(f"CVD gene rows: {len(df):,}")

    # ── Map diseases ──
    df["matched_doids"] = df["PhenotypeIDS"].apply(
        lambda x: parse_phenotype_ids(x, omim_map, umls_map)
    )
    df["has_cvd_disease"] = df["matched_doids"].apply(bool)
    df["is_pathogenic"]   = df["ClinicalSignificance"].apply(is_pathogenic)

    df = df[df["is_pathogenic"] | df["has_cvd_disease"]].copy()
    df = df.drop_duplicates(subset=["VariationID"], keep="first")
    print(f"Filtered variants: {len(df):,}")

    # ── Build Variant nodes ──
    df["variantId"]          = df["VariationID"].astype(str)
    df["rsId"]               = df["RS# (dbSNP)"].apply(build_rs_id)
    df["clinicalSignificance"] = df["ClinicalSignificance"].apply(clean_value)
    df["reviewStatus"]       = df["ReviewStatus"].apply(clean_value)
    df["variantType"]        = df["Type"].apply(clean_value)
    df["chromosomePosition"] = df.apply(build_chrom_pos, axis=1)
    df["referenceAllele"]    = df["ReferenceAlleleVCF"].apply(clean_value)
    df["alternateAllele"]    = df["AlternateAlleleVCF"].apply(clean_value)
    df["hgvs"]               = df["Name"].apply(lambda x: clean_value(x)[:500])

    variant_cols = ["variantId", "rsId", "clinicalSignificance", "reviewStatus",
                    "variantType", "chromosomePosition", "referenceAllele",
                    "alternateAllele", "hgvs"]
    df_variants = df[variant_cols].copy()

    # ── Build Gene-Variant edges ──
    gv_rows = []
    for _, row in df.iterrows():
        vid = str(row["VariationID"])
        for g in str(row["GeneSymbol"]).split(";"):
            g = g.strip()
            if g in gene_symbols:
                gv_rows.append({"geneSymbol": g, "variantId": vid, "source": "ClinVar"})
    df_gv = pd.DataFrame(gv_rows).drop_duplicates()

    # ── Build Disease-Variant edges ──
    dv_rows = []
    for _, row in df.iterrows():
        vid = str(row["VariationID"])
        for doid in row["matched_doids"]:
            dv_rows.append({"xrefDiseaseOntology": doid, "variantId": vid, "source": "ClinVar"})
    df_dv = pd.DataFrame(dv_rows).drop_duplicates() if dv_rows else pd.DataFrame()

    # ── Save TSVs ──
    df_variants.to_csv(f"{OUT_DIR}/variant_nodes.tsv",       sep="\t", index=False)
    df_gv.to_csv(      f"{OUT_DIR}/gene_variant_edges.tsv",  sep="\t", index=False)
    df_dv.to_csv(      f"{OUT_DIR}/disease_variant_edges.tsv", sep="\t", index=False)

    summary = {
        "total_variants": len(df_variants),
        "total_gene_variant_edges": len(df_gv),
        "total_disease_variant_edges": len(df_dv),
        "unique_genes": int(df_gv["geneSymbol"].nunique()),
        "unique_diseases": int(df_dv["xrefDiseaseOntology"].nunique()) if len(df_dv) > 0 else 0,
    }
    with open(f"{OUT_DIR}/summary.json", "w") as fh:
        json.dump(summary, fh, indent=2)

    print("Saved TSV files to", OUT_DIR)
    print(json.dumps(summary, indent=2))
    return df_variants, df_gv, df_dv


# ── Load into Memgraph ─────────────────────────────────────────────────────────

BATCH_SIZE = 500

def load_variants(driver, df_variants):
    print(f"\nLoading {len(df_variants):,} Variant nodes...")
    records = df_variants.to_dict("records")
    loaded = 0
    with driver.session() as session:
        for i in range(0, len(records), BATCH_SIZE):
            batch = records[i:i + BATCH_SIZE]
            session.run("""
                UNWIND $rows AS row
                MERGE (v:Variant {variantId: row.variantId})
                SET v.rsId                 = row.rsId,
                    v.clinicalSignificance = row.clinicalSignificance,
                    v.reviewStatus         = row.reviewStatus,
                    v.variantType          = row.variantType,
                    v.chromosomePosition   = row.chromosomePosition,
                    v.referenceAllele      = row.referenceAllele,
                    v.alternateAllele      = row.alternateAllele,
                    v.hgvs                 = row.hgvs
            """, rows=batch)
            loaded += len(batch)
            if loaded % 10000 == 0 or loaded == len(records):
                print(f"  Variants loaded: {loaded:,}/{len(records):,}")
    print("Variant nodes done.")


def load_gene_variant_edges(driver, df_gv):
    print(f"\nLoading {len(df_gv):,} Gene-Variant edges...")
    records = df_gv.to_dict("records")
    loaded = 0
    with driver.session() as session:
        for i in range(0, len(records), BATCH_SIZE):
            batch = records[i:i + BATCH_SIZE]
            session.run("""
                UNWIND $rows AS row
                MATCH (g:Gene    {geneSymbol: row.geneSymbol})
                MATCH (v:Variant {variantId:  row.variantId})
                MERGE (g)-[:hasVariant    {source: "ClinVar"}]->(v)
                MERGE (v)-[:variantInGene {source: "ClinVar"}]->(g)
            """, rows=batch)
            loaded += len(batch)
            if loaded % 10000 == 0 or loaded == len(records):
                print(f"  Gene-Variant edges loaded: {loaded:,}/{len(records):,}")
    print("Gene-Variant edges done.")


def load_disease_variant_edges(driver, df_dv):
    if df_dv is None or len(df_dv) == 0:
        print("No Disease-Variant edges to load.")
        return
    print(f"\nLoading {len(df_dv):,} Disease-Variant edges...")
    records = df_dv.to_dict("records")
    loaded = 0
    with driver.session() as session:
        for i in range(0, len(records), BATCH_SIZE):
            batch = records[i:i + BATCH_SIZE]
            session.run("""
                UNWIND $rows AS row
                MATCH (d:Disease {xrefDiseaseOntology: row.xrefDiseaseOntology})
                MATCH (v:Variant {variantId:           row.variantId})
                MERGE (d)-[:associatedWithVariant      {source: "ClinVar"}]->(v)
                MERGE (v)-[:variantAssociatedWithDisease {source: "ClinVar"}]->(d)
            """, rows=batch)
            loaded += len(batch)
            if loaded % 10000 == 0 or loaded == len(records):
                print(f"  Disease-Variant edges loaded: {loaded:,}/{len(records):,}")
    print("Disease-Variant edges done.")


def create_indexes(driver):
    print("\nCreating indexes on Variant nodes...")
    with driver.session() as session:
        session.run("CREATE INDEX ON :Variant(variantId);")
        session.run("CREATE INDEX ON :Variant(rsId);")
        session.run("CREATE INDEX ON :Variant(clinicalSignificance);")
    print("Indexes created.")


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Parse and load ClinVar data into Memgraph")
    parser.add_argument("--download", action="store_true", help="Force re-download of ClinVar file")
    parser.add_argument("--load",     action="store_true", help="Load data into Memgraph")
    args = parser.parse_args()

    driver = GraphDatabase.driver(BOLT_URI, auth=None)

    if args.download or not os.path.exists(RAW_PATH):
        download_clinvar(force=args.download)

    df_variants, df_gv, df_dv = parse_and_filter(driver)

    if args.load:
        create_indexes(driver)
        load_variants(driver, df_variants)
        load_gene_variant_edges(driver, df_gv)
        load_disease_variant_edges(driver, df_dv)

    driver.close()
    print("\nDone.")


if __name__ == "__main__":
    main()
