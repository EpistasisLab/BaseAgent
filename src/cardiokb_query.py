#!/usr/bin/env python3
"""
CardioKB - Cardiovascular Disease Knowledge Graph
Built on Memgraph database

This script provides utilities for querying and analyzing the CardioKB knowledge graph.
"""

from neo4j import GraphDatabase
import pandas as pd

class CardioKB:
    def __init__(self, uri="bolt://localhost:7687", user=None, password=None):
        self.driver = GraphDatabase.driver(uri, auth=(user, password) if user else None)
    
    def close(self):
        self.driver.close()
    
    def get_stats(self):
        """Get basic statistics about the knowledge graph"""
        with self.driver.session() as session:
            # Node counts
            result = session.run("MATCH (n) RETURN labels(n)[0] AS nodeType, count(n) AS count ORDER BY count DESC")
            nodes = {record['nodeType']: record['count'] for record in result}
            
            # Relationship counts  
            result = session.run("MATCH ()-[r]->() RETURN type(r) AS relType, count(r) AS count ORDER BY count DESC LIMIT 10")
            relationships = {record['relType']: record['count'] for record in result}
            
            return {'nodes': nodes, 'relationships': relationships}
    
    def find_cvd_diseases(self, limit=10):
        """Find CVD-related diseases"""
        with self.driver.session() as session:
            result = session.run("""
                MATCH (d:Disease) 
                WHERE d.diseaseName CONTAINS 'heart' OR d.diseaseName CONTAINS 'cardiac' 
                   OR d.diseaseName CONTAINS 'coronary' OR d.diseaseName CONTAINS 'hypertension'
                   OR d.diseaseName CONTAINS 'stroke' OR d.diseaseName CONTAINS 'arrhythmia'
                   OR d.diseaseName CONTAINS 'myocardial' OR d.diseaseName CONTAINS 'vascular'
                RETURN d.diseaseName, d.xrefDiseaseOntology
                LIMIT $limit
            """, limit=limit)
            
            return [(record['d.diseaseName'], record['d.xrefDiseaseOntology']) for record in result]
    
    def find_cvd_drugs(self, limit=10):
        """Find CVD-related drugs"""
        with self.driver.session() as session:
            result = session.run("""
                MATCH (drug:Drug) 
                WHERE drug.indication CONTAINS 'heart' OR drug.indication CONTAINS 'cardiac' 
                   OR drug.indication CONTAINS 'hypertension' OR drug.indication CONTAINS 'coronary'
                   OR drug.indication CONTAINS 'stroke' OR drug.indication CONTAINS 'arrhythmia'
                   OR drug.indication CONTAINS 'myocardial' OR drug.indication CONTAINS 'vascular'
                RETURN drug.commonName, drug.indication
                LIMIT $limit
            """, limit=limit)
            
            return [(record['drug.commonName'], record['drug.indication']) for record in result]
    
    def find_gene_disease_drug_paths(self, limit=5):
        """Find gene-disease-drug therapeutic paths"""
        with self.driver.session() as session:
            result = session.run("""
                MATCH (gene:Gene)-[r1:geneAssociatesWithDisease]->(disease:Disease)<-[r2:drugTreatsDisease]-(drug:Drug)
                WHERE disease.diseaseName CONTAINS 'heart' OR disease.diseaseName CONTAINS 'cardiac'
                   OR disease.diseaseName CONTAINS 'coronary' OR disease.diseaseName CONTAINS 'stroke'
                RETURN gene.geneSymbol, disease.diseaseName, drug.commonName
                LIMIT $limit
            """, limit=limit)
            
            return [(record['gene.geneSymbol'], record['disease.diseaseName'], record['drug.commonName']) for record in result]

if __name__ == "__main__":
    # Example usage
    kb = CardioKB()
    
    print("=== CardioKB Query Examples ===")
    
    # Get basic stats
    stats = kb.get_stats()
    print(f"\nTotal nodes: {sum(stats['nodes'].values()):,}")
    print(f"Total relationships: {sum(stats['relationships'].values()):,}")
    
    # Find CVD diseases
    diseases = kb.find_cvd_diseases()
    print(f"\nCVD Diseases (sample):")
    for name, doid in diseases[:5]:
        print(f"  {name} ({doid})")
    
    # Find CVD drugs
    drugs = kb.find_cvd_drugs()
    print(f"\nCVD Drugs (sample):")
    for name, indication in drugs[:5]:
        print(f"  {name}: {indication}")
    
    # Find therapeutic paths
    paths = kb.find_gene_disease_drug_paths()
    print(f"\nGene-Disease-Drug Paths:")
    for gene, disease, drug in paths:
        print(f"  {gene} -> {disease} <- {drug}")
    
    kb.close()
