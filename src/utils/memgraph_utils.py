
"""
Utility functions for building the CardioKB knowledge graph
"""

import pandas as pd
import requests
import os
# neo4j package provides bolt driver compatible with Memgraph
from neo4j import GraphDatabase
from tqdm import tqdm
import gzip
import json
import logging

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# CVD terms for filtering
CVD_TERMS = [
    "heart failure", "coronary artery disease", "myocardial infarction", 
    "atrial fibrillation", "cardiomyopathy", "aortic stenosis", "hypertension", 
    "stroke", "atherosclerosis", "cardiac arrest", "ventricular tachycardia", 
    "pulmonary hypertension", "heart valve disease", "endocarditis", 
    "pericarditis", "aortic aneurysm", "peripheral artery disease", 
    "deep vein thrombosis", "pulmonary embolism", "congenital heart disease", 
    "arrhythmia", "angina pectoris", "cardiovascular", "cardiac", "cardio"
]

class MemgraphConnection:
    """Handle Memgraph database connections and operations"""
    
    def __init__(self, uri="bolt://localhost:7688"):
        self.uri = uri
        self.driver = GraphDatabase.driver(uri)
    
    def close(self):
        """Close the database connection"""
        self.driver.close()
    
    def execute_query(self, query, parameters=None):
        """Execute a Cypher query"""
        with self.driver.session() as session:
            result = session.run(query, parameters or {})
            return [record for record in result]
    
    def load_nodes_from_tsv(self, file_path, node_type, primary_key):
        """Load nodes from TSV file using MERGE"""
        df = pd.read_csv(file_path, sep='\t')
        logger.info(f"Loading {len(df)} {node_type} nodes from {file_path}")
        
        with self.driver.session() as session:
            for _, row in tqdm(df.iterrows(), total=len(df), desc=f"Loading {node_type}"):
                properties = {k: v for k, v in row.to_dict().items() if pd.notna(v)}
                
                # Build property string for Cypher
                prop_string = ", ".join([f"{k}: ${k}" for k in properties.keys()])
                
                query = f"""
                MERGE (n:{node_type} {{{primary_key}: ${primary_key}}})
                SET n += {{{prop_string}}}
                """
                
                session.run(query, properties)
        
        logger.info(f"✓ Loaded {len(df)} {node_type} nodes")
    
    def load_edges_from_tsv(self, file_path, edge_type, source_key, target_key):
        """Load edges from TSV file using MERGE"""
        df = pd.read_csv(file_path, sep='\t')
        logger.info(f"Loading {len(df)} {edge_type} edges from {file_path}")
        
        with self.driver.session() as session:
            for _, row in tqdm(df.iterrows(), total=len(df), desc=f"Loading {edge_type}"):
                properties = {k: v for k, v in row.to_dict().items() 
                            if pd.notna(v) and k not in [source_key, target_key]}
                
                # Build property string for Cypher
                prop_string = ", ".join([f"{k}: ${k}" for k in properties.keys()]) if properties else ""
                set_clause = f"SET r += {{{prop_string}}}" if prop_string else ""
                
                query = f"""
                MATCH (source), (target)
                WHERE source.{source_key} = ${source_key} AND target.{target_key} = ${target_key}
                MERGE (source)-[r:{edge_type}]->(target)
                {set_clause}
                """
                
                params = row.to_dict()
                session.run(query, params)
        
        logger.info(f"✓ Loaded {len(df)} {edge_type} edges")
    
    def get_node_count(self, node_type=None):
        """Get count of nodes, optionally filtered by type"""
        if node_type:
            query = f"MATCH (n:{node_type}) RETURN count(n) AS count"
        else:
            query = "MATCH (n) RETURN count(n) AS count"
        
        result = self.execute_query(query)
        return result[0]["count"] if result else 0
    
    def get_edge_count(self, edge_type=None):
        """Get count of edges, optionally filtered by type"""
        if edge_type:
            query = f"MATCH ()-[r:{edge_type}]->() RETURN count(r) AS count"
        else:
            query = "MATCH ()-[r]->() RETURN count(r) AS count"
        
        result = self.execute_query(query)
        return result[0]["count"] if result else 0

def download_file(url, local_path, chunk_size=8192):
    """Download a file from URL to local path"""
    logger.info(f"Downloading {url} to {local_path}")
    
    os.makedirs(os.path.dirname(local_path), exist_ok=True)
    
    response = requests.get(url, stream=True)
    response.raise_for_status()
    
    total_size = int(response.headers.get('content-length', 0))
    
    with open(local_path, 'wb') as f, tqdm(
        desc=os.path.basename(local_path),
        total=total_size,
        unit='B',
        unit_scale=True,
        unit_divisor=1024,
    ) as pbar:
        for chunk in response.iter_content(chunk_size=chunk_size):
            if chunk:
                f.write(chunk)
                pbar.update(len(chunk))
    
    logger.info(f"✓ Downloaded {local_path}")
    return local_path

def is_cvd_related(text, terms=CVD_TERMS):
    """Check if text is related to cardiovascular disease"""
    if not text or pd.isna(text):
        return False
    
    text_lower = str(text).lower()
    return any(term.lower() in text_lower for term in terms)

def save_tsv(df, file_path, description=""):
    """Save DataFrame as TSV file"""
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    df.to_csv(file_path, sep='\t', index=False)
    logger.info(f"✓ Saved {len(df)} rows to {file_path} {description}")

def load_json_gz(file_path):
    """Load JSON from gzipped file"""
    with gzip.open(file_path, 'rt') as f:
        return json.load(f)
