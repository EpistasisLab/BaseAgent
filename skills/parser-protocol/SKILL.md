---
name: parser-protocol
description: Use when creating a new parser or fixing/updating an existing parser under src/parsers/*.py in the CardioKB project. Covers the BaseParser contract, constructor patterns, registration in src/main.py and src/parsers/__init__.py, and verification via pipeline run. Parsers download biomedical source data and return clean pandas DataFrames.
---

You write, improve, and maintain parsers under `src/parsers/*.py` in the CardioKB project. A parser produces pandas DataFrames from one biomedical source.

## What a Parser Does

1. Downloads source data into `data/raw/<source_name>/`.
2. Returns one or more named DataFrames from those files.
3. The pipeline writes each DataFrame to `data/processed/<source_name>/<output_name>.tsv`.

The `src/ontology_configs.py` config references TSV stems and column names — choose them carefully.

---

## The `BaseParser` Contract

Inherit from `src/parsers/base_parser.py`. Implement these methods:

### `download_data() -> bool`
Download and cache source files. Return `True` if files are ready.

### `parse_data() -> dict[str, pd.DataFrame]`
Return `{output_name: df}`. Dict keys become TSV filename stems and must match the `source_filename` values in `src/ontology_configs.py`.

### `get_schema() -> dict[str, dict[str, str]]`
Return `{output_name: {col_name: description}}` matching every column in `parse_data()` output.

---

## BaseParser Helpers

| Method | Use for |
|--------|---------|
| `self.download_file(url, filename)` | Download a file; skips if cached |
| `self.extract_gzip(gz_path)` | Decompress `.gz` |
| `self.read_tsv(filepath, **kwargs)` | `pd.read_csv` with `sep="\t"` |
| `self.validate_data(df, required_columns)` | Check required columns |
| `self.get_file_path(filename)` | Absolute path under `self.source_dir` |

---

## Constructor Patterns

```python
class MySourceParser(BaseParser):
    def __init__(self, data_dir: str, my_param: str = None):
        super().__init__(data_dir)
        self.my_param = my_param
```

**Disease filtering** — for parsers that filter by disease terms:
```python
from src.utils import load_disease_terms, get_disease_search_pattern

def __init__(self, data_dir: str, disease_filter: str = None):
    super().__init__(data_dir)
    self.disease_terms = load_disease_terms(disease_filter or 'ontology/disease_filter.txt')
```

**Credentials** — never hard-code; use `.env` via `os.environ`:
```python
def __init__(self, data_dir: str, username: str = None, password: str = None):
    super().__init__(data_dir)
    self.username = username or os.environ.get('DRUGBANK_USERNAME')
```

---

## Registration Checklist

1. **`src/parsers/__init__.py`** — add the import
2. **`src/main.py`** — register in the PARSERS dict and add parser instantiation in the `create_parsers()` function
3. **`src/ontology_configs.py`** — add node and relationship config entries (mapping-protocol's responsibility)
4. **`ontology/cardiokb_ontology.rdf`** — add OWL classes/properties if new types (ontology-protocol's responsibility)

**Verify** by running:
```bash
python src/main.py --skip-neo4j  # Parse only, no graph load
```

---

## CardioKB's 24 Active Parsers

| Parser | Source | Access |
|--------|--------|--------|
| NCBIGeneParser | NCBI Gene | Public FTP |
| DiseaseOntologyParser | Disease Ontology | Public OBO |
| DrugBankParser | DrugBank | XML file |
| ClinicalTrialsParser | ClinicalTrials.gov | Public API v2 |
| ClinPGxParser | ClinPGx | Public API |
| DoRothEAParser | DoRothEA/OmniPath | Public API |
| ClinVarParser | ClinVar | Public FTP |
| HGNCFamiliesParser | HGNC Families | Public |
| GeneOntologyParser | Gene Ontology | Public OBO+GAF |
| UberonParser | Uberon | Public OBO |
| MeSHParser | MeSH | Public XML |
| SIDERParser | SIDER | Public (legacy) |
| LINCS1000Parser | LINCS L1000 | Public (legacy) |
| MEDLINECooccurrenceParser | MEDLINE | Public (legacy) |
| DrugCentralParser | DrugCentral | Public |
| BindingDBParser | BindingDB | Public TSV |
| PubTatorParser | PubTator Central | Public FTP |
| CTDParser | CTD | Public TSV |
| BgeeParser | Bgee | Public FTP |
| JensenTissuesParser | Jensen TISSUES | Public |
| HPOParser | HPO | Public OBO |
| ReactomeParser | Reactome | Public TSV |
| STRINGParser | STRING | Public |
| OpenTargetsParser | OpenTargets | Public |
