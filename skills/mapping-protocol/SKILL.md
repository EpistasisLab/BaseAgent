---
name: mapping-protocol
description: Use when adding, modifying, or fixing entries in src/ontology_configs.py. Maps parser TSV output columns to Memgraph node types, data properties, and relationship types. Covers config entry format, node and relationship entry schemas, the source_label requirement, merge semantics, filter patterns, skip flag, and pre-flight validation. Requires reading ontology/schema/node_types.txt and edge_types.txt to confirm valid names before writing entries. Does not modify the OWL RDF file or parser Python files.
---

You own `src/ontology_configs.py`. You map parsed TSV columns to graph node/relationship types and properties so the Memgraph loader can create nodes and relationships.

**Strict constraints**:
- Only use node type names that appear in `ontology/schema/node_types.txt` and relationship type names in `ontology/schema/edge_types.txt`.
- Every relationship config must include a `source_label` field naming the source database (e.g., `'source_label': 'OpenTargets'`). The loader sets this as `r.source` on every relationship.
- If a required class or relationship type is absent from the schema files, stop and report the missing name. Do not propose changes to the RDF.
- Never edit parser Python files or the OWL RDF file.

---

## Pre-Editing Checklist

Before writing any entry:
1. Read `ontology/schema/node_types.txt` to confirm the node type is valid.
2. Read `ontology/schema/edge_types.txt` to confirm the relationship type is valid.
3. Read `data/processed/<source>/<output>.tsv` (header) to confirm TSV column names.
4. Verify property names by checking existing entries in `src/ontology_configs.py` that reference the same node type.

---

## Config Entry Format

`src/ontology_configs.py` contains 86 entries in the `ONTOLOGY_CONFIGS` dict. Keys use `{source_name}.{output_name}`:
- `source_name` must match the `src/main.py` PARSERS dict key and the `data/processed/<source_name>/` subdirectory.
- `output_name` must match the TSV filename stem (without `.tsv`).

Example: `'opentargets.gene_disease_associations'` → `data/processed/opentargets/gene_disease_associations.tsv`.

---

## Node Entry Schema

```python
'source.output_name': {
    'data_type': 'node',
    'node_type': 'Gene',                    # Must match ontology/schema/node_types.txt
    'source_filename': 'output_name.tsv',
    'merge_column': 'geneSymbol',           # Primary key for MERGE
    'data_property_map': {
        'geneSymbol': 'geneSymbol',         # TSV column → graph property
        'description': 'description',
    },
}
```

## Relationship Entry Schema

```python
'source.output_name': {
    'data_type': 'relationship',
    'relationship_type': 'geneAssociatesWithDisease',  # Must match edge_types.txt
    'source_label': 'OpenTargets',                     # REQUIRED — sets r.source
    'source_filename': 'output_name.tsv',
    'subject_node_type': 'Gene',
    'subject_merge_column': 'geneSymbol',
    'object_node_type': 'Disease',
    'object_merge_column': 'xrefDiseaseOntology',
    'data_property_map': {                             # Optional edge properties
        'score': 'score',
    },
}
```

---

## Critical Rules

1. **source_label is mandatory** on every relationship entry. The loader (`src/memgraph_loader.py`) sets `r.source` from this field.
2. **Node entries should be processed before relationships** — the loader MATCHes existing nodes when creating relationships. If the subject/object node doesn't exist, the relationship is silently skipped.
3. **skip flag** — Use `'skip': True` for planned but unimplemented entries.

---

## Current Source Labels (21)

`Bgee`, `BindingDB`, `CTD`, `ClinPGx`, `ClinVar`, `ClinicalTrials.gov`, `Disease Ontology`, `DoRothEA`, `DrugBank`, `DrugCentral`, `Gene Ontology`, `HGNC`, `HPO`, `Jensen TISSUES`, `LINCS L1000`, `MEDLINE`, `OpenTargets`, `PubTator`, `Reactome`, `SIDER`, `STRING`
