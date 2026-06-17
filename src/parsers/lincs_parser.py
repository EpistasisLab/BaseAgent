#!/usr/bin/env python3
"""
LINCS L1000 Expression Parser & Loader for CardioKB
Source: https://maayanlab.cloud/sigcom-lincs/
Creates:
    - geneRegulatesGene  (Gene -> Gene)
    - compoundUpregulatesGene   (Drug -> Gene)
    - compoundDownregulatesGene (Drug -> Gene)

Usage:
    python lincs_parser.py --download
    python lincs_parser.py --parse
    python lincs_parser.py --load
    python lincs_parser.py --all
"""

import argparse
import json
import os
import sys
import urllib.request
import pandas as pd
from neo4j import GraphDatabase

DB_URI = "bolt://localhost:7688"
LINCS_DIR = "./data/processed/lincs"          # gene_regulates_gene + raw compound edges
LINCS_L1000_DIR = "./data/processed/lincs_l1000"  # canonicalized compound edges (Drug.commonName)
BATCH_SIZE = 500


def get_driver():
    return GraphDatabase.driver(DB_URI, auth=None)


def download():
    os.makedirs(LINCS_DIR, exist_ok=True)
    os.makedirs(LINCS_L1000_DIR, exist_ok=True)
    # LINCS L1000 data is large; this is a placeholder for the SigCom LINCS API endpoints.
    print("[download] LINCS L1000 raw data is fetched via SigCom LINCS API (see https://maayanlab.cloud/sigcom-lincs/).")
    print("[download] Pre-fetched processed files expected under ./data/processed/lincs/ and ./data/processed/lincs_l1000/")
    for f in ["gene_regulates_gene.tsv", "compound_up_edges.tsv", "compound_down_edges.tsv"]:
        p = os.path.join(LINCS_DIR, f)
        print(f"  {p}: {'OK' if os.path.exists(p) else 'MISSING'}")
    for f in ["compound_upregulates_gene.tsv", "compound_downregulates_gene.tsv"]:
        p = os.path.join(LINCS_L1000_DIR, f)
        print(f"  {p}: {'OK' if os.path.exists(p) else 'MISSING'}")


def _normalize(s):
    return s.lower().strip() if isinstance(s, str) else ""


def _build_drug_lookup(driver):
    lookup = {}
    with driver.session() as session:
        res = session.run("MATCH (d:Drug) RETURN d.commonName AS name, d.drugAliases AS aliases")
        for r in res:
            n = r["name"]
            if n:
                lookup[_normalize(n)] = n
            aliases = r["aliases"] or []
            if isinstance(aliases, str):
                aliases = [aliases]
            for a in aliases:
                if a:
                    lookup.setdefault(_normalize(a), n)
    return lookup


def _build_gene_set(driver):
    with driver.session() as session:
        res = session.run("MATCH (g:Gene) RETURN g.geneSymbol AS s")
        return {r["s"] for r in res if r["s"]}


def parse():
    """Filter raw LINCS exports to genes/drugs present in graph."""
    os.makedirs(LINCS_DIR, exist_ok=True)
    os.makedirs(LINCS_L1000_DIR, exist_ok=True)
    driver = get_driver()
    genes = _build_gene_set(driver)
    drugs = _build_drug_lookup(driver)
    print(f"[parse] Graph genes: {len(genes):,}, drugs(+aliases): {len(drugs):,}")

    # geneRegulatesGene
    grg_in = os.path.join(LINCS_DIR, "gene_regulates_gene.tsv")
    if os.path.exists(grg_in):
        grg = pd.read_csv(grg_in, sep="\t")
        grg = grg[grg["source"].isin(genes) & grg["target"].isin(genes)].copy()
        grg = grg.drop_duplicates(subset=["source", "target"])
        grg.to_csv(os.path.join(LINCS_DIR, "gene_regulates_gene.filtered.tsv"), sep="\t", index=False)
        print(f"[parse] geneRegulatesGene: {len(grg):,}")

    # compound up/down
    for direction, raw, canon in [
        ("up",   "compound_up_edges.tsv",   "compound_upregulates_gene.tsv"),
        ("down", "compound_down_edges.tsv", "compound_downregulates_gene.tsv"),
    ]:
        raw_p = os.path.join(LINCS_DIR, raw)
        canon_p = os.path.join(LINCS_L1000_DIR, canon)
        if os.path.exists(canon_p):
            df = pd.read_csv(canon_p, sep="\t")
            df = df[df["geneSymbol"].isin(genes)].copy()
            # Make sure commonName matches a Drug in graph (canonical name)
            drug_names = set(drugs.values())
            df = df[df["commonName"].isin(drug_names)]
            df = df.drop_duplicates(subset=["commonName", "geneSymbol"])
            df.to_csv(canon_p, sep="\t", index=False)
            print(f"[parse] compound{direction.capitalize()}regulatesGene: {len(df):,}")
        elif os.path.exists(raw_p):
            df = pd.read_csv(raw_p, sep="\t")
            df["drug_norm"] = df["drug"].apply(_normalize)
            df["commonName"] = df["drug_norm"].map(drugs)
            df = df[df["commonName"].notna() & df["gene"].isin(genes)].copy()
            df = df.rename(columns={"gene": "geneSymbol"})
            df = df[["commonName", "geneSymbol"]].drop_duplicates()
            df.to_csv(canon_p, sep="\t", index=False)
            print(f"[parse] compound{direction.capitalize()}regulatesGene: {len(df):,}")
    driver.close()


