"""
CardioKB Foundation Node Loader
Loads Gene, Disease, and Drug nodes into Memgraph
Usage: python load_foundation_nodes.py
"""
import pandas as pd
from neo4j import GraphDatabase
import time
import sys

URI  = "bolt://localhost:7688"
AUTH = None

GENE_QUERY = """
MERGE (g:Gene {geneSymbol: $geneSymbol})
SET g.ncbiGeneId = $ncbiGeneId,
    g.geneName   = $geneName,
    g.chromosome = $chromosome,
    g.geneType   = $geneType,
    g.synonyms   = $synonyms,
    g.organism   = $organism,
    g.taxonId    = $taxonId,
    g.source     = 'NCBI Gene'
"""

DISEASE_QUERY = """
MERGE (d:Disease {xrefDiseaseOntology: $doid})
SET d.diseaseName = $name,
    d.definition  = $definition,
    d.synonyms    = $synonyms,
    d.source      = 'Disease Ontology'
"""

DRUG_QUERY = """
MERGE (dr:Drug {commonName: $commonName})
SET dr.drugBankId = $drugBankId,
    dr.casNumber  = $casNumber,
    dr.meshId     = $meshId,
    dr.drugGroups = $drugGroups,
    dr.source     = 'DrugCentral+CTD'
"""

def load_nodes(session, query, records, label, key_field):
    loaded, errors = 0, 0
    for rec in records:
        try:
            session.run(query, **rec)
            loaded += 1
        except Exception as e:
            errors += 1
            if errors <= 3:
                print(f"  [WARN] {label} error: {e}")
    return loaded, errors

def main():
    driver = GraphDatabase.driver(URI, auth=AUTH)
    print(f"Connected to Memgraph at {URI}")
    
    with driver.session() as session:
        # ── Genes ──────────────────────────────────────────────────
        print("\n--- Loading Gene nodes ---")
        df = pd.read_csv("./data/processed/ncbi_gene/cvd_genes_final.tsv",
                         sep="\t", dtype=str).fillna("")
        records = [
            dict(geneSymbol=r["geneSymbol"], ncbiGeneId=r["ncbiGeneId"],
                 geneName=r["geneName"], chromosome=r["chromosome"],
                 geneType=r["geneType"], synonyms=r["synonyms"],
                 organism=r.get("organism","Homo sapiens"),
                 taxonId=r.get("taxonId","9606"))
            for _, r in df.iterrows()
        ]
        n, e = load_nodes(session, GENE_QUERY, records, "Gene", "geneSymbol")
        print(f"  Loaded {n} Gene nodes ({e} errors)")

        # ── Diseases ───────────────────────────────────────────────
        print("\n--- Loading Disease nodes ---")
        df = pd.read_csv("./data/processed/disease_ontology/cvd_diseases_final.tsv",
                         sep="\t", dtype=str).fillna("")
        records = [
            dict(doid=r["xrefDiseaseOntology"], name=r["diseaseName"],
                 definition=r["definition"], synonyms=r["synonyms"])
            for _, r in df.iterrows()
        ]
        n, e = load_nodes(session, DISEASE_QUERY, records, "Disease", "xrefDiseaseOntology")
        print(f"  Loaded {n} Disease nodes ({e} errors)")

        # ── Drugs ──────────────────────────────────────────────────
        print("\n--- Loading Drug nodes ---")
        df = pd.read_csv("./data/processed/drugcentral/cvd_drugs_final.tsv",
                         sep="\t", dtype=str).fillna("")
        records = [
            dict(commonName=r["commonName"], drugBankId=r["drugBankId"],
                 casNumber=r["casNumber"], meshId=r["meshId"],
                 drugGroups=r["drugGroups"])
            for _, r in df.iterrows()
            if str(r["commonName"]).strip()
        ]
        n, e = load_nodes(session, DRUG_QUERY, records, "Drug", "commonName")
        print(f"  Loaded {n} Drug nodes ({e} errors)")

        # ── Final counts ───────────────────────────────────────────
        print("\n--- Final node counts ---")
        result = session.run(
            "MATCH (n) RETURN labels(n)[0] AS label, count(n) AS cnt ORDER BY cnt DESC")
        for r in result:
            print(f"  {r['label']}: {r['cnt']:,}")

    driver.close()
    print("\nDone.")

if __name__ == "__main__":
    main()
