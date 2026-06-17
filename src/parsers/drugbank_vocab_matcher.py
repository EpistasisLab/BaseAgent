#!/usr/bin/env python3
"""
DrugBank Vocabulary Enhanced Drug Matcher for CardioKB
Uses DrugBank vocabulary synonyms to improve LINCS L1000 drug matching.
Source: https://go.drugbank.com/releases/latest#open-data
"""

import pandas as pd
import re
import json
import os


def normalize_strict(s):
    return re.sub(r"[^a-z0-9]", "", s.lower()) if s else ""

def normalize_drug(s):
    return s.lower().strip().replace("-", " ").replace("_", " ") if s else ""


# Known incorrect synonym mappings to exclude
EXCLUDE_MATCHES = {"Quinine"}  # Quinine ≠ Quinidine


def build_enhanced_drug_lookup(db_drug_records: list, vocab_file: str) -> dict:
    """
    Build comprehensive drug name lookup combining DB drug names/aliases
    with DrugBank vocabulary synonyms.
    
    Args:
        db_drug_records: list of dicts with 'name', 'dbid', 'aliases'
        vocab_file: path to drugbank_vocabulary.csv
    
    Returns:
        dict: normalized_name -> DB commonName
    """
    lookup = {}

    # Step 1: Base lookup from DB drug names + aliases
    for r in db_drug_records:
        name = r.get("name") or r.get("commonName")
        if name:
            lookup[name.lower().strip()] = name
            lookup[normalize_drug(name)] = name
            lookup[normalize_strict(name)] = name
        aliases = r.get("aliases") or r.get("drugAliases") or []
        for alias in aliases:
            if alias:
                lookup[alias.lower().strip()] = name
                lookup[normalize_drug(alias)] = name
                lookup[normalize_strict(alias)] = name

    # Step 2: DrugBank vocabulary synonyms -> DB commonName via DrugBank ID
    dbid_to_name = {r.get("dbid", ""): r.get("name") or r.get("commonName")
                    for r in db_drug_records if r.get("dbid")}

    df_vocab = pd.read_csv(vocab_file)
    for _, row in df_vocab.iterrows():
        dbid = str(row["DrugBank ID"]).strip()
        if dbid not in dbid_to_name:
            continue
        db_name = dbid_to_name[dbid]
        cname = str(row["Common name"]) if pd.notna(row["Common name"]) else ""
        synonyms = []
        if cname:
            synonyms.append(cname)
        if pd.notna(row["Synonyms"]):
            synonyms.extend([s.strip() for s in str(row["Synonyms"]).split("|")])
        for syn in synonyms:
            if syn and syn not in EXCLUDE_MATCHES:
                lookup[syn.lower().strip()] = db_name
                lookup[normalize_drug(syn)] = db_name
                lookup[normalize_strict(syn)] = db_name

    return lookup


def match_drug(drug_str: str, lookup: dict) -> str:
    """Match a drug name string to DB commonName."""
    if not drug_str or pd.isna(drug_str):
        return None
    return (lookup.get(drug_str.lower().strip()) or
            lookup.get(normalize_drug(drug_str)) or
            lookup.get(normalize_strict(drug_str)))


if __name__ == "__main__":
    from neo4j import GraphDatabase
    driver = GraphDatabase.driver("bolt://localhost:7688", auth=None)
    with driver.session() as session:
        result = session.run(
            "MATCH (d:Drug) RETURN d.commonName as name, d.drugBankId as dbid, "
            "d.drugAliases as aliases"
        )
        db_records = [dict(r) for r in result]
    driver.close()

    lookup = build_enhanced_drug_lookup(
        db_records,
        "./data/processed/drugbank/drugbank_vocabulary.csv"
    )
    print(f"Enhanced drug lookup: {len(lookup):,} entries")

    # Test with known LINCS drugs
    test_drugs = ["Torasemide", "Icosapent", "Benzatropine", "D-Mannitol", "Kcl"]
    for drug in test_drugs:
        matched = match_drug(drug, lookup)
        print(f"  {drug} -> {matched}")
