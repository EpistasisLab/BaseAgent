#!/usr/bin/env python3
"""Parse CTD_chemicals.tsv.gz as drug source."""
import gzip, csv, sys, os

def main():
    inp, out_dir = sys.argv[1], sys.argv[2]
    os.makedirs(out_dir, exist_ok=True)
    rows = []; seen = set(); header = None
    with gzip.open(inp, "rt") as f:
        for line in f:
            if line.startswith("# Fields:"): continue
            if line.startswith("#"):
                if "ChemicalName" in line:
                    header = line.lstrip("#").strip().split("\t")
                continue
            if not header or not line.strip(): continue
            cols = line.rstrip("\n").split("\t")
            if len(cols) < len(header): cols += [""] * (len(header) - len(cols))
            rec = dict(zip(header, cols))
            name = rec["ChemicalName"].strip()
            if not name or name in seen: continue
            seen.add(name)
            cas = rec["CasRN"].strip(); pcid = rec.get("PubChemCID","").strip()
            # Filter: only cataloged compounds with CAS or PubChemCID
            if not (cas or pcid): continue
            rows.append({
                "commonName": name,
                "meshId": rec["ChemicalID"].strip(),
                "casNumber": cas,
                "pubchemCID": pcid,
                "inchiKey": rec.get("InChIKey","").strip(),
                "description": rec.get("Definition","").strip(),
                "synonyms": (rec.get("MESHSynonyms","") + ("|"+rec.get("CTDCuratedSynonyms","") if rec.get("CTDCuratedSynonyms","") else "")).strip("|"),
                "drugBankId": "",
                "source": "CTD",
            })
    out = os.path.join(out_dir, "drug_nodes.tsv")
    with open(out, "w") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()), delimiter="\t")
        w.writeheader(); w.writerows(rows)
    print(f"Wrote {len(rows)} drug nodes -> {out}")

if __name__ == "__main__":
    main()
