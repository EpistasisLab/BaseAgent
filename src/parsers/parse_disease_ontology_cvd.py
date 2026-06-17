#!/usr/bin/env python3
"""
Parser: Disease Ontology OBO → CVD Disease nodes
Filters to CVD-relevant diseases and their subtypes.
Source: doid.obo (Disease Ontology)
Output: cvd_diseases_final.tsv
"""

import pandas as pd

CVD_SEED_TERMS = [
    "heart failure", "coronary artery disease", "myocardial infarction",
    "atrial fibrillation", "cardiomyopathy", "aortic stenosis", "hypertension",
    "stroke", "atherosclerosis", "cardiac arrest", "ventricular tachycardia",
    "pulmonary hypertension", "heart valve disease", "endocarditis", "pericarditis",
    "aortic aneurysm", "peripheral artery disease", "deep vein thrombosis",
    "pulmonary embolism", "congenital heart disease", "arrhythmia", "angina pectoris"
]

def load_cvd_diseases(filepath: str) -> pd.DataFrame:
    """Load CVD disease nodes from processed TSV."""
    df = pd.read_csv(filepath, sep="\t")
    df = df.dropna(subset=["xrefDiseaseOntology"])
    df = df.drop_duplicates(subset=["xrefDiseaseOntology"])
    df["definition"] = df["definition"].fillna("")
    df["synonyms"] = df["synonyms"].fillna("")
    return df

if __name__ == "__main__":
    filepath = "./data/processed/disease_ontology/cvd_diseases_final.tsv"
    df = load_cvd_diseases(filepath)
    print(f"Loaded {len(df)} CVD diseases")
    print(df.head(5).to_string())
