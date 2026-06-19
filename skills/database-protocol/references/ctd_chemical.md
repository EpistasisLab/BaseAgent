# CTD (Comparative Toxicogenomics Database) Operational Reference

---

## Setup

No API key or account required. The file is a direct bulk download.

**databases.yaml entry:**
```yaml
ctd:
  enabled: true
  args: {}
```

No `args` are needed; the download URL is a fixed constant in the parser.

---

## Source File

`CTD_chem_gene_ixns.tsv.gz` — gzipped TSV of all CTD chemical-gene interactions. Updated monthly. Lines beginning with `#` are comment/header lines and are skipped; the first non-comment line is the data (no explicit column header row in the file).

**Download URL:**
```
http://ctdbase.org/reports/CTD_chem_gene_ixns.tsv.gz
```

### Columns (11 total)

| Column | Description |
|---|---|
| `ChemicalName` | Chemical preferred name |
| `ChemicalID` | MeSH Descriptor UI without prefix (e.g. `D000082`); normalized to `MESH:D000082` by the parser |
| `CasRN` | CAS registry number (may be empty) |
| `GeneSymbol` | HGNC gene symbol |
| `GeneID` | NCBI Gene ID (Entrez) |
| `GeneForms` | Affected gene/protein forms, pipe-delimited (e.g. `mRNA\|protein`) |
| `Organism` | Organism name (e.g. `Homo sapiens`) |
| `OrganismID` | NCBI taxonomy ID (e.g. `9606` for human) |
| `Interaction` | Free-text description of the full interaction |
| `InteractionActions` | Pipe-delimited action tokens in `direction^process` format (see below) |
| `PubMedIDs` | Pipe-delimited PubMed IDs supporting the annotation |

### `InteractionActions` Token Format

Each token takes the form `direction^process`, where direction is `increases`, `decreases`, `affects`, or a more specific verb, and process describes what is affected. Multiple tokens may appear in one row, pipe-separated. Examples:

| Token | Meaning |
|---|---|
| `increases^expression` | Chemical increases gene expression |
| `decreases^expression` | Chemical decreases gene expression |
| `increases^mRNA expression` | Chemical increases mRNA specifically |
| `decreases^protein expression` | Chemical decreases protein level |
| `affects^binding` | Chemical affects binding (direction unspecified) |

The parser retains only tokens matching `\^expression` (case-insensitive substring), then further splits on `increases^` vs `decreases^` prefix.

---

## Known Gotchas

**No column header row** — the file uses `#`-prefixed comment lines (including a descriptive header block) but the data rows have no header. The parser skips all `#` lines and assigns column names explicitly. Do not rely on `header=0` when reading this file.

**`ChemicalID` is bare, without the `MESH:` prefix** — the raw file contains just the D-code (e.g. `D000082`), not `MESH:D000082`. The parser normalizes this before use. Joins against MeSH node IDs that include the prefix will fail without this normalization.

**`InteractionActions` is pipe-delimited and exploded** — a single source row may contain multiple action tokens (e.g. `increases^expression|increases^protein expression`). The parser explodes these into one row per token before filtering. Row counts will exceed the number of source records.

**Data is not human-specific** — `OrganismID` spans many taxa; the parser does not filter to human (`9606`) before building edge tables. The `organism` column is preserved in the output for downstream filtering if needed.

**URL uses `http://`, not `https://`** — the CTD download endpoint is unencrypted HTTP. This is intentional upstream; do not substitute `https://` as it may not be served on that scheme.

**No versioned archive** — the URL always serves the current monthly release. Record the download date for reproducibility.
