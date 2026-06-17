#!/usr/bin/env python3
"""Parse NCBI Homo_sapiens.gene_info.gz for protein-coding genes."""
import gzip, csv, sys, os

def main():
    inp, out_dir = sys.argv[1], sys.argv[2]
    os.makedirs(out_dir, exist_ok=True)
    rows = []
    with gzip.open(inp, "rt") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            if row["#tax_id"] != "9606": continue
            if row["type_of_gene"] != "protein-coding": continue
            symbol = row["Symbol"]
            if not symbol or symbol == "-": continue
            dbx = {}
            for x in row["dbXrefs"].split("|"):
                if ":" in x:
                    k, v = x.split(":", 1); dbx.setdefault(k, []).append(v)
            hgnc = dbx.get("HGNC", [""])[0].replace("HGNC:", "")
            rows.append({
                "geneSymbol": symbol,
                "ncbiGeneId": row["GeneID"],
                "name": row["description"],
                "chromosome": row["chromosome"],
                "geneType": row["type_of_gene"],
                "mapLocation": row["map_location"],
                "synonyms": row["Synonyms"] if row["Synonyms"] != "-" else "",
                "xrefHGNC": hgnc,
                "xrefEnsembl": dbx.get("Ensembl", [""])[0],
                "xrefOMIM": dbx.get("MIM", [""])[0],
                "source": "NCBIGene",
            })
    out = os.path.join(out_dir, "gene_nodes.tsv")
    with open(out, "w") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()), delimiter="\t")
        w.writeheader(); w.writerows(rows)
    print(f"Wrote {len(rows)} gene nodes -> {out}")

if __name__ == "__main__":
    main()
