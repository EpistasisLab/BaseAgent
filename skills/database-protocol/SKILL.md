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

## Database-Specific Operational References
Read these when working with the source, or when writing/debugging the parser. They cover source-specific details like file formats, node/edge types, identifier namespaces, cross-references, and gotchas.

- **NCBI Gene** (FTP) - [references/ncbigene.md](references/ncbigene.md)

- **UBERON** (OBO, public) - [references/uberon.md](references/uberon.md)

- **Bgee** (FTP) - [references/bgee.md](references/bgee.md)

- **AOP-DB** (MySQL) - [references/aopdb.md](references/aopdb.md)

- **DrugCentral** (PostgreSQL):
  - [references/drugcentral_eval.json](references/drugcentral_eval.json)
  - [references/drugcentral.md](references/drugcentral.md)

- **DrugBank** (HTTP download, academic account required) - [references/drugbank.md](references/drugbank.md)

- **Gene Ontology** (OBO + GAF, public) - [references/gene_ontology.md](references/gene_ontology.md)

- **MeSH** (XML, public) - [references/mesh.md](references/mesh.md)

- **CollectTRI** (OmniPath REST API, public) - [references/collectri.md](references/collectri.md)

- **BindingDB** (bulk TSV download, public) - [references/bindingdb.md](references/bindingdb.md)

- **Evolutionary Rate Covariation** (Dryad RDS, public; bot-protected download) - [references/evolutionary_rate_covariation.md](references/evolutionary_rate_covariation.md)

- **CTD Chemical** (bulk TSV, public) - [references/ctd_chemical.md](references/ctd_chemical.md)

- **CTD Exposure** (bulk TSV, public) - [references/ctd_exposure.md](references/ctd_exposure.md)

- **Reactome** (TSV, public) - [references/reactome.md](references/reactome.md)

- **Disease Ontology** (OBO, public) - [references/disease_ontology.md](references/disease_ontology.md)

- **MEDLINE** (NCBI E-utilities via EDirect CLI; optional API key) - [references/medline.md](references/medline.md)

- **SIDER** (bulk gzip TSV, public; static SIDER 4.1 release) - [references/sider.md](references/sider.md)
