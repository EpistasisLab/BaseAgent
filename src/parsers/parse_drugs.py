"""
CVD Drug Parser - DrugBank + CTD (Fixed)
"""
import pandas as pd
import gzip
import io

CVD_DISEASE_KEYWORDS = [
    "heart", "cardiac", "cardio", "coronary", "myocardial", "infarction",
    "atrial", "fibrillation", "arrhythmia", "hypertension", "stroke",
    "atherosclerosis", "arteriosclerosis", "vascular", "thrombosis",
    "embolism", "angina", "aortic", "ventricular", "cardiomyopathy",
    "pericarditis", "endocarditis", "peripheral artery", "deep vein",
    "pulmonary hypertension", "heart failure", "tachycardia", "bradycardia",
    "ischemic", "ischaemic", "aneurysm", "stenosis", "cerebrovascular",
    "platelet", "anticoagul", "antithrombotic", "thrombolytic",
    "lipid", "cholesterol", "statin", "fibrate", "antihypertensive",
    "diuretic", "antiarrhythm",
]

CVD_DRUG_KEYWORDS = [
    "statin", "pril", "sartan", "olol", "dipine", "thiazide",
    "warfarin", "heparin", "aspirin", "clopidogrel", "ticagrelor",
    "rivaroxaban", "apixaban", "dabigatran", "edoxaban",
    "digoxin", "amiodarone", "sotalol", "flecainide", "propafenone",
    "metoprolol", "atenolol", "carvedilol", "bisoprolol", "nebivolol",
    "amlodipine", "nifedipine", "diltiazem", "verapamil",
    "lisinopril", "enalapril", "ramipril", "captopril", "perindopril",
    "losartan", "valsartan", "irbesartan", "candesartan", "olmesartan",
    "furosemide", "spironolactone", "eplerenone", "hydrochlorothiazide",
    "nitroglycerin", "isosorbide", "hydralazine", "minoxidil",
    "simvastatin", "atorvastatin", "rosuvastatin", "pravastatin",
    "lovastatin", "fluvastatin", "pitavastatin",
    "ezetimibe", "evolocumab", "alirocumab", "inclisiran",
    "fenofibrate", "gemfibrozil", "niacin", "omega-3",
    "alteplase", "streptokinase", "urokinase", "tenecteplase",
    "enoxaparin", "fondaparinux", "bivalirudin", "argatroban",
    "prasugrel", "cangrelor", "vorapaxar", "dipyridamole",
    "sacubitril", "ivabradine", "ranolazine", "milrinone", "dobutamine",
    "dopamine", "norepinephrine", "epinephrine", "vasopressin",
    "levosimendan", "nesiritide", "tolvaptan", "vericiguat",
    "dapagliflozin", "empagliflozin", "canagliflozin",
    "colchicine", "hydroxychloroquine",
]

def load_drugbank(path):
    print(f"Loading DrugBank vocabulary...")
    df = pd.read_csv(path, dtype=str)
    df.columns = [c.strip() for c in df.columns]
    result = pd.DataFrame({
        "drugBankId": df["DrugBank ID"].str.strip(),
        "commonName": df["Common name"].str.strip(),
        "casNumber":  df["CAS"].str.strip().fillna(""),
        "synonyms":   df["Synonyms"].fillna(""),
    })
    result["name_lower"] = result["commonName"].str.lower().str.strip()
    print(f"  Loaded {len(result)} DrugBank entries")
    return result

def load_ctd_cvd_chemicals(path):
    print(f"Loading CTD chemicals-diseases...")
    pattern = "|".join(CVD_DISEASE_KEYWORDS)
    
    with gzip.open(path, "rt", encoding="utf-8", errors="replace") as f:
        data_lines = [l for l in f if not l.startswith("#")]
    
    df_all = pd.read_csv(
        io.StringIO("".join(data_lines)), header=0,
        names=["ChemicalName","ChemicalID","CasRN","DiseaseName",
               "DiseaseID","DirectEvidence","InferenceGeneSymbol",
               "InferenceScore","OmimIDs","PubMedIDs"],
        dtype=str, low_memory=False
    )
    print(f"  Total rows: {len(df_all)}")
    
    mask = df_all["DiseaseName"].str.lower().str.contains(pattern, na=False, regex=True)
    df_cvd = df_all[mask].copy()
    print(f"  CVD rows: {len(df_cvd)}")
    
    unique_chems = df_cvd[["ChemicalName","ChemicalID","CasRN"]].drop_duplicates("ChemicalName").copy()
    unique_chems["name_lower"] = unique_chems["ChemicalName"].str.lower().str.strip()
    print(f"  Unique CVD chemicals: {len(unique_chems)}")
    return unique_chems

