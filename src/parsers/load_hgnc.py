#!/usr/bin/env python3
"""Load HGNC GeneFamily nodes and Gene<->GeneFamily relationships into Memgraph."""

import csv
from neo4j import GraphDatabase

BOLT   = "bolt://localhost:7688"
driver = GraphDatabase.driver(BOLT, auth=None)

FAM_PATH   = "./data/processed/hgnc/hgnc_families_cvd.tsv"
EDGES_PATH = "./data/processed/hgnc/hgnc_gene_family_cvd.tsv"

families = []
with open(FAM_PATH, encoding='utf-8') as f:
    reader = csv.DictReader(f, delimiter='\t')
    for row in reader:
        families.append(row)

edges = []
with open(EDGES_PATH, encoding='utf-8') as f:
    reader = csv.DictReader(f, delimiter='\t')
    for row in reader:
        edges.append(row)

print(f"Gene families to load:  {len(families)}")
print(f"Gene-family edges:      {len(edges)}")

BATCH = 500

with driver.session() as session:
    # 1. MERGE GeneFamily nodes
    print("\nLoading GeneFamily nodes ...")
    for i in range(0, len(families), BATCH):
        batch = families[i:i+BATCH]
        session.run("""
            UNWIND $rows AS row
            MERGE (f:GeneFamily {familyId: row.familyId})
              ON CREATE SET f.familyName = row.familyName,
                            f.source = 'HGNC'
        """, rows=[{'familyId': r['familyId'], 'familyName': r['familyName']}
                   for r in batch])

    cnt = session.run("MATCH (n:GeneFamily) RETURN count(n) as c").single()['c']
    print(f"  GeneFamily nodes: {cnt}")

    # 2. MERGE geneInFamily (Gene -> GeneFamily)
    print("Loading geneInFamily relationships ...")
    for i in range(0, len(edges), BATCH):
        batch = edges[i:i+BATCH]
        session.run("""
            UNWIND $rows AS row
            MATCH (g:Gene       {geneSymbol: row.gene})
            MATCH (f:GeneFamily {familyId:   row.familyId})
            MERGE (g)-[r:geneInFamily]->(f)
              ON CREATE SET r.source = 'HGNC Families'
        """, rows=[{'gene': r['geneSymbol'], 'familyId': r['familyId']}
                   for r in batch])

    cnt = session.run("MATCH ()-[r:geneInFamily]->() RETURN count(r) as c").single()['c']
    print(f"  geneInFamily edges: {cnt}")

    # 3. MERGE familyContainsGene (GeneFamily -> Gene)
    print("Loading familyContainsGene relationships ...")
    for i in range(0, len(edges), BATCH):
        batch = edges[i:i+BATCH]
        session.run("""
            UNWIND $rows AS row
            MATCH (f:GeneFamily {familyId:   row.familyId})
            MATCH (g:Gene       {geneSymbol: row.gene})
            MERGE (f)-[r:familyContainsGene]->(g)
              ON CREATE SET r.source = 'HGNC Families'
        """, rows=[{'gene': r['geneSymbol'], 'familyId': r['familyId']}
                   for r in batch])

    cnt = session.run("MATCH ()-[r:familyContainsGene]->() RETURN count(r) as c").single()['c']
    print(f"  familyContainsGene edges: {cnt}")

driver.close()
print("\nHGNC loading complete.")
