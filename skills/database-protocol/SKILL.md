---
name: database-protocol
description: Use when evaluating a new biomedical data source (producing a structured report on access method, formats, node/relationship types, and update schedule), or when enabling/disabling sources in the CardioKB pipeline. Covers the src/main.py PARSERS dict, credential patterns, and the checklist for safely enabling a new source. Does not implement parsers or manage ontology mappings.
---

You evaluate new data sources and manage source registration in the CardioKB pipeline.

---

## Evaluating a New Data Source

Produce a structured JSON report:

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

Before enabling a new source in the pipeline:

1. Confirm a parser class exists in `src/parsers/` and is imported in `src/parsers/__init__.py`.
2. Confirm the parser is registered in `src/main.py` PARSERS dict with instantiation in `create_parsers()`.
3. Confirm all required credentials are present in `.env`.
4. Confirm `src/ontology_configs.py` has entries for the parser's TSV outputs — node entries first, then relationship entries.
5. Confirm any new OWL classes or properties are defined in `ontology/cardiokb_ontology.rdf` and listed in `ontology/schema/node_types.txt` / `edge_types.txt`.

### Credential Patterns

CardioKB parsers read credentials directly from environment variables via `os.environ.get()`:
```python
self.username = username or os.environ.get('DRUGBANK_USERNAME')
self.password = password or os.environ.get('DRUGBANK_PASSWORD')
```

Credentials are stored in `.env` (not committed). Template in `.env.example`.

### Source Name Consistency

The following must all use the same string key:
- `src/main.py` PARSERS dict key
- `src/ontology_configs.py` entry prefix
- `data/processed/<source_name>/` subdirectory

Changing any one without updating the others breaks the pipeline silently.

---

## CardioKB's 24 Active Sources

| # | Source | Parser | Access |
|---|--------|--------|--------|
| 1 | ClinicalTrials.gov | ClinicalTrialsParser | Public API v2 |
| 2 | ClinPGx | ClinPGxParser | Public API |
| 3 | NCBI Gene | NCBIGeneParser | Public FTP |
| 4 | DoRothEA | DoRothEAParser | Public API |
| 5 | DrugBank | DrugBankParser | XML file |
| 6 | Disease Ontology | DiseaseOntologyParser | Public OBO |
| 7 | Gene Ontology | GeneOntologyParser | Public OBO+GAF |
| 8 | Uberon | UberonParser | Public OBO |
| 9 | MeSH | MeSHParser | Public XML |
| 10 | SIDER | SIDERParser | Public (legacy) |
| 11 | LINCS L1000 | LINCS1000Parser | Public (legacy) |
| 12 | MEDLINE | MEDLINECooccurrenceParser | Public (legacy) |
| 13 | DrugCentral | DrugCentralParser | Public |
| 14 | BindingDB | BindingDBParser | Public TSV |
| 15 | PubTator Central | PubTatorParser | Public FTP |
| 16 | CTD | CTDParser | Public TSV |
| 17 | Bgee | BgeeParser | Public FTP |
| 18 | Jensen TISSUES | JensenTissuesParser | Public |
| 19 | HPO | HPOParser | Public OBO |
| 20 | Reactome | ReactomeParser | Public TSV |
| 21 | STRING | STRINGParser | Public |
| 22 | OpenTargets | OpenTargetsParser | Public |
| 23 | HGNC Families | HGNCFamiliesParser | Public |
| 24 | ClinVar | ClinVarParser | Public FTP |
