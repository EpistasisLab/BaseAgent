"""
MeSH symptoms parser for CardioKB
- Loads Symptom nodes (xrefMeSH = MeSH descriptor like "2026/D012345")
- diseasePresentsSymptom edges from Hetionet (MEDLINE-derived) DpS edges
Supports: --download --parse --load --all
"""
import argparse, csv, os, requests
from neo4j import GraphDatabase

NEO4J_URI = "bolt://localhost:7688"
OUT_DIR = "./data/processed/mesh"
os.makedirs(OUT_DIR, exist_ok=True)

SYMPTOMS_TSV = os.path.join(OUT_DIR, "symptoms.tsv")
DPS_TSV      = os.path.join(OUT_DIR, "disease_symptom_edges.tsv")
HETIONET_SIF = "./data/processed/medline/hetionet-v1.0-edges.sif"
HETIONET_NODES_URL = "https://github.com/hetio/hetionet/raw/main/hetnet/tsv/hetionet-v1.0-nodes.tsv"


def download():
    print("[mesh] download")
    # Symptom nodes come from Hetionet nodes file (Symptom rows -> xrefMeSH)
    try:
        r = requests.get(HETIONET_NODES_URL, timeout=60); r.raise_for_status()
    except Exception as e:
        print(f"  fetch failed: {e}"); return
    sym_rows = []
    for line in r.text.strip().splitlines()[1:]:
        parts = line.split("\t")
        if len(parts) >= 3 and parts[2].strip() == "Symptom":
            mesh = parts[0].replace("Symptom::", "").strip()
            sym_rows.append({"xrefMeSH": mesh, "name": parts[1].strip()})
    if sym_rows and not os.path.exists(SYMPTOMS_TSV):
        with open(SYMPTOMS_TSV,"w",newline="") as f:
            w = csv.DictWriter(f, fieldnames=["xrefMeSH","name"], delimiter="\t")
            w.writeheader(); w.writerows(sym_rows)
    print(f"  symptom rows present: {len(sym_rows)}  file={SYMPTOMS_TSV}")


def parse():
    print("[mesh] parse")
    if not os.path.exists(HETIONET_SIF):
        print(f"  missing {HETIONET_SIF}"); return
    edges = []
    with open(HETIONET_SIF) as f:
        for r in csv.DictReader(f, delimiter="\t"):
            if r["metaedge"] == "DpS":
                doid = r["source"].replace("Disease::","")
                mesh = r["target"].replace("Symptom::","")
                edges.append((doid, mesh))
    with open(DPS_TSV,"w",newline="") as f:
        w = csv.writer(f, delimiter="\t"); w.writerow(["doid","mesh"])
        for d,m in edges: w.writerow([d,m])
    print(f"  DpS edges parsed: {len(edges)}  -> {DPS_TSV}")


def load():
    print("[mesh] load")
    drv = GraphDatabase.driver(NEO4J_URI, auth=None)
    with drv.session() as s:
        # Symptom nodes
        rows = []
        if os.path.exists(SYMPTOMS_TSV):
            with open(SYMPTOMS_TSV) as f:
                for r in csv.DictReader(f, delimiter="\t"):
                    if r.get("xrefMeSH"):
                        rows.append(r)
        before = s.run("MATCH (n:Symptom) RETURN count(n) AS c").single()["c"]
        s.run("""
            UNWIND $rows AS r
            MERGE (sm:Symptom {xrefMeSH: r.xrefMeSH})
            ON CREATE SET sm.name=r.name, sm.source='MeSH'
        """, rows=rows)
        after = s.run("MATCH (n:Symptom) RETURN count(n) AS c").single()["c"]
        print(f"  Symptom: {before} -> {after}  (+{after-before})")

        # diseasePresentsSymptom edges
        edges = []
        if os.path.exists(DPS_TSV):
            with open(DPS_TSV) as f:
                for r in csv.DictReader(f, delimiter="\t"):
                    if r.get("doid") and r.get("mesh"):
                        edges.append(r)
        before_e = s.run("MATCH ()-[r:diseasePresentsSymptom]->() RETURN count(r) AS c").single()["c"]
        s.run("""
            UNWIND $rows AS r
            MATCH (d:Disease {xrefDiseaseOntology: r.doid})
            MATCH (sm:Symptom {xrefMeSH: r.mesh})
            MERGE (d)-[e:diseasePresentsSymptom]->(sm)
            ON CREATE SET e.source='MEDLINE'
            ON MATCH  SET e.source=coalesce(e.source,'MEDLINE')
        """, rows=edges)
        after_e = s.run("MATCH ()-[r:diseasePresentsSymptom]->() RETURN count(r) AS c").single()["c"]
        print(f"  diseasePresentsSymptom: {before_e} -> {after_e}  (+{after_e-before_e})  rows={len(edges)}")
    drv.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--download", action="store_true")
    ap.add_argument("--parse",    action="store_true")
    ap.add_argument("--load",     action="store_true")
    ap.add_argument("--all",      action="store_true")
    a = ap.parse_args()
    if a.all or a.download: download()
    if a.all or a.parse:    parse()
    if a.all or a.load:     load()
    if not any([a.all,a.download,a.parse,a.load]):
        print("usage: --download | --parse | --load | --all")
