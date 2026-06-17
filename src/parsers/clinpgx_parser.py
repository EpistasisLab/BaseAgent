"""
ClinPGx / PharmGKB parser for CardioKB
- Loads DrugLabel nodes (labelId)
- VARIANT_IN: (Variant)-[:VARIANT_IN {source:'ClinPGx'}]->(Gene) MATCH-only
- AFFECTS_RESPONSE_TO: (Gene)-[:AFFECTS_RESPONSE_TO {source:'ClinPGx'}]->(Drug)
- drugLabelAnnotatesGene: (DrugLabel)->(Gene)
- drugLabelDescribesDrug:  (DrugLabel)->(Drug)
Supports: --download --parse --load --all
"""
import argparse, csv, os, time, requests
from neo4j import GraphDatabase

NEO4J_URI = "bolt://localhost:7688"
OUT_DIR = "./data/processed/clinpgx"
os.makedirs(OUT_DIR, exist_ok=True)
CPIC_BASE = "https://api.cpicpgx.org/v1"

DRUG_LABELS_TSV = os.path.join(OUT_DIR, "drug_labels.tsv")
LABEL_GENE_TSV  = os.path.join(OUT_DIR, "label_gene_edges.tsv")
LABEL_DRUG_TSV  = os.path.join(OUT_DIR, "label_drug_edges.tsv")
VARIANT_IN_TSV  = os.path.join(OUT_DIR, "variant_in_gene_edges.tsv")
AFFECTS_TSV     = os.path.join(OUT_DIR, "affects_response_edges.tsv")


def fetch_all(endpoint, limit=500):
    out, off = [], 0
    while True:
        r = requests.get(f"{CPIC_BASE}{endpoint}",
                         params={"limit": limit, "offset": off}, timeout=30)
        data = r.json()
        if not isinstance(data, list) or not data: break
        out.extend(data)
        if len(data) < limit: break
        off += limit
        time.sleep(0.2)
    return out


def download():
    print("[clinpgx] download (CPIC API)")
    try:
        drugs = fetch_all("/drug")
        genes = fetch_all("/gene")
        pairs = fetch_all("/pair")
        guides = fetch_all("/guideline")
    except Exception as e:
        print(f"  CPIC API fetch failed: {e}  (keeping existing TSVs)")
        return
    # write drug labels (one per guideline)
    if guides:
        with open(DRUG_LABELS_TSV,"w",newline="") as f:
            w = csv.writer(f, delimiter="\t")
            w.writerow(["labelId","name","url","guidelineId","source"])
            for g in guides:
                gid = g.get("id")
                name = g.get("name","")
                pa = g.get("pharmgkbId") or f"PA{gid}"
                w.writerow([pa, name, f"https://www.clinpgx.org/guideline/{pa}", gid, "ClinPGx"])
        print(f"  wrote {DRUG_LABELS_TSV}")
    print(f"  fetched drugs={len(drugs)} genes={len(genes)} pairs={len(pairs)} guidelines={len(guides)}")


def parse():
    print("[clinpgx] parse - using existing TSVs (download yields curated label/gene/drug TSVs)")
    for p in [DRUG_LABELS_TSV, LABEL_GENE_TSV, LABEL_DRUG_TSV, VARIANT_IN_TSV, AFFECTS_TSV]:
        exists = "OK" if os.path.exists(p) else "MISSING"
        print(f"  {p}: {exists}")


