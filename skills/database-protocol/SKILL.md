---
name: database-protocol
description: Use when evaluating a new biomedical data source (producing a structured report on access method, formats, node/relationship types, and update schedule), or when enabling/disabling sources in config/databases.yaml. Covers the databases.yaml entry format, credential injection via the _env convention, and the checklist for safely enabling a new source. Does not implement parsers or manage ontology mappings.
---

You manage `config/databases.yaml`. Two workflows: **evaluate** a new data source, or **enable/disable** an existing one.

---

## Evaluating a New Data Source

Produce a structured JSON report. Use the `biomedical-database-advisor` agent for research if needed.

```json
{
  "database_evaluation": {
    "access_method": {
      "methods": ["RESTful API"],
      "requirements_and_restrictions": ["API key required", "rate limits"],
      "locations": ["https://api.example.org/v1/"]
    },
    "file_formats": {
      "supported_formats": ["JSON", "TSV"],
      "notes": "Bulk download in TSV; API responses in JSON"
    },
    "currency_and_update_schedule": {
      "last_known_update_date": "YYYY-MM",
      "update_frequency": ["quarterly"],
      "update_logs_available": true
    },
    "node_types": {
      "names": ["Gene", "Disease"],
      "primary_identifiers_and_nomenclature": ["Entrez Gene IDs", "UMLS CUIs"]
    },
    "relationship_types": {
      "format": "subjectVerbObject",
      "names": ["geneAssociatesWithDisease"],
      "origins": ["curated", "text-mined"],
      "metadata": ["confidence scores", "evidence levels"]
    }
  }
}
```

---

## Enabling a New Source

Before setting `enabled: true`:
1. Confirm a parser class exists for this source in `src/parsers/` and is registered in `src/main.py` `PARSERS`.
2. Confirm all required credentials are present in `.env` (see Environment Variables table in `docs/reference.md`).
3. Add the source entry to `databases.yaml` if it is not already there.
4. Add `ontology_mappings.yaml` entries for the parser's TSV outputs — node entries before relationship entries.
5. Register the parser in `PARSER_CLASS_MAP` in `src/main.py` with key equal to the `databases.yaml` key (= `data/processed/` subdirectory name).
6. Activate any new OWL class or object property names in `config/project.yaml` `node_types` / `edge_types`.

**Never delete entries** — set `enabled: false` to disable.

### databases.yaml Entry Format

```yaml
databases:
  <source_name>:                        # must match PARSERS key and ontology_mappings.yaml prefix
    enabled: true
    args:
      api_key_env: MY_API_KEY           # _env: read from environment; plain key: literal value
    notes: "What nodes/edges this source provides."
```

The `source_name` key controls the `data/processed/<source_name>/` directory and the `ontology_mappings.yaml` key prefix. Changing it breaks the pipeline.

### Credential Injection (`_env` Convention)

`_resolve_env_vars()` in `main.py` walks `args` recursively at startup:
- `api_key_env: MY_KEY` → `api_key: <value of $MY_KEY>` passed to parser constructor
- The `_env` suffix is stripped; the constructor must declare the stripped parameter name
- Works in nested dicts: `mysql_config: {user_env: MYSQL_USERNAME}` → `mysql_config: {user: <value>}`

**Critical**: if the environment variable is not set, the value resolves to `None` and a `WARNING` is logged at startup — there is no hard error. This silently breaks parsers that pass credentials to external clients (e.g., psycopg2 treats `None` as empty string and fails authentication). Only add `_env` keys for env vars that are guaranteed to be present.

**Source name vs. directory**: some parsers override `self.source_name` internally. This affects `data/raw/<source_name>/` paths but does NOT affect `data/processed/` — the processed subdirectory always uses the `databases.yaml` key. Use the `databases.yaml` key in both `PARSER_CLASS_MAP` and `ontology_mappings.yaml` prefix.

---

## Database-Specific References

- **NCBI Gene** (FTP):
  - [references/ncbigene.md](references/ncbigene.md) — operational reference (source file format, dbXrefs expansion, gotchas).

- **UBERON** (OBO, public):
  - [references/uberon.md](references/uberon.md) — operational reference (two-file OBO setup, term filtering criteria, xref prefixes, gotchas). Use this when understanding the human-slim filter, cross-referencing MeSH/FMA/BTO IDs, or debugging obonet parsing.

- **Bgee** (FTP):
  - [references/bgee.md](references/bgee.md) — operational reference (source file columns, anatomy ID prefixes, tissue_filter usage, gotchas). Use this when configuring the source URL, understanding UBERON vs. CL entries, or cross-referencing gene identifiers.

