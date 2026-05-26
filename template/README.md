# Disease Knowledge Graph Pipeline

A pipeline for building a disease-specific knowledge graph — integrating data from biomedical databases, populating an OWL ontology, and exporting a Memgraph-compatible graph.

## Overview

The pipeline runs four steps in sequence:

```
1. Extract   — download and parse data from biomedical databases
2. Export TSV — save parsed DataFrames to data/processed/
3. Populate  — populate the OWL ontology using ista
4. Export graph — write Memgraph-compatible CSV files to data/output/
```

Configuration lives in `config/`:
- `project.yaml` — disease scope (search terms, UMLS CUIs, MeSH IDs, ontology paths)
- `databases.yaml` — which sources to enable and their access credentials
- `ontology_mappings.yaml` — how parsed columns map to ontology properties

## Installation

**Prerequisites:** Python 3.8+, MySQL (for AOP-DB), Git

```bash
git clone <your-repo-url>
cd <project-name>

python3 -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt

# Install ista (bundled in .ista/)
pip install -e .ista

# Install NCBI EDirect (required by the MEDLINE parser)
bash edirect/install-edirect.sh
export PATH="$(pwd)/edirect:${PATH}"   # add to ~/.bashrc or ~/.zshrc to persist
```

**Credentials** — create a `.env` file:
```bash
DISGENET_API_KEY=your_key_here
DRUGBANK_USERNAME=your_username
DRUGBANK_PASSWORD=your_password
DC_USER=drugman                    # DrugCentral public read-only account
DC_PASSWORD=dosage
MYSQL_USERNAME=root                # Only needed if running AOP-DB
MYSQL_PASSWORD=your_password
MYSQL_DB_NAME=aopdb
NCBI_EUTILS_API_KEY=your_key_here  # Optional; raises MEDLINE rate limit to 10 req/s
```

## Usage

```bash
# Full pipeline
python src/main.py

# Run a single pipeline step
python src/main.py --step extract   # download sources and write TSVs
python src/main.py --step populate  # load TSVs into the OWL ontology
python src/main.py --step export    # write Memgraph CSVs from the ontology

# Run and export a single source (useful for testing)
python src/main.py --source disgenet

# Verbose output
python src/main.py --log-level DEBUG

# Re-download source files even if they already exist
python src/main.py --force-download
```

Output files appear in `data/output/`:
- `ontology_populated.rdf` — populated OWL ontology
- `nodes_{NodeType}.csv` — one CSV per node type (Gene, Drug, Disease, …)
- `edges_{RelType}.csv` — one CSV per relationship type
- `import.cypher` — Cypher LOAD CSV script; paste into Memgraph Lab to load the graph

Logs are written to `kg_build.log`.

## Evaluation

Three scripts in `eval/` compute quality metrics at each pipeline stage. Run them from the disease KG directory after the corresponding pipeline step completes.

| Script | Run after | Required inputs |
|--------|-----------|-----------------|
| `eval_after_parser.py` | `--step extract` | `data/processed/<source>/*.tsv` |
| `eval_after_ontology.py` | `--step populate` | `data/ontology/ontology.rdf` + `data/output/ontology_populated.rdf` |
| `eval_after_memgraph.py` | `--step export` | `data/output/nodes_*.csv` + `data/output/edges_*.csv` |

```bash
# After extraction
python eval/eval_after_parser.py --output report_parser.json

# After ontology population
python eval/eval_after_ontology.py --output report_ontology.json

# After Memgraph export
python eval/eval_after_memgraph.py --output report_memgraph.json

# Optional Tier 3 inputs for eval_after_memgraph.py
python eval/eval_after_memgraph.py \
    --baseline prev_report.json \       # enables run-to-run entity count delta
    --omim-genemap genemap2.txt \       # enables disease-gene recall rate
    --drugbank-tsv drugbank_drugs.tsv \ # enables drug-target coverage
    --output report_memgraph.json
```

All scripts print JSON to stdout by default; use `--output` to save to a file.

## Interactive use (Jupyter)

Open `run_individual_components.ipynb` to run parsers one at a time. This is useful for debugging a specific source without running the full pipeline.

## Configuration

### Set disease scope

Edit `config/project.yaml`:
```yaml
project:
  disease_scope:
    primary_terms:
      - "<disease_term>"
    umls_cuis:
      - "<UMLS_CUI>"
```

### Enable a data source

Edit `config/databases.yaml`:
```yaml
disgenet:
  enabled: true          # change to false to skip
  args:
    api_key_env: DISGENET_API_KEY
```

## Adding a new data source

1. Create a parser in `src/parsers/`:

```python
from .base_parser import BaseParser

class MySourceParser(BaseParser):
    def download_data(self) -> bool:
        # download files to self.source_dir
        return True

    def parse_data(self) -> dict[str, pd.DataFrame]:
        # return {"table_name": dataframe, ...}
        return {}

    def get_schema(self) -> dict:
        return {}
```

