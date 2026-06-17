#!/usr/bin/env python3
"""
Disease Association Loader for CardioKB Knowledge Graph
Loads: OpenTargets, DrugCentral, PubTator, SIDER
Target: bolt://localhost:7688 (Memgraph, no auth)
"""
from neo4j import GraphDatabase
import pandas as pd
import numpy as np
import glob
import os

NEO4J_URI = "bolt://localhost:7688"
DRIVER = GraphDatabase.driver(NEO4J_URI, auth=None)

# ─── Utility ──────────────────────────────────────────────────────────────────

def run_query(query, params=None):
    with DRIVER.session() as session:
        return [dict(r) for r in session.run(query, params or {})]

def batch_write(records, query, batch_size=500):
    total = 0
    for i in range(0, len(records), batch_size):
        batch = records[i:i+batch_size]
        with DRIVER.session() as session:
            result = session.execute_write(lambda tx, b: tx.run(query, rows=b).single()["cnt"], batch)
            total += result
    return total

def get_cvd_genes():
    return set(r["symbol"] for r in run_query("MATCH (g:Gene) RETURN g.geneSymbol as symbol") if r["symbol"])

def get_cvd_doids():
    return set(r["doid"] for r in run_query("MATCH (d:Disease) RETURN d.xrefDiseaseOntology as doid") if r["doid"])

def get_cvd_drug_names():
    return set(r["name"] for r in run_query("MATCH (d:Drug) RETURN d.commonName as name") if r["name"])

def create_indexes():
    for idx in [
        "CREATE INDEX ON :Gene(geneSymbol)",
        "CREATE INDEX ON :Disease(xrefDiseaseOntology)",
        "CREATE INDEX ON :Drug(commonName)",
        "CREATE INDEX ON :SideEffect(xrefUmlsCUI)",
    ]:
        try:
            with DRIVER.session() as s:
                s.run(idx)
        except Exception:
            pass

# ─── 1. OpenTargets ───────────────────────────────────────────────────────────

def load_opentargets(cvd_genes, cvd_doids):
    df = pd.read_csv("./data/processed/opentargets/cvd_gene_disease_edges.tsv", sep="\t")
    records = df[["geneSymbol", "xrefDiseaseOntology", "score"]].to_dict("records")
    query = """
    UNWIND $rows AS row
    MATCH (g:Gene {geneSymbol: row.geneSymbol})
    MATCH (d:Disease {xrefDiseaseOntology: row.xrefDiseaseOntology})
    MERGE (g)-[r:geneAssociatesWithDisease {source: 'OpenTargets'}]->(d)
    ON CREATE SET r.score = row.score
    ON MATCH  SET r.score = row.score
    RETURN count(r) as cnt
    """
    cnt = batch_write(records, query)
    print(f"  OpenTargets geneAssociatesWithDisease: {cnt:,}")

# ─── 2. DrugCentral ───────────────────────────────────────────────────────────

def load_drugcentral():
    for rel_type, fname in [
        ("drugTreatsDisease",   "drug_treats_disease_edges.tsv"),
        ("drugPalliatesDisease","drug_palliates_disease_edges.tsv"),
    ]:
        df = pd.read_csv(f"./data/processed/drugcentral/{fname}", sep="\t")
        records = df[["commonName", "doid"]].to_dict("records")
        query = f"""
        UNWIND $rows AS row
        MATCH (dr:Drug {{commonName: row.commonName}})
        MATCH (di:Disease {{xrefDiseaseOntology: row.doid}})
        MERGE (dr)-[r:{rel_type} {{source: 'DrugCentral'}}]->(di)
        ON CREATE SET r.source = 'DrugCentral'
        RETURN count(r) as cnt
        """
        cnt = batch_write(records, query)
        print(f"  DrugCentral {rel_type}: {cnt:,}")

# ─── 3. PubTator ──────────────────────────────────────────────────────────────

def load_pubtator():
    df = pd.read_csv("./data/processed/pubtator/cvd_disease_disease_edges.tsv", sep="\t")
    records = df[["disease1", "disease2"]].to_dict("records")
    query = """
    UNWIND $rows AS row
    MATCH (d1:Disease {xrefDiseaseOntology: row.disease1})
    MATCH (d2:Disease {xrefDiseaseOntology: row.disease2})
    MERGE (d1)-[r:diseaseAssociatesWithDisease {source: 'PubTator'}]->(d2)
    ON CREATE SET r.source = 'PubTator'
    RETURN count(r) as cnt
    """
    cnt = batch_write(records, query)
    print(f"  PubTator diseaseAssociatesWithDisease: {cnt:,}")

# ─── 4. SIDER ─────────────────────────────────────────────────────────────────

def load_sider():
    # SideEffect nodes
    df_nodes = pd.read_csv("./data/processed/sider/side_effect_nodes.tsv", sep="\t")
    node_query = """
    UNWIND $rows AS row
    MERGE (s:SideEffect {xrefUmlsCUI: row.xrefUmlsCUI})
    ON CREATE SET s.name = row.sideEffectName, s.primaryKey = row.xrefUmlsCUI, s.source = 'SIDER'
    ON MATCH  SET s.name = row.sideEffectName
    RETURN count(s) as cnt
    """
    cnt_nodes = batch_write(df_nodes.to_dict("records"), node_query)
    print(f"  SIDER SideEffect nodes: {cnt_nodes:,}")

    # Edges
    df_edges = pd.read_csv("./data/processed/sider/cvd_drug_side_effect_edges.tsv", sep="\t")
    edge_query = """
    UNWIND $rows AS row
    MATCH (dr:Drug {commonName: row.commonName})
    MATCH (se:SideEffect {xrefUmlsCUI: row.xrefUmlsCUI})
    MERGE (dr)-[r:compoundCausesSideEffect {source: 'SIDER'}]->(se)
    ON CREATE SET r.source = 'SIDER'
    RETURN count(r) as cnt
    """
    cnt_edges = batch_write(df_edges[["commonName", "xrefUmlsCUI"]].to_dict("records"), edge_query)
    print(f"  SIDER compoundCausesSideEffect: {cnt_edges:,}")

# ─── Main ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("Creating indexes...")
    create_indexes()

    print("\nLoading disease associations...")
    cvd_genes = get_cvd_genes()
    cvd_doids = get_cvd_doids()
    cvd_drugs = get_cvd_drug_names()

    load_opentargets(cvd_genes, cvd_doids)
    load_drugcentral()
    load_pubtator()
    load_sider()

    print("\nDone!")
    DRIVER.close()
