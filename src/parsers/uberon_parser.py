#!/usr/bin/env python3
"""Uberon anatomy parser & loader."""
import argparse, csv, urllib.request
from pathlib import Path
from neo4j import GraphDatabase

RAW_DIR = Path("./data/raw/uberon")
PROC_DIR = Path("./data/processed/uberon")
BOLT_URL = "bolt://localhost:7688"

URL = "http://purl.obolibrary.org/obo/uberon.obo"

def download():
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    out = RAW_DIR / "uberon.obo"
    if out.exists():
        print(f"[skip] {out}"); return
    print(f"[download] {URL}")
    urllib.request.urlretrieve(URL, out)

def parse():
    PROC_DIR.mkdir(parents=True, exist_ok=True)
    terms = []
    cur = None
    with open(RAW_DIR/"uberon.obo") as f:
        for line in f:
            line = line.rstrip("\n")
            if line == "[Term]":
                if cur: terms.append(cur)
                cur = {"synonyms":[]}
            elif line.startswith("[") and cur is not None:
                terms.append(cur); cur=None
            elif cur is not None and ":" in line:
                k,_,v = line.partition(": ")
                if k=="id" and v.startswith("UBERON:"): cur["id"]=v
                elif k=="name": cur["name"]=v
                elif k=="def" and v.startswith('"'):
                    end = v.rfind('"')
                    cur["definition"] = v[1:end] if end>0 else v
                elif k=="synonym" and v.startswith('"'):
                    end = v.find('"',1)
                    if end>0: cur["synonyms"].append(v[1:end])
                elif k=="is_obsolete" and v=="true": cur["obsolete"]=True
    if cur: terms.append(cur)
    terms = [t for t in terms if t.get("id") and not t.get("obsolete")]
    print(f"[parse] {len(terms)} Uberon terms")
    with open(PROC_DIR/"uberon_terms.tsv","w",newline="") as f:
        w = csv.writer(f, delimiter="\t")
        w.writerow(["xrefUberon","name","definition","synonyms"])
        for t in terms:
            w.writerow([t["id"], t.get("name",""), t.get("definition",""), "|".join(t.get("synonyms",[]))])

def load():
    driver = GraphDatabase.driver(BOLT_URL, auth=None)
    with driver.session() as session:
        session.run("CREATE INDEX ON :BodyPart(xrefUberon)")
        session.run("CREATE INDEX ON :BodyPart(name)")
        rows = []
        with open(PROC_DIR/"uberon_terms.tsv") as f:
            r = csv.DictReader(f, delimiter="\t")
            for row in r: rows.append(row)
        print(f"[load] {len(rows)} BodyPart nodes")
        for i in range(0, len(rows), 1000):
            batch = rows[i:i+1000]
            for b in batch:
                b["synonyms_list"] = b["synonyms"].split("|") if b["synonyms"] else []
            session.run(
                "UNWIND $rows AS row "
                "MERGE (b:BodyPart {xrefUberon: row.xrefUberon}) "
                "SET b.name = row.name, b.definition = row.definition, "
                "b.synonyms = row.synonyms_list, b.source = 'Uberon'",
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