- **AOP-DB** (MySQL):
  - [references/aopdb.md](references/aopdb.md) — operational reference (setup, tables, processing, gotchas).

- **DrugCentral** (PostgreSQL):
  - [references/drugcentral_eval.json](references/drugcentral_eval.json) — structured evaluation artifact (node/relationship types, update schedule, parser output status). Use this for agent handoff or confirming what the database provides before writing mappings.
  - [references/drugcentral.md](references/drugcentral.md) — operational reference (setup, schema tables, inspect queries, known gotchas). Use this when installing, querying, or debugging the PostgreSQL instance.

- **DrugBank** (HTTP download, academic account required):
  - [references/drugbank.md](references/drugbank.md) — operational reference (setup, full XML structure, drug-links CSV columns, known gotchas). Use this when configuring credentials, understanding available fields, or debugging download/parse issues.

- **Gene Ontology** (OBO + GAF, public):
  - [references/gene_ontology.md](references/gene_ontology.md) — operational reference (two-file setup, OBO term fields, GAF 2.2 column layout, Entrez mapping dependency, gotchas). Use this when understanding BP/MF/CC namespace routing, GOA annotation filtering, or debugging the gene-symbol→Entrez dependency.

- **MeSH** (XML, public):
  - [references/mesh.md](references/mesh.md) — operational reference (year-based filename scheme, XML descriptor structure, C23.888 subtree filter, gotchas). Use this when updating the candidate year list, understanding tree number filtering, or debugging lxml streaming parse.

- **CollectTRI** (OmniPath REST API, public):
  - [references/collectri.md](references/collectri.md) — operational reference (OmniPath endpoint, TSV response columns, stimulation/inhibition flags, gotchas). Use this when understanding the databases.yaml key spelling, the genesymbols parameter, or cross-referencing TF symbols to Entrez IDs.

- **BindingDB** (bulk TSV download, public):
  - [references/bindingdb.md](references/bindingdb.md) — operational reference (monthly-stamped ZIP URL discovery, key TSV columns, human-target and DrugBank ID filters, gotchas). Use this when the fallback URL needs updating, adding affinity columns, or cross-referencing target names to gene identifiers.

- **Evolutionary Rate Covariation** (Dryad RDS, public; bot-protected download):
  - [references/evolutionary_rate_covariation.md](references/evolutionary_rate_covariation.md) — operational reference (Playwright + range-request download strategy, RDS matrix format, ft_threshold derivation, gotchas). Use this when the Dryad file_stream ID needs updating, understanding the Fisher-transformed score threshold, or debugging Playwright/pyreadr dependencies.

- **CTD Chemical** (bulk TSV, public):
  - [references/ctd_chemical.md](references/ctd_chemical.md) — operational reference (no-header gzip TSV, 11-column layout, InteractionActions pipe-token format, MeSH ID normalization, gotchas). Use this when understanding the expression action filter, the ChemicalID prefix normalization, or the multi-organism scope of the data.

- **Reactome** (TSV, public):
  - [references/reactome.md](references/reactome.md) — operational reference (two no-header TSV files, pathway ID format, all-levels hierarchical roll-up, species filter, gotchas). Use this when understanding the R-HSA- prefix, the all-levels redundancy in gene-pathway mappings, or the additional files that exist but are not loaded.

- **Disease Ontology** (OBO, public):
  - [references/disease_ontology.md](references/disease_ontology.md) — operational reference (OBO term fields, two-stage slim+scope filter, slim-terms.tsv generation via generate_disease_slim.py, xref prefixes, gotchas). Use this when regenerating the disease slim, understanding the UMLS_CUI prefix format, or diagnosing why terms are excluded by the scope or slim filters.

- **MEDLINE** (NCBI E-utilities via EDirect CLI; optional API key):
  - [references/medline.md](references/medline.md) — operational reference (EDirect install, two-phase PMID-fetch + Fisher stats algorithm, three output tables, prerequisites from disease_ontology/mesh/uberon parsers, gotchas). Use this when diagnosing missing EDirect tools, understanding the force-refresh PMID cache, or interpreting the per-relation-type corpus.

- **SIDER** (bulk gzip TSV, public; static SIDER 4.1 release):
  - [references/sider.md](references/sider.md) — operational reference (two-file setup, STITCH→PubChem CID conversion, PT filter, meddra inner join, cross-reference strategy against DrugCentral, gotchas). Use this when understanding why SIDER edges require DrugCentral to be enabled, debugging the STITCH ID format, or checking why side effects are dropped.
