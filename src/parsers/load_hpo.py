#!/usr/bin/env python3
"""Load HPO Phenotype nodes and Gene->Phenotype relationships into Memgraph."""

import csv
from neo4j import GraphDatabase

BOLT   = "bolt://localhost:7688"
driver = GraphDatabase.driver(BOLT, auth=None)

PHENO_PATH = "./data/processed/hpo/hpo_phenotypes.tsv"
GP_PATH    = "./data/processed/hpo/hpo_gene_phenotype.tsv"

phenotypes = []
with open(PHENO_PATH, encoding='utf-8') as f:
    reader = csv.DictReader(f, delimiter='\t')
    for row in reader:
        phenotypes.append(row)

edges = []
with open(GP_PATH, encoding='utf-8') as f:
    reader = csv.DictReader(f, delimiter='\t')
    for row in reader:
        edges.append(row)

print(f"Phenotypes to load:        {len(phenotypes)}")
print(f"Gene-phenotype edges:      {len(edges)}")

BATCH = 500

with driver.session() as session:
    # 1. MERGE Phenotype nodes
    print("\nLoading Phenotype nodes ...")
    for i in range(0, len(phenotypes), BATCH):
        batch = phenotypes[i:i+BATCH]
        session.run("""
            UNWIND $rows AS row
            MERGE (p:Phenotype {xrefHPO: row.xrefHPO})
              ON CREATE SET p.name = row.name
        """, rows=[{'xrefHPO': r['xrefHPO'], 'name': r['name']} for r in batch])

    cnt = session.run("MATCH (n:Phenotype) RETURN count(n) as c").single()['c']
    print(f"  Phenotype nodes: {cnt}")

    # 2. MERGE geneAssociatesWithPhenotype (Gene -> Phenotype)
    print("Loading geneAssociatesWithPhenotype relationships ...")
    for i in range(0, len(edges), BATCH):
        batch = edges[i:i+BATCH]
        session.run("""
            UNWIND $rows AS row
            MATCH (g:Gene     {geneSymbol: row.gene})
            MATCH (p:Phenotype {xrefHPO:   row.xrefHPO})
            MERGE (g)-[r:geneAssociatesWithPhenotype]->(p)
              ON CREATE SET r.source = 'HPO'
        """, rows=[{'gene': r['geneSymbol'], 'xrefHPO': r['xrefHPO']} for r in batch])

    cnt = session.run("MATCH ()-[r:geneAssociatesWithPhenotype]->() RETURN count(r) as c").single()['c']
    print(f"  geneAssociatesWithPhenotype edges: {cnt}")

driver.close()
print("\nHPO loading complete.")
