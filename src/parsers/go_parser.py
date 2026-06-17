#!/usr/bin/env python3
"""Gene Ontology parser & loader for CardioKB."""
import argparse, gzip, os, sys, urllib.request, csv
from pathlib import Path
from neo4j import GraphDatabase

RAW_DIR = Path("./data/raw/gene_ontology")
PROC_DIR = Path("./data/processed/gene_ontology")
BOLT_URL = "bolt://localhost:7688"

GO_OBO_URL = "http://purl.obolibrary.org/obo/go.obo"
GOA_HUMAN_URL = "https://current.geneontology.org/annotations/goa_human.gaf.gz"

NS_TO_LABEL = {
    "biological_process": "BiologicalProcess",
    "molecular_function": "MolecularFunction",
    "cellular_component": "CellularComponent",
}
NS_TO_REL = {
    "biological_process": "geneParticipatesInBiologicalProcess",
    "molecular_function": "geneHasMolecularFunction",
    "cellular_component": "geneAssociatedWithCellularComponent",
}

def download():
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    for url, name in [(GO_OBO_URL, "go.obo"), (GOA_HUMAN_URL, "goa_human.gaf.gz")]:
        out = RAW_DIR / name
        if out.exists():
            print(f"[skip] {out} exists")
            continue
        print(f"[download] {url} -> {out}")
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req) as r, open(out, 'wb') as o:
            o.write(r.read())

def parse_obo(path):
    terms = []
    cur = None
    with open(path) as f:
        for line in f:
            line = line.rstrip("\n")
            if line == "[Term]":
                if cur: terms.append(cur)
                cur = {}
            elif line.startswith("[") and cur is not None:
                terms.append(cur); cur = None
            elif cur is not None and ":" in line:
                k, _, v = line.partition(": ")
                if k == "id" and v.startswith("GO:"):
                    cur["id"] = v
                elif k == "name":
                    cur["name"] = v
                elif k == "namespace":
                    cur["namespace"] = v
                elif k == "def":
                    # def: "..." [refs]
                    if v.startswith('"'):
                        end = v.rfind('"')
                        cur["definition"] = v[1:end] if end > 0 else v
                elif k == "is_obsolete" and v == "true":
                    cur["obsolete"] = True
    if cur: terms.append(cur)
    return [t for t in terms if "id" in t and not t.get("obsolete")]

def parse():
    PROC_DIR.mkdir(parents=True, exist_ok=True)
    obo = RAW_DIR / "go.obo"
    gaf = RAW_DIR / "goa_human.gaf.gz"
    
    # Parse GO terms
    terms = parse_obo(obo)
    print(f"[parse] {len(terms)} GO terms")
    out_terms = PROC_DIR / "go_terms.tsv"
    with open(out_terms, "w", newline="") as f:
        w = csv.writer(f, delimiter="\t")
        w.writerow(["geneOntologyId","name","namespace","definition"])
        for t in terms:
            w.writerow([t.get("id",""), t.get("name",""), t.get("namespace",""), t.get("definition","")])
    print(f"[parse] wrote {out_terms}")
    
    # Parse annotations
    annots = []
    opener = gzip.open if str(gaf).endswith(".gz") else open
    with opener(gaf, "rt") as f:
        for line in f:
            if line.startswith("!"): continue
            cols = line.rstrip("\n").split("\t")
            if len(cols) < 9: continue
            gene_symbol = cols[2]
            go_id = cols[4]
            qualifier = cols[3]
            evidence = cols[6]
            if "NOT" in qualifier: continue
            annots.append((gene_symbol, go_id, evidence))
    print(f"[parse] {len(annots)} annotations")
    out_a = PROC_DIR / "go_annotations.tsv"
    with open(out_a, "w", newline="") as f:
        w = csv.writer(f, delimiter="\t")
        w.writerow(["geneSymbol","geneOntologyId","evidence"])
        for r in annots:
            w.writerow(r)
    print(f"[parse] wrote {out_a}")

def load():
    driver = GraphDatabase.driver(BOLT_URL, auth=None)
    with driver.session() as session:
        # Indexes/constraints (idempotent)
        for lbl in NS_TO_LABEL.values():
            session.run(f"CREATE INDEX ON :{lbl}(geneOntologyId)")
        # Load terms grouped by namespace
        terms_file = PROC_DIR / "go_terms.tsv"
        by_ns = {ns: [] for ns in NS_TO_LABEL}
        with open(terms_file) as f:
            r = csv.DictReader(f, delimiter="\t")
            for row in r:
                ns = row["namespace"]
                if ns in by_ns: by_ns[ns].append(row)
        for ns, rows in by_ns.items():
            lbl = NS_TO_LABEL[ns]
            print(f"[load] {len(rows)} {lbl} nodes")
            BATCH = 1000
            for i in range(0, len(rows), BATCH):
                batch = rows[i:i+BATCH]
                session.run(
                    f"UNWIND $rows AS row "
                    f"MERGE (n:{lbl} {{geneOntologyId: row.geneOntologyId}}) "
                    f"SET n.name = row.name, n.namespace = row.namespace, n.definition = row.definition",
                    rows=batch
                )
        # Load annotations
        ann_file = PROC_DIR / "go_annotations.tsv"
        # Need namespace info from terms file
        ns_map = {}
        with open(terms_file) as f:
            r = csv.DictReader(f, delimiter="\t")
            for row in r:
                ns_map[row["geneOntologyId"]] = row["namespace"]
        # Bucket annotations by ns
        edges_ns = {ns: [] for ns in NS_TO_LABEL}
        with open(ann_file) as f:
            r = csv.DictReader(f, delimiter="\t")
            for row in r:
                ns = ns_map.get(row["geneOntologyId"])
                if ns in edges_ns:
                    edges_ns[ns].append({"gene":row["geneSymbol"],"go":row["geneOntologyId"]})
        for ns, edges in edges_ns.items():
            lbl = NS_TO_LABEL[ns]; rel = NS_TO_REL[ns]
            print(f"[load] {len(edges)} {rel} edges")
            BATCH = 2000
            for i in range(0, len(edges), BATCH):
                batch = edges[i:i+BATCH]
                session.run(
                    f"UNWIND $rows AS row "
                    f"MATCH (g:Gene {{geneSymbol: row.gene}}) "
                    f"MATCH (t:{lbl} {{geneOntologyId: row.go}}) "
                    f"MERGE (g)-[r:{rel}]->(t) "
                    f"ON CREATE SET r.source = 'Gene Ontology' "
                    f"ON MATCH SET r.source = coalesce(r.source,'Gene Ontology')",
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
