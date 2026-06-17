#!/usr/bin/env python3
"""
Parser for Disease Ontology (DOID) OBO format.
Extracts CVD-relevant disease terms including ancestors/descendants.
Output: TSV with columns: xrefDiseaseOntology, diseaseName, diseaseDescription, source
"""

import re
import urllib.request
import os
from collections import defaultdict

OBO_URL = "https://raw.githubusercontent.com/DiseaseOntology/HumanDiseaseOntology/main/src/ontology/doid.obo"
OUTPUT_TSV = "./data/processed/disease_ontology/diseases.tsv"

# CVD seed terms to search for (case-insensitive substring match)
CVD_SEED_TERMS = [
    "heart failure", "coronary artery disease", "myocardial infarction",
    "atrial fibrillation", "cardiomyopathy", "aortic stenosis", "hypertension",
    "stroke", "atherosclerosis", "cardiac arrest", "ventricular tachycardia",
    "pulmonary hypertension", "heart valve disease", "endocarditis", "pericarditis",
    "aortic aneurysm", "peripheral artery disease", "deep vein thrombosis",
    "pulmonary embolism", "congenital heart disease", "arrhythmia", "angina pectoris",
    "cardiovascular", "cardiac", "vascular", "arterial", "ventricular", "aortic",
    "mitral", "tricuspid", "pericardial", "myocardial", "ischemic heart",
    "heart disease", "coronary", "thrombosis", "embolism", "aneurysm",
    "cardiomegaly", "bradycardia", "tachycardia", "fibrillation", "flutter",
    "stenosis", "regurgitation", "infarction"
]

def download_obo(url):
    print(f"Downloading OBO from: {url}")
    with urllib.request.urlopen(url) as response:
        content = response.read().decode("utf-8")
    print(f"Downloaded {len(content):,} characters")
    return content

def parse_obo(content):
    """Parse OBO format into a dict of term_id -> term_data."""
    terms = {}
    current_term = None
    
    for line in content.splitlines():
        line = line.strip()
        
        if line == "[Term]":
            current_term = {
                "id": None,
                "name": None,
                "def": None,
                "is_a": [],
                "is_obsolete": False,
                "synonym": [],
                "xref": []
            }
        elif line == "" and current_term is not None:
            if current_term["id"] and not current_term["is_obsolete"]:
                terms[current_term["id"]] = current_term
            current_term = None
        elif current_term is not None:
            if line.startswith("id: "):
                current_term["id"] = line[4:].strip()
            elif line.startswith("name: "):
                current_term["name"] = line[6:].strip()
            elif line.startswith("def: "):
                # Extract text between first pair of quotes
                m = re.match(r'def: "(.+?)" \[', line)
                if m:
                    current_term["def"] = m.group(1).strip()
            elif line.startswith("is_a: "):
                parent = line[6:].split("!")[0].strip()
                current_term["is_a"].append(parent)
            elif line.startswith("is_obsolete: true"):
                current_term["is_obsolete"] = True
    
    # Handle last term if file doesn't end with blank line
    if current_term and current_term["id"] and not current_term["is_obsolete"]:
        terms[current_term["id"]] = current_term
    
    print(f"Parsed {len(terms):,} non-obsolete DOID terms")
    return terms

def build_hierarchy(terms):
    """Build parent->children and child->parents maps."""
    children = defaultdict(set)
    parents = defaultdict(set)
    
    for tid, term in terms.items():
        for parent in term["is_a"]:
            if parent in terms:
                children[parent].add(tid)
                parents[tid].add(parent)
    
    return children, parents

def get_all_descendants(term_id, children):
    """BFS to get all descendant term IDs."""
    visited = set()
    queue = [term_id]
    while queue:
        current = queue.pop(0)
        if current in visited:
            continue
        visited.add(current)
        for child in children.get(current, []):
            queue.append(child)
    visited.discard(term_id)
    return visited

def get_all_ancestors(term_id, parents):
    """BFS to get all ancestor term IDs."""
    visited = set()
    queue = [term_id]
    while queue:
        current = queue.pop(0)
        if current in visited:
            continue
        visited.add(current)
        for parent in parents.get(current, []):
            queue.append(parent)
    visited.discard(term_id)
    return visited

def find_cvd_terms(terms, children, parents):
    """Find all CVD-relevant terms via seed matching + hierarchy traversal."""
    # Step 1: Find seed terms by name matching
    seed_ids = set()
    for tid, term in terms.items():
        name = (term["name"] or "").lower()
        for seed in CVD_SEED_TERMS:
            if seed in name:
                seed_ids.add(tid)
                break
    
    print(f"Found {len(seed_ids)} seed CVD terms by name matching")
    
    # Step 2: Expand to all descendants and ancestors
    expanded_ids = set(seed_ids)
    
    for sid in seed_ids:
        # Get descendants (subtypes of CVD diseases)
        descendants = get_all_descendants(sid, children)
        expanded_ids.update(descendants)
        
        # Get ancestors up to cardiovascular root (limit depth)
        ancestors = get_all_ancestors(sid, parents)
        # Only include ancestors that are themselves disease terms (DOID:4 = disease)
        # Filter to keep relevant ones (not too generic)
        for anc in ancestors:
            anc_name = (terms.get(anc, {}).get("name") or "").lower()
            for seed in CVD_SEED_TERMS:
                if seed in anc_name:
                    expanded_ids.add(anc)
                    break
    
    print(f"Expanded to {len(expanded_ids)} CVD-related terms (including descendants)")
    return expanded_ids

def main():
    os.makedirs(os.path.dirname(OUTPUT_TSV), exist_ok=True)
    
    # Download and parse
    content = download_obo(OBO_URL)
    terms = parse_obo(content)
    children, parents = build_hierarchy(terms)
    
    # Find CVD terms
    cvd_ids = find_cvd_terms(terms, children, parents)
    
    # Write TSV
    written = 0
    with open(OUTPUT_TSV, "w", encoding="utf-8") as f:
        f.write("xrefDiseaseOntology\tdiseaseName\tdiseaseDescription\tsource\n")
        for tid in sorted(cvd_ids):
            if tid not in terms:
                continue
            term = terms[tid]
            name = (term["name"] or "").replace("\t", " ").replace("\n", " ")
            desc = (term["def"] or "").replace("\t", " ").replace("\n", " ")
            f.write(f"{tid}\t{name}\t{desc}\tDiseaseOntology\n")
            written += 1
    
    print(f"\nWrote {written} disease records to: {OUTPUT_TSV}")
    
    # Preview
    print("\nFirst 5 rows:")
    with open(OUTPUT_TSV) as f:
        for i, line in enumerate(f):
            if i >= 6:
                break
            print(line.rstrip())

if __name__ == "__main__":
    main()
