#!/usr/bin/env python3
"""
Foundation Agent Data Validation Script
Verifies integrity of core anchor nodes: Gene, Disease, Drug
Run this script to confirm the foundation data is intact before
downstream agents begin loading relationships.

Usage:
    python3 ./src/parsers/validate_foundation.py

Memgraph URI: bolt://localhost:7688
"""

from neo4j import GraphDatabase
import sys

URI  = "bolt://localhost:7688"
PASS = "\033[92m  ✓\033[0m"
FAIL = "\033[91m  ✗\033[0m"

def check(label, actual, expected_min, expected_max=None):
    if expected_max is None:
        expected_max = expected_min * 2
    ok = expected_min <= actual <= expected_max
    status = PASS if ok else FAIL
    print(f"{status} {label}: {actual}"
          + (f" (expected ≥{expected_min})" if not ok else ""))
    return ok

def main():
    print("=" * 60)
    print("  FOUNDATION AGENT — DATA VALIDATION")
    print("=" * 60)

    driver = GraphDatabase.driver(URI, auth=None)
    failures = 0

    with driver.session() as session:

        # ── Node counts ────────────────────────────────────────────
        print("\n[1] Node Counts")
        counts = {
            "Disease": session.run("MATCH (d:Disease) RETURN count(d) AS c").single()["c"],
            "Gene":    session.run("MATCH (g:Gene)    RETURN count(g) AS c").single()["c"],
            "Drug":    session.run("MATCH (d:Drug)    RETURN count(d) AS c").single()["c"],
            "Species": session.run("MATCH (s:Species) RETURN count(s) AS c").single()["c"],
        }
        if not check("Disease nodes",  counts["Disease"], 700):   failures += 1
        if not check("Gene nodes",     counts["Gene"],    600):   failures += 1
        if not check("Drug nodes",     counts["Drug"],    2800):  failures += 1
        if not check("Species nodes",  counts["Species"], 1, 1):  failures += 1

        # ── Relationship counts ────────────────────────────────────
        print("\n[2] Relationship Counts")
        gis = session.run("MATCH ()-[r:geneInSpecies]->() RETURN count(r) AS c").single()["c"]
        isa = session.run("MATCH ()-[r:is_a]->() RETURN count(r) AS c").single()["c"]
        if not check("geneInSpecies relationships", gis, 600):  failures += 1
        if not check("is_a relationships",          isa, 700):  failures += 1

        # ── Source property on all relationships ───────────────────
        print("\n[3] Source Property on Relationships")
        gis_src = session.run(
            "MATCH ()-[r:geneInSpecies]->() WHERE r.source IS NOT NULL RETURN count(r) AS c"
        ).single()["c"]
        isa_src = session.run(
            "MATCH ()-[r:is_a]->() WHERE r.source IS NOT NULL RETURN count(r) AS c"
        ).single()["c"]
        if not check("geneInSpecies with source", gis_src, gis, gis): failures += 1
        if not check("is_a with source",          isa_src, isa, isa): failures += 1

        # ── Disease node properties ────────────────────────────────
        print("\n[4] Disease Node Properties")
        d = counts["Disease"]
        checks = [
            ("Disease.xrefDiseaseOntology (100%)",
             "MATCH (d:Disease) WHERE d.xrefDiseaseOntology STARTS WITH \'DOID:\' RETURN count(d) AS c",
             d, d),
            ("Disease.diseaseName (100%)",
             "MATCH (d:Disease) WHERE d.diseaseName <> \'\'  RETURN count(d) AS c",
             d, d),
            ("Disease.source = DiseaseOntology (100%)",
             "MATCH (d:Disease) WHERE d.source = \'DiseaseOntology\' RETURN count(d) AS c",
             d, d),
            ("Disease.xrefMeSH (≥35%)",
             "MATCH (d:Disease) WHERE d.xrefMeSH IS NOT NULL RETURN count(d) AS c",
             int(d*0.35), d),
            ("Disease.xrefOMIM (≥30%)",
             "MATCH (d:Disease) WHERE d.xrefOMIM IS NOT NULL RETURN count(d) AS c",
             int(d*0.30), d),
            ("Disease.xrefICD10 (≥35%)",
             "MATCH (d:Disease) WHERE d.xrefICD10 IS NOT NULL RETURN count(d) AS c",
             int(d*0.35), d),
        ]
        for label, query, mn, mx in checks:
            val = session.run(query).single()["c"]
            if not check(label, val, mn, mx): failures += 1

        # ── Gene node properties ───────────────────────────────────
        print("\n[5] Gene Node Properties")
        g = counts["Gene"]
        gene_checks = [
            ("Gene.geneSymbol (100%)",
             "MATCH (g:Gene) WHERE g.geneSymbol IS NOT NULL RETURN count(g) AS c", g, g),
            ("Gene.ncbiGeneId (100%)",
             "MATCH (g:Gene) WHERE g.ncbiGeneId IS NOT NULL RETURN count(g) AS c", g, g),
            ("Gene.chromosome (100%)",
             "MATCH (g:Gene) WHERE g.chromosome <> \'\'    RETURN count(g) AS c", g, g),
            ("Gene.xrefHGNC (100%)",
             "MATCH (g:Gene) WHERE g.xrefHGNC <> \'\' RETURN count(g) AS c", g, g),
            ("Gene.xrefEnsembl (100%)",
             "MATCH (g:Gene) WHERE g.xrefEnsembl <> \'\'   RETURN count(g) AS c", g, g),
            ("Gene.geneAliases (≥90%)",
             "MATCH (g:Gene) WHERE g.geneAliases IS NOT NULL AND g.geneAliases <> \'\'  RETURN count(g) AS c",
             int(g*0.90), g),
        ]
        for label, query, mn, mx in gene_checks:
            val = session.run(query).single()["c"]
            if not check(label, val, mn, mx): failures += 1

        # ── Drug node properties ───────────────────────────────────
        print("\n[6] Drug Node Properties")
        dr = counts["Drug"]
        drug_checks = [
            ("Drug.commonName (100%)",
             "MATCH (d:Drug) WHERE d.commonName IS NOT NULL AND d.commonName <> \'\'  RETURN count(d) AS c",
             dr, dr),
            ("Drug.meshId (100%)",
             "MATCH (d:Drug) WHERE d.meshId STARTS WITH \'MESH:\' RETURN count(d) AS c",
             dr, dr),
            ("Drug.source = CTD (100%)",
             "MATCH (d:Drug) WHERE d.source = \'CTD\' RETURN count(d) AS c", dr, dr),
            ("Drug.casNumber (≥55%)",
             "MATCH (d:Drug) WHERE d.casNumber <> \'\'   RETURN count(d) AS c",
             int(dr*0.55), dr),
            ("Drug.drugBankId (≥8%)",
             "MATCH (d:Drug) WHERE d.drugBankId <> \'\'  RETURN count(d) AS c",
             int(dr*0.08), dr),
            ("Drug.drugAliases (≥85%)",
             "MATCH (d:Drug) WHERE d.drugAliases IS NOT NULL AND d.drugAliases <> \'\'  RETURN count(d) AS c",
             int(dr*0.85), dr),
        ]
        for label, query, mn, mx in drug_checks:
            val = session.run(query).single()["c"]
            if not check(label, val, mn, mx): failures += 1

        # ── Key node spot checks ───────────────────────────────────
        print("\n[7] Key Node Spot Checks")
        key_genes    = ["ACE", "APOE", "MYH7", "SCN5A", "LDLR", "PCSK9", "KCNQ1", "TNF", "VEGFA"]
        key_diseases = ["DOID:0060319", "DOID:0050650", "DOID:14557", "DOID:1287"]
        key_drugs    = ["Warfarin", "Aspirin", "Atorvastatin", "Metoprolol",
                        "Clopidogrel", "Evolocumab", "Empagliflozin"]

        for sym in key_genes:
            r = session.run("MATCH (g:Gene {geneSymbol: $s}) RETURN count(g) AS c", s=sym).single()["c"]
            if not check(f"Gene:{sym}", r, 1, 1): failures += 1

        for doid in key_diseases:
            r = session.run("MATCH (d:Disease {xrefDiseaseOntology: $d}) RETURN count(d) AS c", d=doid).single()["c"]
            if not check(f"Disease:{doid}", r, 1, 1): failures += 1

        for drug in key_drugs:
            r = session.run("MATCH (d:Drug {commonName: $n}) RETURN count(d) AS c", n=drug).single()["c"]
            if not check(f"Drug:{drug}", r, 1, 1): failures += 1

        # ── Index checks ───────────────────────────────────────────
        print("\n[8] Index Checks")
        required_indexes = [
            ("Disease", "xrefDiseaseOntology"),
            ("Gene",    "geneSymbol"),
            ("Gene",    "ncbiGeneId"),
            ("Drug",    "commonName"),
            ("Drug",    "drugBankId"),
            ("Species", "taxId"),
        ]
        idx_rows = session.run("SHOW INDEX INFO").data()
        active = {(r["label"], r["property"][0] if isinstance(r["property"], list) else r["property"])
                  for r in idx_rows if r["count"] > 0}
        for label, prop in required_indexes:
            ok = (label, prop) in active
            status = PASS if ok else FAIL
            print(f"{status} INDEX :{label}({prop})")
            if not ok: failures += 1

    driver.close()

    # ── Summary ────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    if failures == 0:
        print("\033[92m  ALL CHECKS PASSED — Foundation data is intact\033[0m")
    else:
        print(f"\033[91m  {failures} CHECK(S) FAILED — Review above output\033[0m")
    print("=" * 60)
    sys.exit(0 if failures == 0 else 1)

if __name__ == "__main__":
    main()
