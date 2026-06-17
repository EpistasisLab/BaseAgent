#!/usr/bin/env python3
"""HPO phenotype parser & loader."""
import argparse, csv, urllib.request
from pathlib import Path
from neo4j import GraphDatabase

RAW_DIR = Path("./data/raw/hpo")
PROC_DIR = Path("./data/processed/hpo")
BOLT_URL = "bolt://localhost:7688"

URLS = {
    "genes_to_phenotype.txt": "https://github.com/obophenotype/human-phenotype-ontology/releases/latest/download/genes_to_phenotype.txt",
    "hp.obo": "http://purl.obolibrary.org/obo/hp.obo",
}

def download():
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    for name, url in URLS.items():
        out = RAW_DIR / name
        if out.exists():
            print(f"[skip] {out}"); continue
        print(f"[download] {url}")
        urllib.request.urlretrieve(url, out)

def parse_obo(path):
    terms = {}
    cur = None
    with open(path) as f:
        for line in f:
            line = line.rstrip("\n")
            if line == "[Term]":
                if cur and "id" in cur: terms[cur["id"]] = cur
                cur = {}
            elif line.startswith("[") and cur is not None:
                if "id" in cur: terms[cur["id"]] = cur
                cur = None
            elif cur is not None and ":" in line:
                k, _, v = line.partition(": ")
                if k == "id" and v.startswith("HP:"): cur["id"] = v
                elif k == "name": cur["name"] = v
                elif k == "def" and v.startswith('"'):
                    end = v.rfind('"')
                    cur["definition"] = v[1:end] if end>0 else v
    if cur and "id" in cur: terms[cur["id"]] = cur
    return terms

def parse():
    PROC_DIR.mkdir(parents=True, exist_ok=True)
    hp_terms = parse_obo(RAW_DIR/"hp.obo")
    print(f"[parse] {len(hp_terms)} HPO terms in ontology")
    # genes_to_phenotype.txt columns: ncbi_gene_id, gene_symbol, hpo_id, hpo_name, ...
    phenotypes = {}
    edges = set()
    with open(RAW_DIR/"genes_to_phenotype.txt") as f:
        header = f.readline()
        for line in f:
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 4: continue
            ncbi, gsym, hpo_id, hpo_name = parts[0], parts[1], parts[2], parts[3]
            if not hpo_id.startswith("HP:"): continue
            defn = hp_terms.get(hpo_id, {}).get("definition", "")
            phenotypes[hpo_id] = {"xrefHPO":hpo_id, "name":hpo_name, "definition":defn}
            edges.add((gsym, hpo_id))
    print(f"[parse] {len(phenotypes)} phenotypes, {len(edges)} edges")
    with open(PROC_DIR/"phenotypes.tsv","w",newline="") as f:
        w = csv.writer(f, delimiter="\t")
        w.writerow(["xrefHPO","name","definition"])
        for p in phenotypes.values():
            w.writerow([p["xrefHPO"], p["name"], p["definition"]])
    with open(PROC_DIR/"gene_phenotype.tsv","w",newline="") as f:
        w = csv.writer(f, delimiter="\t")
        w.writerow(["geneSymbol","xrefHPO"])
        for gs, hp in edges:
            w.writerow([gs, hp])

def load():
    driver = GraphDatabase.driver(BOLT_URL, auth=None)
    with driver.session() as session:
        session.run("CREATE INDEX ON :Phenotype(xrefHPO)")
        session.run("CREATE INDEX ON :Phenotype(name)")
        phs = []
        with open(PROC_DIR/"phenotypes.tsv") as f:
            r = csv.DictReader(f, delimiter="\t")
            for row in r: phs.append(row)
        print(f"[load] {len(phs)} Phenotype nodes")
        for i in range(0, len(phs), 1000):
            batch = phs[i:i+1000]
            session.run(
                "UNWIND $rows AS row "
                "MERGE (p:Phenotype {xrefHPO: row.xrefHPO}) "
                "SET p.name = row.name, p.definition = row.definition",
                rows=batch
            )
        edges = []
        with open(PROC_DIR/"gene_phenotype.tsv") as f:
            r = csv.DictReader(f, delimiter="\t")
            for row in r: edges.append(row)
        print(f"[load] {len(edges)} gene-phenotype edges")
        for i in range(0, len(edges), 2000):
            batch = edges[i:i+2000]
            session.run(
                "UNWIND $rows AS row "
                "MATCH (g:Gene {geneSymbol: row.geneSymbol}) "
                "MATCH (p:Phenotype {xrefHPO: row.xrefHPO}) "
                "MERGE (g)-[r:geneAssociatesWithPhenotype]->(p) "
                "ON CREATE SET r.source='HPO'",
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
