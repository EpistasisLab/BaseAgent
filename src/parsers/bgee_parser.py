#!/usr/bin/env python3
"""
Bgee Expression Parser & Loader for CardioKB
Source: https://www.bgee.org/ftp/
Creates: bodyPartOverexpressesGene, bodyPartUnderexpressesGene edges (BodyPart -> Gene)
         (geneExpressedInBodyPart edges also derived from "present" calls)

Usage:
    python bgee_parser.py --download
    python bgee_parser.py --parse
    python bgee_parser.py --load
    python bgee_parser.py --all
"""

import argparse
import gzip
import json
import os
import sys
import urllib.request
import pandas as pd
from neo4j import GraphDatabase

DB_URI = "bolt://localhost:7688"
DATA_DIR = "./data/processed/bgee"
RAW_URL = "https://www.bgee.org/ftp/current/download/calls/expr_calls/Homo_sapiens_expr_simple.tsv.gz"
CVD_GENES_FILE = "./data/processed/cvd_genes.json"
BATCH_SIZE = 500

OVER_EXPRESSION_SCORE_THRESHOLD = 75.0
UNDER_EXPRESSION_CALL = "absent"


def get_driver():
    return GraphDatabase.driver(DB_URI, auth=None)


def download():
    os.makedirs(DATA_DIR, exist_ok=True)
    out = os.path.join(DATA_DIR, "Homo_sapiens_expr_simple.tsv.gz")
    if os.path.exists(out):
        print(f"[download] Already present: {out}")
        return out
    print(f"[download] Fetching {RAW_URL}")
    urllib.request.urlretrieve(RAW_URL, out)
    print(f"[download] Saved {out}")
    return out


def load_db_uberon():
    driver = get_driver()
    with driver.session() as session:
        result = session.run("MATCH (b:BodyPart) RETURN b.xrefUberon AS uid")
        uberon = {r["uid"] for r in result if r["uid"]}
    driver.close()
    return uberon


def load_db_gene_ensembl_map():
    """Map Ensembl ID -> geneSymbol for all genes in the graph."""
    driver = get_driver()
    mapping = {}
    with driver.session() as session:
        result = session.run("MATCH (g:Gene) RETURN g.geneSymbol AS sym, g.xrefEnsembl AS ens")
        for r in result:
            sym = r["sym"]
            ens = r["ens"]
            if not sym:
                continue
            if isinstance(ens, list):
                for e in ens:
                    if e:
                        mapping[e] = sym
            elif ens:
                mapping[ens] = sym
    driver.close()
    # Fallback: also map CVD JSON if available
    if os.path.exists(CVD_GENES_FILE):
        with open(CVD_GENES_FILE) as f:
            cvd = json.load(f)
        for g in cvd.get("full", []):
            if g.get("ensembl") and g.get("symbol"):
                mapping.setdefault(g["ensembl"], g["symbol"])
    print(f"[parse] Ensembl->Symbol map size: {len(mapping):,}")
    return mapping


def parse(gz_file=None):
    os.makedirs(DATA_DIR, exist_ok=True)
    gz_file = gz_file or os.path.join(DATA_DIR, "Homo_sapiens_expr_simple.tsv.gz")
    if not os.path.exists(gz_file):
        print(f"[parse] Missing raw file: {gz_file}; run --download first")
        sys.exit(1)

    ens2sym = load_db_gene_ensembl_map()
    db_uberon = load_db_uberon()
    print(f"[parse] BodyPart UBERON set: {len(db_uberon):,}")

    chunks = []
    total = 0
    with gzip.open(gz_file, "rt") as f:
        for chunk in pd.read_csv(f, sep="\t", quotechar='"', chunksize=100_000):
            total += len(chunk)
            mask_gene = chunk["Gene ID"].isin(ens2sym)
            mask_uberon = chunk["Anatomical entity ID"].isin(db_uberon)
            filt = chunk[mask_gene & mask_uberon].copy()
            if len(filt):
                chunks.append(filt)
    df = pd.concat(chunks, ignore_index=True) if chunks else pd.DataFrame()
    print(f"[parse] Raw rows: {total:,}, filtered: {len(df):,}")
    if df.empty:
        return

    df["geneSymbol"] = df["Gene ID"].map(ens2sym)
    df = df.rename(columns={"Anatomical entity ID": "xrefUberon"})

    df_over = df[
        (df["Expression"] == "present") &
        (df["Expression score"] >= OVER_EXPRESSION_SCORE_THRESHOLD)
    ][["geneSymbol", "xrefUberon", "Expression score", "Expression rank", "Call quality"]]
    df_over = df_over.sort_values("Expression score", ascending=False)\
        .drop_duplicates(subset=["geneSymbol", "xrefUberon"])
    df_over.to_csv(os.path.join(DATA_DIR, "bodypart_overexpresses_gene.tsv"), sep="\t", index=False)
    print(f"[parse] Overexpression: {len(df_over):,}")

    df_under = df[df["Expression"] == UNDER_EXPRESSION_CALL][
        ["geneSymbol", "xrefUberon", "Expression score", "Expression rank", "Call quality"]
    ].drop_duplicates(subset=["geneSymbol", "xrefUberon"])
    df_under.to_csv(os.path.join(DATA_DIR, "bodypart_underexpresses_gene.tsv"), sep="\t", index=False)
    print(f"[parse] Underexpression: {len(df_under):,}")


