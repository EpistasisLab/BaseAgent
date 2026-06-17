#!/usr/bin/env python3
"""Load Reactome Pathway nodes and Gene<->Pathway relationships into Memgraph."""

import csv
from neo4j import GraphDatabase

BOLT   = "bolt://localhost:7688"
driver = GraphDatabase.driver(BOLT, auth=None)

PATHWAYS_PATH = "./data/processed/reactome/reactome_pathways.tsv"
GP_PATH       = "./data/processed/reactome/reactome_gene_pathway.tsv"

# Read data
pathways = []
with open(PATHWAYS_PATH, encoding='utf-8') as f:
    reader = csv.DictReader(f, delimiter='\t')
    for row in reader:
        pathways.append(row)

edges = []
with open(GP_PATH, encoding='utf-8') as f:
    reader = csv.DictReader(f, delimiter='\t')
    for row in reader:
        edges.append(row)

print(f"Pathways to load:    {len(pathways)}")
print(f"Gene-pathway edges:  {len(edges)}")

BATCH = 500

with driver.session() as session:
    # 1. MERGE Pathway nodes
    print("\nLoading Pathway nodes ...")
    for i in range(0, len(pathways), BATCH):
        batch = pathways[i:i+BATCH]
        session.run("""
            UNWIND $rows AS row
            MERGE (p:Pathway {pathwayId: row.pathwayId})
              ON CREATE SET p.pathwayName = row.pathwayName,
                            p.source = 'Reactome'
        """, rows=[{'pathwayId': r['pathwayId'], 'pathwayName': r['pathwayName']}
                   for r in batch])

    cnt = session.run("MATCH (n:Pathway) RETURN count(n) as c").single()['c']
    print(f"  Pathway nodes: {cnt}")

    # 2. MERGE geneInPathway (Gene -> Pathway)
    print("Loading geneInPathway relationships ...")
    for i in range(0, len(edges), BATCH):
        batch = edges[i:i+BATCH]
        session.run("""
            UNWIND $rows AS row
            MATCH (g:Gene    {geneSymbol: row.gene})
            MATCH (p:Pathway {pathwayId:  row.pathwayId})
            MERGE (g)-[r:geneInPathway]->(p)
              ON CREATE SET r.source = 'Reactome'
        """, rows=[{'gene': r['geneSymbol'], 'pathwayId': r['pathwayId']}
                   for r in batch])

    cnt = session.run("MATCH ()-[r:geneInPathway]->() RETURN count(r) as c").single()['c']
    print(f"  geneInPathway edges: {cnt}")

    # 3. MERGE pathwayContainsGene (Pathway -> Gene)
    print("Loading pathwayContainsGene relationships ...")
    for i in range(0, len(edges), BATCH):
        batch = edges[i:i+BATCH]
        session.run("""
            UNWIND $rows AS row
            MATCH (p:Pathway {pathwayId:  row.pathwayId})
            MATCH (g:Gene    {geneSymbol: row.gene})
            MERGE (p)-[r:pathwayContainsGene]->(g)
              ON CREATE SET r.source = 'Reactome'
        """, rows=[{'gene': r['geneSymbol'], 'pathwayId': r['pathwayId']}
                   for r in batch])

    cnt = session.run("MATCH ()-[r:pathwayContainsGene]->() RETURN count(r) as c").single()['c']
    print(f"  pathwayContainsGene edges: {cnt}")

driver.close()
print("\nReactome loading complete.")
