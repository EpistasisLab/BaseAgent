"""
ClinicalTrials.gov Parser for CardioKB
Fetches CVD trials, saves TSVs, loads into Memgraph
"""
import requests
import csv
import time
import os
from neo4j import GraphDatabase

NEO4J_URI = "bolt://localhost:7688"
OUT_DIR = "./data/processed/clinicaltrials"
os.makedirs(OUT_DIR, exist_ok=True)

CVD_CONDITIONS = [
    "heart failure", "coronary artery disease", "myocardial infarction",
    "atrial fibrillation", "cardiomyopathy", "aortic stenosis",
    "hypertension", "stroke", "atherosclerosis", "cardiac arrest",
    "ventricular tachycardia", "pulmonary hypertension", "heart valve disease",
    "endocarditis", "pericarditis", "aortic aneurysm", "peripheral artery disease",
    "deep vein thrombosis", "pulmonary embolism", "congenital heart disease",
    "arrhythmia", "angina pectoris"
]

BASE_URL = "https://clinicaltrials.gov/api/v2/studies"

def fetch_trials_for_condition(condition, max_pages=5):
    trials = []
    next_token = None
    page = 0
    while page < max_pages:
        params = {
            "query.cond": condition,
            "pageSize": 200,
            "format": "json",
            "fields": "NCTId,BriefTitle,OverallStatus,Phase,StartDate,CompletionDate,Condition,InterventionName,InterventionType"
        }
        if next_token:
            params["pageToken"] = next_token
        try:
            resp = requests.get(BASE_URL, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            print(f"    Error fetching {condition} page {page}: {e}")
            break

        studies = data.get("studies", [])
        for s in studies:
            proto = s.get("protocolSection", {})
            id_mod = proto.get("identificationModule", {})
            status_mod = proto.get("statusModule", {})
            design_mod = proto.get("designModule", {})
            cond_mod = proto.get("conditionsModule", {})
            interv_mod = proto.get("armsInterventionsModule", {})

            nct = id_mod.get("nctId", "")
            title = id_mod.get("briefTitle", "")
            status = status_mod.get("overallStatus", "")
            phases = design_mod.get("phases", [])
            phase = "|".join(phases) if phases else "NA"
            start = status_mod.get("startDateStruct", {}).get("date", "")
            completion = status_mod.get("completionDateStruct", {}).get("date", "")
            conditions = cond_mod.get("conditions", [])
            interventions = interv_mod.get("interventions", [])

            drug_interventions = [
                iv.get("name", "") for iv in interventions
                if iv.get("type", "").upper() in ("DRUG", "BIOLOGICAL", "COMBINATION_PRODUCT")
            ]

            trials.append({
                "trialId": nct,
                "title": title,
                "status": status,
                "phase": phase,
                "startDate": start,
                "completionDate": completion,
                "conditions": "|".join(conditions),
                "interventions": "|".join(drug_interventions),
                "source": "ClinicalTrials.gov"
            })

        next_token = data.get("nextPageToken")
        page += 1
        if not next_token:
            break
        time.sleep(0.3)

    return trials

def fetch_all_trials():
    all_trials = {}
    for cond in CVD_CONDITIONS:
        print(f"  Fetching: {cond}")
        trials = fetch_trials_for_condition(cond, max_pages=5)
        for t in trials:
            if t["trialId"]:
                all_trials[t["trialId"]] = t
        print(f"    -> {len(trials)} fetched, {len(all_trials)} unique so far")
        time.sleep(0.5)
    return list(all_trials.values())

def save_tsv(trials):
    trials_file = os.path.join(OUT_DIR, "trials_new.tsv")
    with open(trials_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "trialId","title","status","phase","startDate","completionDate",
            "conditions","interventions","source"
        ], delimiter="\t")
        writer.writeheader()
        writer.writerows(trials)
    print(f"  Saved {len(trials)} trials to {trials_file}")

    cond_file = os.path.join(OUT_DIR, "trial_conditions.tsv")
    interv_file = os.path.join(OUT_DIR, "trial_interventions.tsv")
    with open(cond_file, "w", newline="", encoding="utf-8") as cf, \
         open(interv_file, "w", newline="", encoding="utf-8") as ivf:
        cw = csv.writer(cf, delimiter="\t")
        iw = csv.writer(ivf, delimiter="\t")
        cw.writerow(["trialId","condition"])
        iw.writerow(["trialId","intervention"])
        for t in trials:
            for cond in t["conditions"].split("|"):
                cond = cond.strip()
                if cond:
                    cw.writerow([t["trialId"], cond])
            for iv in t["interventions"].split("|"):
                iv = iv.strip()
                if iv:
                    iw.writerow([t["trialId"], iv])
    print(f"  Saved condition/intervention edge TSVs")
    return trials_file, cond_file, interv_file

if __name__ == "__main__":
    print("=== ClinicalTrials.gov Parser ===")
    trials = fetch_all_trials()
    print(f"Total unique trials: {len(trials)}")
    save_tsv(trials)