def load_ctd_master(path):
    print(f"Loading CTD chemicals master...")
    with gzip.open(path, "rt", encoding="utf-8", errors="replace") as f:
        data_lines = [l for l in f if not l.startswith("#")]
    
    df = pd.read_csv(
        io.StringIO("".join(data_lines)), header=0,
        names=["ChemicalName","ChemicalID","CasRN","PubChemCID","PubChemSID",
               "DTXSID","InChIKey","Definition","ParentIDs","TreeNumbers",
               "ParentTreeNumbers","MESHSynonyms","CTDCuratedSynonyms"],
        dtype=str, low_memory=False
    )
    df["name_lower"] = df["ChemicalName"].str.lower().str.strip()
    print(f"  Loaded {len(df)} CTD chemicals")
    return df

def build_drug_tsv(drugbank_df, ctd_cvd_df, ctd_master_df):
    print("\nBuilding merged drug dataset...")
    
    # Merge CTD CVD chemicals with CTD master for extra metadata
    ctd_enriched = ctd_cvd_df.merge(
        ctd_master_df[["name_lower","CasRN","MESHSynonyms"]].rename(
            columns={"CasRN":"CasRN_master","MESHSynonyms":"Synonyms_master"}),
        on="name_lower", how="left"
    )
    # Fill CasRN from master if missing
    ctd_enriched["CasRN"] = ctd_enriched["CasRN"].where(
        ctd_enriched["CasRN"].notna() & (ctd_enriched["CasRN"] != "nan"),
        ctd_enriched["CasRN_master"]
    )
    
    # Merge CTD CVD chemicals with DrugBank by name
    ctd_with_db = ctd_enriched.merge(
        drugbank_df[["name_lower","drugBankId","casNumber"]],
        on="name_lower", how="left"
    )
    
    # Build CAS lookup from DrugBank for fallback
    cas_to_dbid = drugbank_df[drugbank_df["casNumber"] != ""].set_index("casNumber")["drugBankId"].to_dict()
    
    seen_names = set()
    rows = []
    
    for _, row in ctd_with_db.iterrows():
        name = str(row["ChemicalName"]).strip()
        if not name or name.lower() in seen_names:
            continue
        seen_names.add(name.lower())
        
        db_id = str(row.get("drugBankId","")).strip()
        if db_id in ("nan",""):
            db_id = ""
        
        cas = str(row.get("CasRN","")).strip()
        if cas in ("nan",""):
            cas = str(row.get("casNumber","")).strip()
        if cas in ("nan",""):
            cas = ""
        
        # Try CAS lookup for DrugBank ID
        if not db_id and cas:
            db_id = cas_to_dbid.get(cas, "")
        
        mesh_id = str(row.get("ChemicalID","")).strip()
        if mesh_id == "nan":
            mesh_id = ""
        
        rows.append({
            "commonName": name,
            "drugBankId": db_id,
            "casNumber":  cas,
            "meshId":     mesh_id,
            "drugGroups": "",
            "source":     "DrugCentral+CTD",
        })
    
    # Add DrugBank CVD keyword drugs not already included
    db_cvd_mask = drugbank_df["commonName"].str.lower().apply(
        lambda x: any(kw in x for kw in CVD_DRUG_KEYWORDS)
    )
    db_cvd = drugbank_df[db_cvd_mask].copy()
    print(f"  DrugBank CVD keyword matches: {len(db_cvd)}")
    
    for _, row in db_cvd.iterrows():
        name = str(row["commonName"]).strip()
        if name.lower() in seen_names:
            continue
        seen_names.add(name.lower())
        rows.append({
            "commonName": name,
            "drugBankId": row["drugBankId"],
            "casNumber":  row["casNumber"],
            "meshId":     "",
            "drugGroups": "",
            "source":     "DrugCentral+CTD",
        })
    
    df_final = pd.DataFrame(rows)
    print(f"  Total unique drug records: {len(df_final)}")
    print(f"  With DrugBank ID: {(df_final['drugBankId'] != '').sum()}")
    print(f"  With CAS number:  {(df_final['casNumber'] != '').sum()}")
    print(f"  With MESH ID:     {(df_final['meshId'] != '').sum()}")
    return df_final

if __name__ == "__main__":
    drugbank_df  = load_drugbank("./data/processed/drugbank/drugbank_vocabulary.csv")
    ctd_cvd_df   = load_ctd_cvd_chemicals("./data/processed/ctd/CTD_chemicals_diseases.csv.gz")
    ctd_master_df = load_ctd_master("./data/processed/ctd/CTD_chemicals.csv.gz")
    
    df_final = build_drug_tsv(drugbank_df, ctd_cvd_df, ctd_master_df)
    
    out_path = "./data/processed/drugcentral/cvd_drugs_final.tsv"
    df_final.to_csv(out_path, sep="\t", index=False)
    print(f"\nSaved {len(df_final)} drug records to {out_path}")
    print(df_final.head(8).to_string())
