"""
MEDLINE cooccurrence parser for CardioKB (via Hetionet bundle)
- diseaseResemblesDisease   (Disease)-[:diseaseResemblesDisease]->(Disease)
- diseaseLocalizesToAnatomy (Disease)-[:diseaseLocalizesToAnatomy]->(BodyPart) by xrefUberon
Supports: --download --parse --load --all
"""
import argparse, csv, os, zipfile, requests
from neo4j import GraphDatabase

NEO4J_URI = "bolt://localhost:7688"
OUT_DIR = "./data/processed/medline"
os.makedirs(OUT_DIR, exist_ok=True)

HETIONET_SIF = os.path.join(OUT_DIR, "hetionet-v1.0-edges.sif")
DRD_TSV = os.path.join(OUT_DIR, "disease_disease_edges.tsv")
DLA_TSV = os.path.join(OUT_DIR, "disease_anatomy_edges.tsv")
HETIONET_EDGE_URL = "https://github.com/hetio/hetionet/raw/main/hetnet/tsv/hetionet-v1.0-edges.sif.gz"


def download():
    print("[medline] download")
    if os.path.exists(HETIONET_SIF):
        print(f"  exists: {HETIONET_SIF}"); return
    import gzip, io
    r = requests.get(HETIONET_EDGE_URL, timeout=120); r.raise_for_status()
    data = gzip.decompress(r.content)
    with open(HETIONET_SIF, "wb") as f: f.write(data)
    print(f"  wrote {HETIONET_SIF}")


def parse():
    print("[medline] parse")
    if not os.path.exists(HETIONET_SIF):
        print("  missing hetionet SIF - run --download"); return
    drd, dla = [], []
    with open(HETIONET_SIF) as f:
        for r in csv.DictReader(f, delimiter="\t"):
            e = r["metaedge"]
            if e == "DrD":
                drd.append((r["source"].replace("Disease::",""),
                            r["target"].replace("Disease::","")))
            elif e == "DlA":
                dla.append((r["source"].replace("Disease::",""),
                            r["target"].replace("Anatomy::","")))
    with open(DRD_TSV,"w",newline="") as f:
        w = csv.writer(f, delimiter="\t"); w.writerow(["doid1","doid2"])
        for a,b in drd: w.writerow([a,b])
    with open(DLA_TSV,"w",newline="") as f:
        w = csv.writer(f, delimiter="\t"); w.writerow(["doid","uberon"])
        for d,u in dla: w.writerow([d,u])
    print(f"  DrD: {len(drd)}   DlA: {len(dla)}")


def load():
    print("[medline] load")
    drv = GraphDatabase.driver(NEO4J_URI, auth=None)
    with drv.session() as s:
        # diseaseResemblesDisease
        drd_rows = []
        if os.path.exists(DRD_TSV):
            with open(DRD_TSV) as f:
                for r in csv.DictReader(f, delimiter="\t"):
                    if r.get("doid1") and r.get("doid2"):
                        drd_rows.append(r)
        before = s.run("MATCH ()-[r:diseaseResemblesDisease]->() RETURN count(r) AS c").single()["c"]
        s.run("""
            UNWIND $rows AS r
            MATCH (a:Disease {xrefDiseaseOntology: r.doid1})
            MATCH (b:Disease {xrefDiseaseOntology: r.doid2})
            MERGE (a)-[e:diseaseResemblesDisease]->(b)
            ON CREATE SET e.source='MEDLINE'
            ON MATCH  SET e.source=coalesce(e.source,'MEDLINE')
        """, rows=drd_rows)
        after = s.run("MATCH ()-[r:diseaseResemblesDisease]->() RETURN count(r) AS c").single()["c"]
        print(f"  diseaseResemblesDisease: {before} -> {after}  (+{after-before})  rows={len(drd_rows)}")

        # diseaseLocalizesToAnatomy
        dla_rows = []
        if os.path.exists(DLA_TSV):
            with open(DLA_TSV) as f:
                for r in csv.DictReader(f, delimiter="\t"):
                    if r.get("doid") and r.get("uberon"):
                        dla_rows.append(r)
        before = s.run("MATCH ()-[r:diseaseLocalizesToAnatomy]->() RETURN count(r) AS c").single()["c"]
        s.run("""
            UNWIND $rows AS r
            MATCH (d:Disease {xrefDiseaseOntology: r.doid})
            MATCH (b:BodyPart {xrefUberon: r.uberon})
            MERGE (d)-[e:diseaseLocalizesToAnatomy]->(b)
            ON CREATE SET e.source='MEDLINE'
            ON MATCH  SET e.source=coalesce(e.source,'MEDLINE')
        """, rows=dla_rows)
        after = s.run("MATCH ()-[r:diseaseLocalizesToAnatomy]->() RETURN count(r) AS c").single()["c"]
        print(f"  diseaseLocalizesToAnatomy: {before} -> {after}  (+{after-before})  rows={len(dla_rows)}")
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
