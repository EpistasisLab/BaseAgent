#!/usr/bin/env python3
"""Load Uberon BodyPart nodes into Memgraph."""

import csv
from neo4j import GraphDatabase

BOLT   = "bolt://localhost:7688"
driver = GraphDatabase.driver(BOLT, auth=None)

UBERON_PATH = "./data/processed/uberon/uberon_terms.tsv"

terms = []
with open(UBERON_PATH, encoding='utf-8') as f:
    reader = csv.DictReader(f, delimiter='\t')
    for row in reader:
        terms.append(row)

print(f"Uberon terms to load: {len(terms)}")

BATCH = 500

with driver.session() as session:
    print("\nLoading BodyPart nodes ...")
    for i in range(0, len(terms), BATCH):
        batch = terms[i:i+BATCH]
        session.run("""
            UNWIND $rows AS row
            MERGE (b:BodyPart {xrefUberon: row.xrefUberon})
              ON CREATE SET b.name       = row.name,
                            b.definition = row.definition,
                            b.source     = 'Uberon'
        """, rows=[{'xrefUberon': r['xrefUberon'],
                    'name':       r['name'],
                    'definition': r['definition']} for r in batch])

    cnt = session.run("MATCH (n:BodyPart) RETURN count(n) as c").single()['c']
    print(f"  BodyPart nodes: {cnt}")

driver.close()
print("\nUberon loading complete.")
