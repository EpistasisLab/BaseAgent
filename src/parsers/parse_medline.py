"""
MEDLINE Cooccurrence + Hetionet Parser for CardioKB
Loads: DpS, DlA, DrD, DaG, CtD edges + missing Disease nodes
"""
import csv, os, requests
from neo4j import GraphDatabase

NEO4J_URI    = "bolt://localhost:7688"
HETIONET_SIF = "./data/processed/medline/hetionet-v1.0-edges.sif"
OUT_DIR      = "./data/processed/medline"
os.makedirs(OUT_DIR, exist_ok=True)

HETIONET_NODES_URL = "https://github.com/hetio/hetionet/raw/main/hetnet/tsv/hetionet-v1.0-nodes.tsv"

def parse_all_edges(sif_file):
    edges = {"DpS":[], "DlA":[], "DrD":[], "DaG":[], "CtD":[]}
    with open(sif_file) as f:
        for row in csv.DictReader(f, delimiter="\t"):
            e = row["metaedge"]
            if e in edges:
                edges[e].append({"source": row["source"], "target": row["target"]})
    return edges

def load_disease_nodes(driver, nodes_url):
    r = requests.get(nodes_url, timeout=30)
    disease_map = {}
    for line in r.text.strip().split("\n")[1:]:
        parts = line.strip().split("\t")
        if len(parts) >= 3 and parts[2].strip() == "Disease":
            doid = parts[0].strip().replace("Disease::", "")
            disease_map[doid] = parts[1].strip()
    with driver.session() as session:
        rows = [{"xrefDiseaseOntology": k, "diseaseName": v, "source": "Hetionet"}
                for k, v in disease_map.items()]
        session.run("""
            UNWIND $rows AS row
            MERGE (d:Disease {xrefDiseaseOntology: row.xrefDiseaseOntology})
            ON CREATE SET d.diseaseName = row.diseaseName, d.source = row.source
        """, rows=rows)
    print(f"Disease nodes ensured: {len(disease_map)}")

if __name__ == "__main__":
    driver = GraphDatabase.driver(NEO4J_URI, auth=None)
    print("Loading Hetionet disease nodes...")
    load_disease_nodes(driver, HETIONET_NODES_URL)
    print("Parsing edge file...")
    edges = parse_all_edges(HETIONET_SIF)
    for etype, count in {k: len(v) for k, v in edges.items()}.items():
        print(f"  {etype}: {count}")
    print("See main notebook for full loading logic.")
    driver.close()