def _count_rel(driver, rtype, source):
    with driver.session() as session:
        res = session.run(f"MATCH ()-[r:{rtype} {{source: $s}}]->() RETURN count(r) AS c", s=source)
        return res.single()["c"]


def _load_grg(driver):
    p = os.path.join(LINCS_DIR, "gene_regulates_gene.filtered.tsv")
    if not os.path.exists(p):
        p = os.path.join(LINCS_DIR, "gene_regulates_gene.tsv")
    if not os.path.exists(p):
        print("[load] No geneRegulatesGene file")
        return 0
    df = pd.read_csv(p, sep="\t")
    print(f"[load] geneRegulatesGene rows: {len(df):,}")
    query = """
    UNWIND $rows AS row
    MATCH (g1:Gene {geneSymbol: row.src})
    MATCH (g2:Gene {geneSymbol: row.tgt})
    MERGE (g1)-[r:geneRegulatesGene {source: "LINCS"}]->(g2)
    ON CREATE SET r.is_stimulation = row.stim,
                  r.is_inhibition  = row.inh
    """
    pre = _count_rel(driver, "geneRegulatesGene", "LINCS")
    n = 0
    with driver.session() as session:
        for i in range(0, len(df), BATCH_SIZE):
            batch = df.iloc[i:i+BATCH_SIZE]
            rows = [{
                "src": r["source"],
                "tgt": r["target"],
                "stim": bool(r.get("is_stimulation", False)),
                "inh":  bool(r.get("is_inhibition",  False)),
            } for _, r in batch.iterrows()]
            session.run(query, rows=rows)
            n += len(rows)
    post = _count_rel(driver, "geneRegulatesGene", "LINCS")
    print(f"[load] geneRegulatesGene[LINCS]: {pre:,} -> {post:,} (delta={post-pre})")
    return post


def _load_compound(driver, direction):
    rtype = "compoundUpregulatesGene" if direction == "up" else "compoundDownregulatesGene"
    fname = "compound_upregulates_gene.tsv" if direction == "up" else "compound_downregulates_gene.tsv"
    p = os.path.join(LINCS_L1000_DIR, fname)
    if not os.path.exists(p):
        print(f"[load] Missing {p}")
        return 0
    df = pd.read_csv(p, sep="\t")
    print(f"[load] {rtype} rows: {len(df):,}")
    query = f"""
    UNWIND $rows AS row
    MATCH (d:Drug {{commonName: row.commonName}})
    MATCH (g:Gene {{geneSymbol: row.geneSymbol}})
    MERGE (d)-[r:{rtype} {{source: "LINCS L1000"}}]->(g)
    """
    pre = _count_rel(driver, rtype, "LINCS L1000")
    n = 0
    with driver.session() as session:
        for i in range(0, len(df), BATCH_SIZE):
            rows = df.iloc[i:i+BATCH_SIZE][["commonName", "geneSymbol"]].to_dict("records")
            session.run(query, rows=rows)
            n += len(rows)
    post = _count_rel(driver, rtype, "LINCS L1000")
    print(f"[load] {rtype}[LINCS L1000]: {pre:,} -> {post:,} (delta={post-pre})")
    return post


def load():
    driver = get_driver()
    _load_grg(driver)
    _load_compound(driver, "up")
    _load_compound(driver, "down")
    driver.close()


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
