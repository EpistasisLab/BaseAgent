#!/usr/bin/env python3
"""Reactome parser & loader for CardioKB."""
import argparse, csv, os, urllib.request
from pathlib import Path
from neo4j import GraphDatabase

RAW_DIR = Path("./data/raw/reactome")
PROC_DIR = Path("./data/processed/reactome")
BOLT_URL = "bolt://localhost:7688"

URLS = {
    "NCBI2Reactome_All_Levels.txt": "https://reactome.org/download/current/NCBI2Reactome_All_Levels.txt",
    "ReactomePathways.txt": "https://reactome.org/download/current/ReactomePathways.txt",
}

def download():
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    for name, url in URLS.items():
        out = RAW_DIR / name
        if out.exists():
            print(f"[skip] {out}"); continue
        print(f"[download] {url}")
        urllib.request.urlretrieve(url, out)

def parse():
    PROC_DIR.mkdir(parents=True, exist_ok=True)
    # Pathways: id\tname\tspecies
    pathways = {}
    with open(RAW_DIR/"ReactomePathways.txt") as f:
        for line in f:
            parts = line.rstrip("\n").split("\t")
            if len(parts) >= 3 and parts[2] == "Homo sapiens":
                pathways[parts[0]] = {"reactomeId": parts[0], "pathwayName": parts[1], "species": parts[2]}
    print(f"[parse] {len(pathways)} human pathways")
    out_p = PROC_DIR / "pathways.tsv"
    with open(out_p, "w", newline="") as f:
        w = csv.writer(f, delimiter="\t")
        w.writerow(["reactomeId","pathwayName","species"])
        for p in pathways.values():
            w.writerow([p["reactomeId"], p["pathwayName"], p["species"]])
    # Gene-pathway: ncbi_gene_id\tpathway_id\turl\tname\tevidence\tspecies
    edges = []
    seen = set()
    with open(RAW_DIR/"NCBI2Reactome_All_Levels.txt") as f:
        for line in f:
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 6: continue
            ncbi, pwid, _, _, _, species = parts[:6]
            if species != "Homo sapiens": continue
            if pwid not in pathways: continue
            key = (ncbi, pwid)
            if key in seen: continue
            seen.add(key)
            edges.append({"ncbiGeneId": ncbi, "reactomeId": pwid})
    print(f"[parse] {len(edges)} gene-pathway edges")
    out_e = PROC_DIR / "gene_pathway.tsv"
    with open(out_e, "w", newline="") as f:
        w = csv.writer(f, delimiter="\t")
        w.writerow(["ncbiGeneId","reactomeId"])
        for e in edges:
            w.writerow([e["ncbiGeneId"], e["reactomeId"]])

def load():
    driver = GraphDatabase.driver(BOLT_URL, auth=None)
    with driver.session() as session:
        session.run("CREATE INDEX ON :Pathway(pathwayName)")
        session.run("CREATE INDEX ON :Pathway(pathwayId)")
        pathways = []
        with open(PROC_DIR/"pathways.tsv") as f:
            r = csv.DictReader(f, delimiter="\t")
            for row in r: pathways.append(row)
        print(f"[load] {len(pathways)} Pathway nodes")
        for i in range(0, len(pathways), 1000):
            batch = pathways[i:i+1000]
            session.run(
                "UNWIND $rows AS row "
                "MERGE (p:Pathway {pathwayName: row.pathwayName}) "
                "SET p.reactomeId = row.reactomeId, p.species = row.species, p.source='Reactome', "
                "p.url = 'https://reactome.org/PathwayBrowser/#/' + row.reactomeId, "
                "p.pathwayId = row.reactomeId",
                rows=batch
            )
        edges = []
        with open(PROC_DIR/"gene_pathway.tsv") as f:
            r = csv.DictReader(f, delimiter="\t")
            for row in r: edges.append(row)
        # Build mapping from reactomeId -> pathwayName for matching
        pw_name = {p["reactomeId"]: p["pathwayName"] for p in pathways}
        edges = [{"ncbiGeneId": e["ncbiGeneId"], "pathwayName": pw_name[e["reactomeId"]]} 
                 for e in edges if e["reactomeId"] in pw_name]
        print(f"[load] {len(edges)} gene-pathway edges")
        for i in range(0, len(edges), 2000):
            batch = edges[i:i+2000]
            session.run(
                "UNWIND $rows AS row "
                "MATCH (g:Gene {ncbiGeneId: row.ncbiGeneId}) "
                "MATCH (p:Pathway {pathwayName: row.pathwayName}) "
                "MERGE (g)-[r1:geneInPathway]->(p) ON CREATE SET r1.source='Reactome' "
                "MERGE (p)-[r2:pathwayContainsGene]->(g) ON CREATE SET r2.source='Reactome'",
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
