#!/usr/bin/env python3
"""
Parse Disease Ontology OBO file and filter to CVD scope.
Outputs disease_nodes.tsv and disease_isSubtypeOf_edges.tsv
Usage: python parse_doid.py <doid.obo> <output_dir>
"""
import re, sys, os, csv
from collections import defaultdict

CVD_SEED_DOIDS = [
    "DOID:6713",   # cerebrovascular disease
    "DOID:1287",   # cardiovascular system disease
    "DOID:114",    # heart disease
    "DOID:178",    # vascular disease
    "DOID:10763",  # hypertension
    "DOID:3393",   # coronary artery disease
    "DOID:5844",   # myocardial infarction
    "DOID:0050700",# cardiomyopathy
    "DOID:0060224",# atrial fibrillation
    "DOID:1712",   # aortic valve stenosis
    "DOID:1936",   # atherosclerosis
    "DOID:0060319",# cardiac arrest
    "DOID:6432",   # pulmonary hypertension
    "DOID:4079",   # heart valve disease
    "DOID:10314",  # endocarditis
    "DOID:1787",   # pericarditis
    "DOID:3627",   # aortic aneurysm
    "DOID:0050830",# peripheral artery disease
    "DOID:9477",   # pulmonary embolism
    "DOID:1682",   # congenital heart disease
    "DOID:0051061",# stroke
    "DOID:0060903",# thrombosis
    "DOID:10273",  # heart conduction disease
    "DOID:0111151",# Prinzmetal angina
    "DOID:0060674",# catecholaminergic polymorphic ventricular tachycardia
]

def parse_obo(path):
    terms = []
    current = None
    with open(path) as f:
        for line in f:
            line = line.rstrip("\n")
            if line == "[Term]":
                if current is not None:
                    terms.append(current)
                current = {"id": None, "name": None, "def": None, "is_a": [],
                          "is_obsolete": False, "alt_ids": [], "xrefs": [], "synonyms": []}
            elif line.startswith("[") and current is not None:
                terms.append(current); current = None
            elif current is not None and ": " in line:
                k, v = line.split(": ", 1)
                if k == "id": current["id"] = v.strip()
                elif k == "name": current["name"] = v.strip()
                elif k == "def":
                    m = re.match(r'"((?:[^"\\]|\\.)*)"', v)
                    current["def"] = m.group(1) if m else v
                elif k == "is_a":
                    current["is_a"].append(v.split("!")[0].strip())
                elif k == "is_obsolete" and v.strip() == "true":
                    current["is_obsolete"] = True
                elif k == "xref": current["xrefs"].append(v.strip())
                elif k == "synonym":
                    m = re.match(r'"((?:[^"\\]|\\.)*)"', v)
                    if m: current["synonyms"].append(m.group(1))
        if current: terms.append(current)
    return [t for t in terms if t["id"] and not t["is_obsolete"]]

def main():
    obo_path, out_dir = sys.argv[1], sys.argv[2]
    os.makedirs(out_dir, exist_ok=True)
    terms = parse_obo(obo_path)
    by_id = {t["id"]: t for t in terms}
    children = defaultdict(set)
    for t in terms:
        for p in t["is_a"]:
            children[p].add(t["id"])

    def descendants(seed):
        v = set(); st = [seed]
        while st:
            c = st.pop()
            if c in v: continue
            v.add(c)
            for x in children.get(c, []): st.append(x)
        return v
    def ancestors(seed):
        v = set(); st = [seed]
        while st:
            c = st.pop()
            if c in v: continue
            v.add(c)
            for x in by_id.get(c, {}).get("is_a", []): st.append(x)
        return v

    all_terms = set()
    for s in CVD_SEED_DOIDS:
        if s in by_id:
            all_terms |= descendants(s)
            all_terms |= ancestors(s)
    all_terms = {t for t in all_terms if t in by_id}

    # write nodes
    nrows, erows = [], []
    for tid in all_terms:
        t = by_id[tid]
        # parse xrefs
        xr = {"MESH":[], "ICD10CM":[], "SNOMEDCT":[], "UMLS_CUI":[], "OMIM":[], "NCI":[]}
        for x in t["xrefs"]:
            for k in xr:
                if x.startswith(k+":"): xr[k].append(x.split(":",1)[1])
        nrows.append({
            "xrefDiseaseOntology": tid,
            "diseaseName": t["name"] or "",
            "diseaseDescription": t.get("def") or "",
            "synonyms": "|".join(t["synonyms"]),
            "xrefMeSH": "|".join(xr["MESH"]),
            "xrefICD10": "|".join(xr["ICD10CM"]),
            "xrefSNOMED": "|".join(xr["SNOMEDCT"]),
            "xrefUMLS": "|".join(xr["UMLS_CUI"]),
            "xrefOMIM": "|".join(xr["OMIM"]),
            "xrefNCI": "|".join(xr["NCI"]),
            "source": "DiseaseOntology",
        })
        for p in t["is_a"]:
            if p in all_terms:
                erows.append({"child": tid, "parent": p, "source": "DiseaseOntology"})

    with open(os.path.join(out_dir, "disease_nodes.tsv"), "w") as f:
        w = csv.DictWriter(f, fieldnames=list(nrows[0].keys()), delimiter="\t")
        w.writeheader(); w.writerows(nrows)
    with open(os.path.join(out_dir, "disease_isSubtypeOf_edges.tsv"), "w") as f:
        w = csv.DictWriter(f, fieldnames=["child","parent","source"], delimiter="\t")
        w.writeheader(); w.writerows(erows)
    print(f"Wrote {len(nrows)} disease nodes and {len(erows)} edges")

if __name__ == "__main__":
    main()
