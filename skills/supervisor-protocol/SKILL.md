---
name: supervisor-protocol
description: Use when coordinating across CardioKB pipeline modules — tracing config ownership, diagnosing silent failures, or integrating a new data source end-to-end. Covers the contracts that fail silently (source name consistency, TSV stems, column agreement, OWL name validity) and the new-source checklist.
---

## CardioKB Pipeline Data Flow

```
.env (credentials)
       ↓
   BaseParser (download + parse) → data/raw/<source>/
       ↓
   DataFrame dict → export_tsv → data/processed/<source>/<name>.tsv
       ↓
   src/memgraph_loader.py (reads src/ontology_configs.py) → Memgraph (bolt://localhost:7687)
```

---

## Config File Ownership

| File | Owner | Purpose |
|------|-------|---------|
| `ontology/cardiokb_ontology.rdf` | ontology_agent | OWL schema: classes, object/data properties, edgeSource annotations |
| `ontology/schema/node_types.txt` | ontology_agent | Canonical list of 17 node types |
| `ontology/schema/edge_types.txt` | ontology_agent | Canonical list of relationship types with source attribution |
| `src/ontology_configs.py` | mapping_agent | 86 entries mapping TSV columns → graph node/relationship types and properties |
| `src/main.py` | engineer_agent | Pipeline orchestrator, PARSERS dict, parser instantiation |
| `src/parsers/*.py` | engineer_agent | Parser implementations (inherit BaseParser) |
| `src/memgraph_loader.py` | (do not modify) | Cypher-based Memgraph batch loader |

---

## Cross-Module Contracts

These rules must hold for the pipeline to produce correct output. Violations fail silently.

**1. Source name consistency** — `src/main.py` PARSERS dict key = `src/ontology_configs.py` entry prefix = `data/processed/<source>/` subdirectory name. All three must be identical strings.

**2. TSV filename stems** — Keys in `parse_data()` return dict become TSV filename stems (e.g., key `"gene_disease"` → `gene_disease.tsv`). Each `source_filename` in `src/ontology_configs.py` must exactly match one of these stems + `.tsv`.

**3. Column name agreement** — Every column name referenced in `src/ontology_configs.py` (`data_property_map` keys, `merge_column`, `subject_merge_column`, `object_merge_column`) must appear as a column in the corresponding TSV.

**4. OWL name validity** — `node_type` and `relationship_type` values in `src/ontology_configs.py` must correspond to types defined in `ontology/cardiokb_ontology.rdf` and listed in `ontology/schema/node_types.txt` / `edge_types.txt`.

**5. source_label required** — Every relationship entry in `src/ontology_configs.py` must have a `source_label` field. The loader sets `r.source` from this.

---

## Known Silent Failures

| Symptom | Root cause |
|---------|------------|
| Zero edges for a source | Node not loaded before relationship references it |
| TSV not found at load time | Source name mismatch between main.py and ontology_configs.py |
| Relationship missing source property | `source_label` missing from ontology_configs.py entry |
| Credential silently None | Env var not set in `.env` |

---

## New Source Integration Checklist

1. Create parser class extending `BaseParser` in `src/parsers/<source>_parser.py`
2. Add import in `src/parsers/__init__.py`
3. Register in PARSERS dict in `src/main.py` and add instantiation in `create_parsers()`
4. Add credentials to `.env` if needed
5. Add entries to `src/ontology_configs.py` — node entries first, then relationships
6. Add OWL classes/properties to `ontology/cardiokb_ontology.rdf` if new types needed
7. Add types to `ontology/schema/node_types.txt` / `edge_types.txt`

Verify with: `python src/main.py --skip-neo4j` (parse only, no graph load)

Full pipeline: `python src/main.py`
