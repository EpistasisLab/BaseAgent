"""
Disease Ontology Parser - CVD Diseases
Parses doid.obo and filters to cardiovascular disease subtree
"""
import re
import pandas as pd
from collections import defaultdict

CVD_ROOT_TERMS = {
    "heart failure", "coronary artery disease", "myocardial infarction",
    "atrial fibrillation", "cardiomyopathy", "aortic stenosis",
    "hypertension", "stroke", "atherosclerosis", "cardiac arrest",
    "ventricular tachycardia", "pulmonary hypertension", "heart valve disease",
    "endocarditis", "pericarditis", "aortic aneurysm", "peripheral artery disease",
    "deep vein thrombosis", "pulmonary embolism", "congenital heart disease",
    "arrhythmia", "angina pectoris", "cardiovascular system disease",
    "vascular disease", "heart disease", "coronary heart disease",
    "ischemic heart disease", "cardiac conduction disease",
    "cardiomegaly", "cardiomyopathy", "dilated cardiomyopathy",
    "hypertrophic cardiomyopathy", "restrictive cardiomyopathy",
    "aortic disease", "arterial occlusive disease", "arteriosclerosis",
    "thrombosis", "embolism", "cerebrovascular disease",
    "transient ischemic attack", "aortic valve stenosis",
    "mitral valve disease", "tricuspid valve disease",
    "ventricular fibrillation", "bradycardia", "tachycardia",
    "sick sinus syndrome", "wolff-parkinson-white syndrome",
    "long qt syndrome", "brugada syndrome", "catecholaminergic polymorphic ventricular tachycardia",
}

def parse_obo(obo_path):
    """Parse OBO file into list of term dicts."""
    print(f"Parsing {obo_path}...")
    terms = []
    current = {}
    synonyms_list = []
    is_a_list = []
    
    with open(obo_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line == "[Term]":
                if current.get("id"):
                    current["synonyms"] = "|".join(synonyms_list)
                    current["is_a"] = "|".join(is_a_list)
                    terms.append(current)
                current = {}
                synonyms_list = []
                is_a_list = []
            elif line.startswith("id: "):
                current["id"] = line[4:].strip()
            elif line.startswith("name: "):
                current["name"] = line[6:].strip()
            elif line.startswith("def: "):
                # Extract text between first pair of quotes
                m = re.match(r'def: "(.+?)" \[', line)
                if m:
                    current["definition"] = m.group(1)
            elif line.startswith("synonym: "):
                m = re.search(r'"(.+?)"', line)
                if m:
                    synonyms_list.append(m.group(1))
            elif line.startswith("is_a: "):
                parent_id = line[6:].split("!")[0].strip()
                is_a_list.append(parent_id)
            elif line.startswith("is_obsolete: true"):
                current["obsolete"] = True
        # Last term
        if current.get("id"):
            current["synonyms"] = "|".join(synonyms_list)
            current["is_a"] = "|".join(is_a_list)
            terms.append(current)
    
    print(f"  Total terms parsed: {len(terms)}")
    return terms

def build_hierarchy(terms):
    """Build parent->children and child->parents maps."""
    children = defaultdict(set)
    parents = defaultdict(set)
    
    for t in terms:
        for parent in t.get("is_a", "").split("|"):
            parent = parent.strip()
            if parent:
                children[parent].add(t["id"])
                parents[t["id"]].add(parent)
    
    return children, parents

def get_all_descendants(root_ids, children_map):
    """BFS to get all descendants of given root IDs."""
    visited = set(root_ids)
    queue = list(root_ids)
    while queue:
        node = queue.pop(0)
        for child in children_map.get(node, []):
            if child not in visited:
                visited.add(child)
                queue.append(child)
    return visited

def filter_cvd_terms(terms, cvd_root_names):
    """Filter terms to CVD subtree."""
    # Build lookup by name
    name_to_id = {}
    id_to_term = {}
    for t in terms:
        if not t.get("obsolete"):
            name_to_id[t["name"].lower()] = t["id"]
            id_to_term[t["id"]] = t
    
    # Find root IDs for CVD terms
    root_ids = set()
    for name in cvd_root_names:
        if name.lower() in name_to_id:
            root_ids.add(name_to_id[name.lower()])
            print(f"  Found CVD root: {name} -> {name_to_id[name.lower()]}")
        else:
            # Partial match
            for k, v in name_to_id.items():
                if name.lower() in k:
                    root_ids.add(v)
                    print(f"  Partial match: {name} -> {k} ({v})")
                    break
    
    print(f"\n  Root IDs found: {len(root_ids)}")
    
    # Build hierarchy
    children_map, _ = build_hierarchy(terms)
    
    # Get all descendants
    all_cvd_ids = get_all_descendants(root_ids, children_map)
    print(f"  Total CVD disease IDs (including descendants): {len(all_cvd_ids)}")
    
    # Filter terms
    cvd_terms = [id_to_term[tid] for tid in all_cvd_ids if tid in id_to_term]
    return cvd_terms

def build_disease_tsv(cvd_terms):
    rows = []
    for t in cvd_terms:
        rows.append({
            "xrefDiseaseOntology": t["id"],
            "diseaseName":         t["name"],
            "definition":          t.get("definition", ""),
            "synonyms":            t.get("synonyms", ""),
            "source":              "Disease Ontology",
        })
    df = pd.DataFrame(rows)
    return df

if __name__ == "__main__":
    obo_path = "./data/processed/disease_ontology/doid.obo"
    
    terms = parse_obo(obo_path)
    cvd_terms = filter_cvd_terms(terms, CVD_ROOT_TERMS)
    df = build_disease_tsv(cvd_terms)
    
    out_path = "./data/processed/disease_ontology/cvd_diseases_final.tsv"
    df.to_csv(out_path, sep="\t", index=False)
    print(f"\nSaved {len(df)} disease records to {out_path}")
    print(df.head(5).to_string())
    
    # Show sample CVD diseases
    print("\nSample CVD diseases:")
    for name in ["heart failure", "myocardial infarction", "atrial fibrillation",
                 "hypertension", "atherosclerosis", "cardiomyopathy"]:
        matches = df[df["diseaseName"].str.lower().str.contains(name)]
        print(f"  {name}: {len(matches)} matches")
