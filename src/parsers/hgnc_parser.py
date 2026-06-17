#!/usr/bin/env python3
"""HGNC gene families parser & loader."""
import argparse, csv, urllib.request, json
from pathlib import Path
from neo4j import GraphDatabase

RAW_DIR = Path("./data/raw/hgnc")
PROC_DIR = Path("./data/processed/hgnc")
BOLT_URL = "bolt://localhost:7688"

# HGNC stores families in genenames.org BioMart and downloadable TSV
URLS = {
    "family.csv": "https://storage.googleapis.com/public-download-files/hgnc/csv/csv/genefamily_db_tables/family.csv",
    "hierarchy.csv": "https://storage.googleapis.com/public-download-files/hgnc/csv/csv/genefamily_db_tables/hierarchy.csv",
    "family_alias.csv": "https://storage.googleapis.com/public-download-files/hgnc/csv/csv/genefamily_db_tables/family_alias.csv",
    "gene_has_family.csv": "https://storage.googleapis.com/public-download-files/hgnc/csv/csv/genefamily_db_tables/gene_has_family.csv",
    "hgnc_complete_set.txt": "https://storage.googleapis.com/public-download-files/hgnc/tsv/tsv/hgnc_complete_set.txt",
}

def download():
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    for name, url in URLS.items():
        out = RAW_DIR / name
        if out.exists(): 
            print(f"[skip] {out}"); continue
        try:
            print(f"[download] {url}")
            urllib.request.urlretrieve(url, out)
        except Exception as e:
            print(f"[warn] failed {url}: {e}")

def parse():
    PROC_DIR.mkdir(parents=True, exist_ok=True)
    # Parse family.csv (id, name, ...)
    families = {}
    fpath = RAW_DIR / "family.csv"
    if fpath.exists():
        with open(fpath, newline="") as f:
            r = csv.DictReader(f)
            for row in r:
                fid = row.get("id") or row.get("family_id")
                fname = row.get("name") or row.get("family_name")
                if fid and fname:
                    families[fid] = {"familyId": fid, "familyName": fname}
    print(f"[parse] {len(families)} families")
    with open(PROC_DIR/"families.tsv","w",newline="") as f:
        w = csv.writer(f, delimiter="\t")
        w.writerow(["familyId","familyName"])
        for fam in families.values():
            w.writerow([fam["familyId"], fam["familyName"]])
    
    # Parse gene families from hgnc_complete_set: gene_group (pipe-sep names) and gene_group_id (pipe-sep ids)
    edges = []
    hgnc_set = RAW_DIR / "hgnc_complete_set.txt"
    if hgnc_set.exists():
        with open(hgnc_set) as f:
            r = csv.DictReader(f, delimiter="\t")
            for row in r:
                gs = row.get("symbol","")
                gids = row.get("gene_group_id","")
                gnames = row.get("gene_group","")
                if not gs or not gids: continue
                for gid in gids.split("|"):
                    gid = gid.strip()
                    if gid:
                        edges.append({"geneSymbol":gs,"familyId":gid})
    # alternate: gene_has_family.csv (gene_id family_id ...)
    ghf = RAW_DIR/"gene_has_family.csv"
    if not edges and ghf.exists():
        with open(ghf) as f:
            r = csv.DictReader(f)
            for row in r:
                gid = row.get("gene_id"); fid = row.get("family_id")
                if gid and fid: edges.append({"geneSymbol":gid,"familyId":fid})
    print(f"[parse] {len(edges)} gene-family edges")
    with open(PROC_DIR/"gene_family.tsv","w",newline="") as f:
        w = csv.writer(f, delimiter="\t")
        w.writerow(["geneSymbol","familyId"])
        for e in edges:
            w.writerow([e["geneSymbol"], e["familyId"]])

def load():
    driver = GraphDatabase.driver(BOLT_URL, auth=None)
    with driver.session() as session:
        session.run("CREATE INDEX ON :GeneFamily(familyId)")
        session.run("CREATE INDEX ON :GeneFamily(familyName)")
        fams = []
        with open(PROC_DIR/"families.tsv") as f:
            r = csv.DictReader(f, delimiter="\t")
            for row in r: fams.append(row)
        print(f"[load] {len(fams)} GeneFamily nodes")
        for i in range(0, len(fams), 500):
            batch = fams[i:i+500]
            session.run(
                "UNWIND $rows AS row "
                "MERGE (f:GeneFamily {familyId: row.familyId}) "
                "SET f.familyName = row.familyName, f.source = 'HGNC'",
                rows=batch
            )
        edges = []
        with open(PROC_DIR/"gene_family.tsv") as f:
            r = csv.DictReader(f, delimiter="\t")
            for row in r: edges.append(row)
        print(f"[load] {len(edges)} gene-family edges")
        for i in range(0, len(edges), 2000):
            batch = edges[i:i+2000]
            session.run(
                "UNWIND $rows AS row "
                "MATCH (g:Gene {geneSymbol: row.geneSymbol}) "
                "MATCH (f:GeneFamily {familyId: row.familyId}) "
                "MERGE (g)-[r1:geneInFamily]->(f) ON CREATE SET r1.source='HGNC Families' "
                "MERGE (f)-[r2:familyContainsGene]->(g) ON CREATE SET r2.source='HGNC Families'",
                rows=batch
            )
    driver.close()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--download", action="store_true")
    ap.add_argument("--parse", action="store_true")
    ap.add_argument("--load", action="store_true")
    ap.add_argument("--all", action="store_true")
    args = ap.parse_args()
    if args.all or args.download: download()
    if args.all or args.parse: parse()
    if args.all or args.load: load()
    if not any([args.download,args.parse,args.load,args.all]):
        ap.print_help()

if __name__ == "__main__":
    main()
