#!/usr/bin/env python3
"""
Parser for CTD Chemicals (CTD_chemicals.csv.gz).
Filters to cardiovascular-relevant drugs using keyword and MeSH tree matching.
Output TSV columns: commonName, drugBankId, casNumber, meshId, source
"""

import gzip
import urllib.request
import os
import csv

URL = "https://ctdbase.org/reports/CTD_chemicals.csv.gz"
OUTPUT_TSV = "./data/processed/ctd/drugs.tsv"

CVD_DRUG_KEYWORDS = [
    "captopril", "enalapril", "lisinopril", "ramipril", "perindopril",
    "benazepril", "fosinopril", "quinapril", "trandolapril", "moexipril",
    "losartan", "valsartan", "irbesartan", "candesartan", "olmesartan",
    "telmisartan", "eprosartan", "azilsartan", "sacubitril", "aliskiren",
    "metoprolol", "carvedilol", "bisoprolol", "atenolol", "propranolol",
    "nebivolol", "labetalol", "nadolol", "timolol", "acebutolol",
    "betaxolol", "pindolol", "sotalol", "esmolol",
    "amlodipine", "nifedipine", "diltiazem", "verapamil", "felodipine",
    "nicardipine", "isradipine", "nimodipine", "nisoldipine", "clevidipine",
    "furosemide", "hydrochlorothiazide", "chlorthalidone", "spironolactone",
    "eplerenone", "torsemide", "bumetanide", "amiloride", "triamterene",
    "indapamide", "metolazone", "finerenone",
    "atorvastatin", "rosuvastatin", "simvastatin", "pravastatin",
    "lovastatin", "fluvastatin", "pitavastatin", "cerivastatin",
    "ezetimibe", "evolocumab", "alirocumab", "inclisiran",
    "fenofibrate", "gemfibrozil", "cholestyramine", "colesevelam", "colestipol",
    "lomitapide", "mipomersen", "bempedoic",
    "warfarin", "heparin", "enoxaparin", "fondaparinux",
    "dabigatran", "rivaroxaban", "apixaban", "edoxaban", "betrixaban",
    "clopidogrel", "prasugrel", "ticagrelor", "ticlopidine",
    "aspirin", "dipyridamole", "cilostazol",
    "bivalirudin", "argatroban", "lepirudin",
    "alteplase", "tenecteplase", "reteplase", "streptokinase",
    "abciximab", "eptifibatide", "tirofiban",
    "dalteparin", "tinzaparin", "nadroparin", "cangrelor", "vorapaxar",
    "digoxin", "digitoxin", "dobutamine", "dopamine", "milrinone",
    "ivabradine", "levosimendan", "nesiritide", "tolvaptan",
    "vericiguat", "empagliflozin", "dapagliflozin", "canagliflozin",
    "amiodarone", "dronedarone", "flecainide", "propafenone",
    "lidocaine", "mexiletine", "quinidine", "procainamide",
    "disopyramide", "dofetilide", "ibutilide",
    "adenosine", "atropine", "vernakalant",
    "nitroglycerin", "isosorbide", "hydralazine", "minoxidil",
    "nitroprusside", "sildenafil", "tadalafil", "riociguat",
    "bosentan", "ambrisentan", "macitentan",
    "iloprost", "epoprostenol", "treprostinil", "selexipag",
    "ranolazine", "trimetazidine", "perhexiline", "nicorandil",
    "colchicine", "canakinumab",
    "semaglutide", "liraglutide", "dulaglutide", "exenatide",
    "epinephrine", "norepinephrine", "vasopressin", "phenylephrine",
    "idarucizumab", "andexanet",
    "icosapentaenoic", "eicosapentaenoic",
    "lercanidipine", "lacidipine", "nitrendipine", "gallopamil",
    "bepridil", "fasudil", "pimobendan",
    "indobufen", "triflusal", "beraprost", "alprostadil",
    "sitaxentan", "darusentan", "tezosentan", "finerenone",
    "antihypertensive", "vasodilat", "cardiotonic", "antiarrhythm",
    "anticoagul", "antiplatelet", "thrombolyt", "hypolipidemic",
    "antilipemic", "lipid-lower", "diuretic",
    "calcium channel block", "ace inhibitor", "angiotensin",
    "beta-block", "beta blocker", "adrenergic beta",
    "cardiac glycoside", "inotropic",
]

FIELDNAMES = ["ChemicalName","ChemicalID","CasRN","PubChemCID","PubChemSID",
              "DTXSID","InChIKey","Definition","ParentIDs","TreeNumbers",
              "ParentTreeNumbers","MESHSynonyms","CTDCuratedSynonyms"]

def is_cvd_drug(name, synonyms, tree_numbers, definition):
    text = (name + " " + synonyms + " " + definition).lower()
    for kw in CVD_DRUG_KEYWORDS:
        if kw in text:
            return True
    for tn in tree_numbers.split("|"):
        if tn.strip().startswith("D27.505.954.122"):
            return True
    return False

def main():
    os.makedirs(os.path.dirname(OUTPUT_TSV), exist_ok=True)
    print(f"Downloading CTD chemicals from: {URL}")
    local_gz = "/tmp/CTD_chemicals.csv.gz"
    urllib.request.urlretrieve(URL, local_gz)
    print("Download complete")

    records = []
    total = 0

    with gzip.open(local_gz, "rt", encoding="utf-8") as f:
        for line in f:
            if line.startswith("#"):
                continue
            total += 1
            parts = next(csv.reader([line.strip()]))
            if len(parts) < 13:
                parts += [""] * (13 - len(parts))
            row = dict(zip(FIELDNAMES, parts))
            name      = row["ChemicalName"].strip()
            cas       = row["CasRN"].strip()
            mesh_id   = row["ChemicalID"].strip()
            synonyms  = row["MESHSynonyms"].strip() + " " + row["CTDCuratedSynonyms"].strip()
            tree_nums = row["TreeNumbers"].strip()
            defn      = row["Definition"].strip()
            if is_cvd_drug(name, synonyms, tree_nums, defn):
                records.append({"commonName": name, "drugBankId": "",
                                 "casNumber": cas, "meshId": mesh_id, "source": "CTD"})

    print(f"Total chemicals in CTD: {total:,}")
    seen = set()
    deduped = []
    for r in records:
        key = r["commonName"].lower()
        if key not in seen:
            seen.add(key)
            deduped.append(r)

    with open(OUTPUT_TSV, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["commonName","drugBankId","casNumber","meshId","source"], delimiter="\t")
        writer.writeheader()
        for rec in deduped:
            writer.writerow(rec)

    print(f"Wrote {len(deduped)} drug records to: {OUTPUT_TSV}")

if __name__ == "__main__":
    main()