2. Register it in `src/main.py`:

```python
PARSERS = {
    ...
    "mysource": MySourceParser,
}
```

3. Add an entry to `config/databases.yaml`:

```yaml
mysource:
  enabled: true
  args:
    api_key_env: MYSOURCE_API_KEY
  notes: "Brief description."
```

4. Add ontology mappings to `config/ontology_mappings.yaml`.

## Project structure

```
<project-name>/
├── config/
│   ├── project.yaml              # disease scope, ontology settings
│   ├── databases.yaml            # source databases and credentials
│   └── ontology_mappings.yaml    # column-to-ontology-property mappings
├── src/
│   ├── main.py                   # pipeline entry point (read this first)
│   ├── parsers/                  # source parsers
│   │   ├── base_parser.py
│   │   ├── aopdb_parser.py
│   │   ├── bgee_parser.py
│   │   ├── bindingdb_parser.py
│   │   ├── collecttri_parser.py
│   │   ├── ctd_parser.py
│   │   ├── disease_ontology_parser.py
│   │   ├── disgenet_parser.py
│   │   ├── dorothea_parser.py
│   │   ├── drugbank_parser.py
│   │   ├── drugcentral_parser.py
│   │   ├── evolutionary_rate_covariation.py
│   │   ├── gene_ontology_parser.py
│   │   ├── medline_parser.py
│   │   ├── mesh_parser.py
│   │   ├── ncbigene_parser.py
│   │   ├── reactome_parser.py
│   │   └── uberon_parser.py
│   ├── ontology/
│   │   └── populator.py          # OWL population via ista
│   └── export/
│       └── memgraph_exporter.py  # typed CSV export for Memgraph
├── data/
│   ├── raw/                      # downloaded source files
│   ├── processed/                # parsed TSV files (one folder per source)
│   ├── ontology/                 # base OWL ontology
│   └── output/                   # final outputs
├── eval/                            # eval_after_parser.py, eval_after_ontology.py, eval_after_memgraph.py
├── docs/                            # overview.md, reference.md
├── run_individual_components.ipynb  # run parsers interactively
├── run.sh                           # convenience wrapper
└── requirements.txt
```

## Data sources

| Source | Parser | Access | Enabled |
|--------|--------|--------|---------|
| AOP-DB | `AOPDBParser` | Local MySQL | No |
| Bgee | `BgeeParser` | HTTP download | Yes |
| BindingDB | `BindingDBParser` | HTTP download | Yes |
| CollectTRI | `CollectTRIParser` | OmniPath API | Yes |
| CTD | `CTDParser` | HTTP download | Yes |
| Disease Ontology | `DiseaseOntologyParser` | OBO file | Yes |
| DisGeNET | `DisGeNETParser` | REST API (key required) | Yes |
| DrugBank | `DrugBankParser` | HTTP download (credentials required) | Yes |
| DrugCentral | `DrugCentralParser` | Remote PostgreSQL (public credentials) | Yes |
| Evolutionary Rate Covariation | `EvolutionaryRateCovariationParser` | HTTP download (Dryad) | Yes |
| Gene Ontology | `GeneOntologyParser` | OBO file | Yes |
| MEDLINE | `MEDLINEParser` | NCBI E-utilities (PubMed) | Yes |
| MeSH | `MeSHParser` | XML download | Yes |
| NCBI Gene | `NCBIGeneParser` | NCBI FTP | Yes |
| Reactome | `ReactomeParser` | HTTP download | Yes |
| Uberon | `UberonParser` | OBO file | Yes |

## Troubleshooting

**`ista` not found:**
```bash
pip install -e .ista
```

**MySQL connection failed:** verify MySQL is running and credentials in `.env` are correct.

**DrugCentral connection failed:** the pipeline connects to a public read-only instance at `unmtid-dbs.net:5433`. Verify `DC_USER=drugman` and `DC_PASSWORD=dosage` are set in `.env`. To use a local dump instead, load it with `createdb drugcentral && gunzip -c drugcentral.sql.gz | psql drugcentral` and update `pg_config.host` in `databases.yaml`.

**EDirect not found (MEDLINE parser):** run `bash edirect/install-edirect.sh` from the repo root and add `edirect/` to your PATH.

**API authentication failed:** check API keys in `.env`.

**Download failed:** some sources need manual download — check the log for instructions.

## Further reading

- [`docs/overview.md`](docs/overview.md) — pipeline step details, config file contracts, and cross-module invariants
- [`docs/reference.md`](docs/reference.md) — full parser table, environment variables, and dependency list

## References

- [ista](https://github.com/RomanoLab/ista)
- [Hetionet](https://het.io/)
- [OmniPath/DoRothEA](https://omnipathdb.org/)
