# CTD Exposure (Comparative Toxicogenomics Database) Operational Reference

---

## Setup

No API key or account required. Files are direct bulk downloads.

---

## Source Files

### `CTD_exposure_studies.tsv.gz` — primary exposure-event associations

Gzipped TSV of curated epidemiological exposure-event associations. Lines beginning with `#` are comment/header lines and are skipped; the first non-comment line is the data (no explicit column header row).

**Download URL:**
```
http://ctdbase.org/reports/CTD_exposure_studies.tsv.gz
```

#### Columns (10 total)

| Column | Description |
|---|---|
| `PubmedID` | PubMed ID of the supporting study |
| `StudyFactors` | Pipe-separated covariates (e.g. `age\|sex`) |
| `Stressors` | Pipe-separated `Name^MeSH-ID^MESH` entries for chemical/environmental stressors |
| `Receptors` | Pipe-separated `Name^type^ID^Source^notes` entries; `type=gene` entries carry NCBI Gene IDs at position [2] |
| `Countries` | Countries where the study was conducted |
| `ExposureMedium` | Medium of exposure (e.g. air, water) |
| `ExposureMarkers` | Pipe-separated `Name^MeSH-ID^MESH` entries for measured chemicals |
| `Diseases` | Pipe-separated `Name^MeSH-ID^MESH` disease outcome entries |
| `GOTerms` | Pipe-separated `Name^GO:ID^GO` GO term associations |
| `StudyNotes` | Free-text notes |

### `CTD_chem_go_enriched.tsv.gz` — GO term namespace lookup

Used only to resolve GO term IDs to their namespace (Biological Process, Molecular Function, Cellular Component). Columns used: `Ontology`, `GOTermID`.

**Download URL:**
```
http://ctdbase.org/reports/CTD_chem_go_enriched.tsv.gz
```

---

## Output Tables

### `exposure_nodes`

Unique exposure (stressor) nodes derived from the `Stressors` column.

| Column | Description |
|---|---|
| `xrefMeSH` | MeSH ID of the stressor (e.g. `D007854`, `C004762`) |
| `commonName` | Stressor name |
| `source_database` | `"CTD"` |

### `exposure_linked_to_disease`

Cross-join of stressors × diseases per study row.

| Column | Description |
|---|---|
| `xrefMeSH` | Source stressor MeSH ID |
| `disease_id` | Target disease MeSH ID |
| `pubmedId` | PubMed ID of the supporting study |
| `source_database` | `"CTD"` |

### `exposure_interacts_with_gene`

Stressor–gene edges from `Receptors` entries with `type=gene`.

| Column | Description |
|---|---|
| `xrefMeSH` | Source stressor MeSH ID |
| `xrefNcbiGene` | Target NCBI Gene ID |
| `geneSymbol` | Gene symbol |
| `pubmedId` | PubMed ID of the supporting study |
| `source_database` | `"CTD"` |

### `exposure_interacts_with_biological_process` / `_molecular_function` / `_cellular_component`

GO-term edges split by namespace. All three share the same schema.

| Column | Description |
|---|---|
| `xrefMeSH` | Source stressor MeSH ID |
| `xrefGeneOntology` | Target GO term ID (e.g. `GO:0006954`) |
| `pubmedId` | PubMed ID of the supporting study |
| `source_database` | `"CTD"` |

---

## Known Gotchas

**No column header row** — the file uses `#`-prefixed comment lines; data rows have no header. The parser skips all `#` lines and assigns column names explicitly via `names=`. Do not use `header=0`.

**Pipe-and-caret encoding** — multi-valued fields (Stressors, Diseases, GOTerms, Receptors) are pipe-separated, and each entry is caret-delimited (`Name^ID^Source`). Each field must be split on `|` first, then on `^`.

**Stressors × Diseases is a cross-join** — a single study row may list multiple stressors and multiple diseases. The parser emits one edge per stressor–disease pair, so row counts in `exposure_linked_to_disease` will exceed the number of source rows.

**GO term namespace requires a second file** — GO term IDs in `CTD_exposure_studies.tsv.gz` carry no namespace. The parser resolves namespace via `CTD_chem_go_enriched.tsv.gz`. If that file is missing, all GO edges are skipped.

**`xrefMeSH` IDs are bare, without prefix** — the raw file contains just the code (e.g. `D007854`), not `MESH:D007854`. Joins against nodes that include a `MESH:` prefix will fail without normalization.

**URL uses `http://`, not `https://`** — the CTD download endpoints are unencrypted HTTP. Do not substitute `https://`.

**No versioned archive** — both URLs always serve the current monthly release. Record the download date for reproducibility.