def load():
    print("[clinpgx] load")
    drv = GraphDatabase.driver(NEO4J_URI, auth=None)
    with drv.session() as s:
        # 1. DrugLabel nodes
        labels = []
        if os.path.exists(DRUG_LABELS_TSV):
            with open(DRUG_LABELS_TSV) as f:
                for r in csv.DictReader(f, delimiter="\t"):
                    if r.get("labelId"):
                        labels.append(r)
        before = s.run("MATCH (n:DrugLabel) RETURN count(n) AS c").single()["c"]
        s.run("""
            UNWIND $rows AS r
            MERGE (l:DrugLabel {labelId: r.labelId})
            ON CREATE SET l.name=r.name, l.url=r.url, l.guidelineId=r.guidelineId, l.source=r.source
        """, rows=labels)
        after = s.run("MATCH (n:DrugLabel) RETURN count(n) AS c").single()["c"]
        print(f"  DrugLabel: {before} -> {after}  (+{after-before})")

        # 2. VARIANT_IN
        var_rows = []
        if os.path.exists(VARIANT_IN_TSV):
            with open(VARIANT_IN_TSV) as f:
                for r in csv.DictReader(f, delimiter="\t"):
                    if r.get("variantId") and r.get("geneSymbol"):
                        var_rows.append(r)
        before = s.run("MATCH ()-[r:VARIANT_IN]->() RETURN count(r) AS c").single()["c"]
        s.run("""
            UNWIND $rows AS r
            MATCH (v:Variant {variantId: r.variantId})
            MATCH (g:Gene   {geneSymbol: r.geneSymbol})
            MERGE (v)-[e:VARIANT_IN]->(g)
            ON CREATE SET e.source='ClinPGx'
            ON MATCH  SET e.source=coalesce(e.source,'ClinPGx')
        """, rows=var_rows)
        after = s.run("MATCH ()-[r:VARIANT_IN]->() RETURN count(r) AS c").single()["c"]
        print(f"  VARIANT_IN: {before} -> {after}  (+{after-before})  rows={len(var_rows)}")

        # 3. AFFECTS_RESPONSE_TO - need (commonName) drug match (case-insensitive)
        aff_rows = []
        if os.path.exists(AFFECTS_TSV):
            with open(AFFECTS_TSV) as f:
                for r in csv.DictReader(f, delimiter="\t"):
                    if r.get("geneSymbol") and r.get("drugName"):
                        aff_rows.append(r)
        # build drug name lookup
        dr_lookup = {row["nm"].lower(): row["nm"]
                     for row in s.run("MATCH (d:Drug) WHERE d.commonName IS NOT NULL "
                                      "RETURN d.commonName AS nm")
                     if row["nm"]}
        aff_resolved = []
        for r in aff_rows:
            nm = dr_lookup.get(r["drugName"].lower())
            if nm:
                aff_resolved.append({"geneSymbol": r["geneSymbol"],
                                     "drugName": nm,
                                     "cpiclevel": r.get("cpiclevel","")})
        before = s.run("MATCH ()-[r:AFFECTS_RESPONSE_TO]->() RETURN count(r) AS c").single()["c"]
        s.run("""
            UNWIND $rows AS r
            MATCH (g:Gene {geneSymbol: r.geneSymbol})
            MATCH (d:Drug {commonName: r.drugName})
            MERGE (g)-[e:AFFECTS_RESPONSE_TO]->(d)
            ON CREATE SET e.source='ClinPGx', e.cpiclevel=r.cpiclevel
            ON MATCH  SET e.source=coalesce(e.source,'ClinPGx')
        """, rows=aff_resolved)
        after = s.run("MATCH ()-[r:AFFECTS_RESPONSE_TO]->() RETURN count(r) AS c").single()["c"]
        print(f"  AFFECTS_RESPONSE_TO: {before} -> {after}  (+{after-before})  rows={len(aff_resolved)}")

        # 4. drugLabelAnnotatesGene
        lg_rows = []
        if os.path.exists(LABEL_GENE_TSV):
            with open(LABEL_GENE_TSV) as f:
                for r in csv.DictReader(f, delimiter="\t"):
                    if r.get("labelId") and r.get("geneSymbol"):
                        lg_rows.append(r)
        before = s.run("MATCH ()-[r:drugLabelAnnotatesGene]->() RETURN count(r) AS c").single()["c"]
        s.run("""
            UNWIND $rows AS r
            MATCH (l:DrugLabel {labelId: r.labelId})
            MATCH (g:Gene {geneSymbol: r.geneSymbol})
            MERGE (l)-[e:drugLabelAnnotatesGene]->(g)
            ON CREATE SET e.source='ClinPGx'
            ON MATCH  SET e.source=coalesce(e.source,'ClinPGx')
        """, rows=lg_rows)
        after = s.run("MATCH ()-[r:drugLabelAnnotatesGene]->() RETURN count(r) AS c").single()["c"]
        print(f"  drugLabelAnnotatesGene: {before} -> {after}  (+{after-before})  rows={len(lg_rows)}")

        # 5. drugLabelDescribesDrug
        ld_rows = []
        if os.path.exists(LABEL_DRUG_TSV):
            with open(LABEL_DRUG_TSV) as f:
                for r in csv.DictReader(f, delimiter="\t"):
                    if r.get("labelId") and r.get("drugName"):
                        ld_rows.append(r)
        ld_resolved = []
        for r in ld_rows:
            nm = dr_lookup.get(r["drugName"].lower())
            if nm:
                ld_resolved.append({"labelId": r["labelId"], "drugName": nm})
        before = s.run("MATCH ()-[r:drugLabelDescribesDrug]->() RETURN count(r) AS c").single()["c"]
        s.run("""
            UNWIND $rows AS r
            MATCH (l:DrugLabel {labelId: r.labelId})
            MATCH (d:Drug {commonName: r.drugName})
            MERGE (l)-[e:drugLabelDescribesDrug]->(d)
            ON CREATE SET e.source='ClinPGx'
            ON MATCH  SET e.source=coalesce(e.source,'ClinPGx')
        """, rows=ld_resolved)
        after = s.run("MATCH ()-[r:drugLabelDescribesDrug]->() RETURN count(r) AS c").single()["c"]
        print(f"  drugLabelDescribesDrug: {before} -> {after}  (+{after-before})  rows={len(ld_resolved)}")
    drv.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--download", action="store_true")
    ap.add_argument("--parse",    action="store_true")
    ap.add_argument("--load",     action="store_true")
    ap.add_argument("--all",      action="store_true")
    a = ap.parse_args()
    if a.all or a.download: download()
    if a.all or a.parse:    parse()
    if a.all or a.load:     load()
    if not any([a.all,a.download,a.parse,a.load]):
        print("usage: --download | --parse | --load | --all")
