"""MeSH Symptoms Parser for CardioKB - uses Hetionet DpS edges"""
import csv, os
from neo4j import GraphDatabase

NEO4J_URI = "bolt://localhost:7688"
HETIONET_SIF = "./data/processed/medline/hetionet-v1.0-edges.sif"
OUT_DIR = "./data/processed/mesh"
os.makedirs(OUT_DIR, exist_ok=True)

def parse_dps_edges(sif_file):
    edges = []
    with open(sif_file) as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            if row["metaedge"] == "DpS":
                doid = row["source"].replace("Disease::", "")
                mesh = row["target"].replace("Symptom::", "")
                edges.append({"doid": doid, "mesh": mesh})
    return edges

def load_into_graph(edges):
    driver = GraphDatabase.driver(NEO4J_URI, auth=None)
    with driver.session() as session:
        # Build symptom lookup
        result = session.run("MATCH (s:Symptom) RETURN s.xrefMeSH AS mesh")
        mesh_lookup = {}
        for row in result:
            m = row["mesh"]
            if m:
                dcode = m.split("/")[-1] if "/" in m else m
                mesh_lookup[dcode] = m
        # Build disease lookup
        result = session.run("MATCH (d:Disease) RETURN d.xrefDiseaseOntology AS doid")
        doid_set = {row["doid"] for row in result if row["doid"]}
        # Filter and load
        load_rows = [{"doid": e["doid"], "mesh": mesh_lookup[e["mesh"]]}
                     for e in edges if e["doid"] in doid_set and e["mesh"] in mesh_lookup]
        result = session.run("""
            UNWIND $rows AS row
            MATCH (d:Disease {xrefDiseaseOntology: row.doid})
            MATCH (s:Symptom {xrefMeSH: row.mesh})
            MERGE (d)-[r:diseasePresentsSymptom {source:"MEDLINE"}]->(s)
            RETURN count(r) AS cnt
        """, rows=load_rows)
        print(f"diseasePresentsSymptom edges: {result.single()['cnt']}")
    driver.close()

if __name__ == "__main__":
    edges = parse_dps_edges(HETIONET_SIF)
    print(f"DpS edges parsed: {len(edges)}")
    load_into_graph(edges)
