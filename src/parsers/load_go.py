#!/usr/bin/env python3
"""Load GO nodes and relationships into Memgraph."""

import csv
from neo4j import GraphDatabase

BOLT = "bolt://localhost:7688"
driver = GraphDatabase.driver(BOLT, auth=None)

ANN_PATH   = "./data/processed/go/go_annotations.tsv"

# ── Read annotations ────────────────────────────────────────────────────────
annotations = []
with open(ANN_PATH, encoding='utf-8') as f:
    reader = csv.DictReader(f, delimiter='\t')
    for row in reader:
        annotations.append(row)

print(f"Annotations to load: {len(annotations)}")

# Split by namespace
bp  = [a for a in annotations if a['namespace'] == 'biological_process']
mf  = [a for a in annotations if a['namespace'] == 'molecular_function']
cc  = [a for a in annotations if a['namespace'] == 'cellular_component']
print(f"  BiologicalProcess: {len(bp)}")
print(f"  MolecularFunction: {len(mf)}")
print(f"  CellularComponent: {len(cc)}")

BATCH = 500

def load_go_nodes_and_rels(session, rows, label, rel_type):
    """MERGE GO nodes and Gene->GO relationships in batches."""
    for i in range(0, len(rows), BATCH):
        batch = rows[i:i+BATCH]
        session.run(f"""
            UNWIND $rows AS row
            MERGE (go:{label} {{geneOntologyId: row.go_id}})
              ON CREATE SET go.name = row.name, go.namespace = row.namespace
            WITH go, row
            MATCH (g:Gene {{geneSymbol: row.gene}})
            MERGE (g)-[r:{rel_type}]->(go)
              ON CREATE SET r.source = 'Gene Ontology', r.evidence = row.evidence
        """, rows=[{'go_id': r['geneOntologyId'], 'name': r['name'],
                    'namespace': r['namespace'], 'gene': r['geneSymbol'],
                    'evidence': r['evidence']} for r in batch])

with driver.session() as session:
    print("\nLoading BiologicalProcess nodes + geneParticipatesInBiologicalProcess ...")
    load_go_nodes_and_rels(session, bp, 'BiologicalProcess', 'geneParticipatesInBiologicalProcess')
    cnt = session.run("MATCH (n:BiologicalProcess) RETURN count(n) as c").single()['c']
    print(f"  BiologicalProcess nodes: {cnt}")

    print("Loading MolecularFunction nodes + geneHasMolecularFunction ...")
    load_go_nodes_and_rels(session, mf, 'MolecularFunction', 'geneHasMolecularFunction')
    cnt = session.run("MATCH (n:MolecularFunction) RETURN count(n) as c").single()['c']
    print(f"  MolecularFunction nodes: {cnt}")

    print("Loading CellularComponent nodes + geneAssociatedWithCellularComponent ...")
    load_go_nodes_and_rels(session, cc, 'CellularComponent', 'geneAssociatedWithCellularComponent')
    cnt = session.run("MATCH (n:CellularComponent) RETURN count(n) as c").single()['c']
    print(f"  CellularComponent nodes: {cnt}")

    # Relationship counts
    for rel in ['geneParticipatesInBiologicalProcess', 'geneHasMolecularFunction',
                'geneAssociatedWithCellularComponent']:
        cnt = session.run(f"MATCH ()-[r:{rel}]->() RETURN count(r) as c").single()['c']
        print(f"  {rel}: {cnt}")

driver.close()
print("\nGO loading complete.")