def _load_directional(driver, tsv_path, rel_type):
    df = pd.read_csv(tsv_path, sep="\t")
    print(f"[load] {rel_type}: {len(df):,} rows")
    query = f"""
    UNWIND $rows AS row
    MATCH (b:BodyPart {{xrefUberon: row.xrefUberon}})
    MATCH (g:Gene {{geneSymbol: row.geneSymbol}})
    MERGE (b)-[r:{rel_type} {{source: "Bgee"}}]->(g)
    ON CREATE SET r.expressionScore = row.expressionScore,
                  r.expressionRank  = row.expressionRank,
                  r.callQuality     = row.callQuality
    """
    n = 0
    with driver.session() as session:
        for i in range(0, len(df), BATCH_SIZE):
            batch = df.iloc[i:i+BATCH_SIZE]
            rows = [{
                "xrefUberon": r["xrefUberon"],
                "geneSymbol": r["geneSymbol"],
                "expressionScore": float(r["Expression score"]),
                "expressionRank": float(r["Expression rank"]) if pd.notna(r["Expression rank"]) else None,
                "callQuality": r["Call quality"],
            } for _, r in batch.iterrows()]
            session.run(query, rows=rows)
            n += len(rows)
    print(f"[load] {rel_type}: done {n:,}")
    return n


def load():
    driver = get_driver()
    over_path = os.path.join(DATA_DIR, "bodypart_overexpresses_gene.tsv")
    under_path = os.path.join(DATA_DIR, "bodypart_underexpresses_gene.tsv")
    if not (os.path.exists(over_path) and os.path.exists(under_path)):
        print("[load] Missing parsed TSVs; run --parse first")
        sys.exit(1)
    pre_over = _count_rel(driver, "bodyPartOverexpressesGene", "Bgee")
    pre_under = _count_rel(driver, "bodyPartUnderexpressesGene", "Bgee")
    _load_directional(driver, over_path, "bodyPartOverexpressesGene")
    _load_directional(driver, under_path, "bodyPartUnderexpressesGene")
    post_over = _count_rel(driver, "bodyPartOverexpressesGene", "Bgee")
    post_under = _count_rel(driver, "bodyPartUnderexpressesGene", "Bgee")
    print(f"[load] bodyPartOverexpressesGene[Bgee]: {pre_over:,} -> {post_over:,} (delta={post_over-pre_over})")
    print(f"[load] bodyPartUnderexpressesGene[Bgee]: {pre_under:,} -> {post_under:,} (delta={post_under-pre_under})")
    driver.close()


def _count_rel(driver, rtype, source):
    with driver.session() as session:
        res = session.run(f"MATCH ()-[r:{rtype} {{source: $s}}]->() RETURN count(r) AS c", s=source)
        return res.single()["c"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--download", action="store_true")
    ap.add_argument("--parse", action="store_true")
    ap.add_argument("--load", action="store_true")
    ap.add_argument("--all", action="store_true")
    a = ap.parse_args()
    if a.all or a.download:
        download()
    if a.all or a.parse:
        parse()
    if a.all or a.load:
        load()
    if not (a.download or a.parse or a.load or a.all):
        ap.print_help()


if __name__ == "__main__":
    main()
