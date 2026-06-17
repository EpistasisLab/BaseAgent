"""
Shared utilities for CardioKB knowledge graph building.
"""
# neo4j package provides bolt driver compatible with Memgraph
from neo4j import GraphDatabase
import csv, os, requests, gzip, time

# Memgraph connection
BOLT_URI = "bolt://localhost:7688"

def get_driver():
    return GraphDatabase.driver(BOLT_URI, auth=None)

def run_query(driver, query, parameters=None, batch=False):
    with driver.session() as session:
        if parameters:
            result = session.run(query, parameters)
        else:
            result = session.run(query)
        return result.data()

def batch_merge(driver, query, rows, batch_size=500):
    """Execute a parameterized query in batches."""
    total = 0
    with driver.session() as session:
        for i in range(0, len(rows), batch_size):
            batch = rows[i:i+batch_size]
            session.run(query, {"rows": batch})
            total += len(batch)
    return total

# CVD disease terms for filtering
CVD_TERMS = [
    "heart failure", "coronary artery disease", "myocardial infarction",
    "atrial fibrillation", "cardiomyopathy", "aortic stenosis",
    "hypertension", "stroke", "atherosclerosis", "cardiac arrest",
    "ventricular tachycardia", "pulmonary hypertension", "heart valve disease",
    "endocarditis", "pericarditis", "aortic aneurysm", "peripheral artery disease",
    "deep vein thrombosis", "pulmonary embolism", "congenital heart disease",
    "arrhythmia", "angina pectoris", "cardiovascular", "cardiac", "heart disease",
    "vascular disease", "aortic", "coronary", "ventricular", "atrial",
    "cardiomyopathy", "ischemic heart", "heart attack", "bradycardia",
    "tachycardia", "fibrillation", "flutter", "stenosis", "regurgitation",
    "thrombosis", "embolism", "aneurysm", "arteriosclerosis"
]

def is_cvd_related(text):
    """Check if a text is related to CVD."""
    if not text:
        return False
    text_lower = text.lower()
    return any(term in text_lower for term in CVD_TERMS)
