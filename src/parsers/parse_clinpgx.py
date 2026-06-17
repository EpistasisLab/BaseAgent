"""ClinPGx (CPIC) Parser for CardioKB"""
import requests, csv, time, os, json
from neo4j import GraphDatabase

NEO4J_URI = "bolt://localhost:7688"
OUT_DIR = "./data/processed/clinpgx"
CPIC_BASE = "https://api.cpicpgx.org/v1"
os.makedirs(OUT_DIR, exist_ok=True)

def fetch_all(endpoint, limit=500):
    results, offset = [], 0
    while True:
        r = requests.get(f"{CPIC_BASE}{endpoint}", params={"limit": limit, "offset": offset}, timeout=30)
        data = r.json()
        if not data or not isinstance(data, list): break
        results.extend(data)
        if len(data) < limit: break
        offset += limit
        time.sleep(0.2)
    return results

if __name__ == "__main__":
    print("Fetching CPIC data...")
    cpic_drugs    = fetch_all("/drug")
    cpic_genes    = fetch_all("/gene")
    cpic_pairs    = fetch_all("/pair")
    cpic_guidelines = fetch_all("/guideline")
    print(f"drugs={len(cpic_drugs)}, genes={len(cpic_genes)}, pairs={len(cpic_pairs)}, guidelines={len(cpic_guidelines)}")
    print("See main notebook for full loading logic.")
