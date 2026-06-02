---
name: memgraph-protocol
description: Use when running the CardioKB pipeline to load data into Memgraph, verifying graph contents, or managing Memgraph deployment via Docker. Covers the pipeline orchestrator (src/main.py), the Cypher batch loader (src/memgraph_loader.py), Docker deployment, and data export/import scripts.
---

## CardioKB Graph Loading

CardioKB loads data directly into Memgraph via Cypher (no intermediate CSV/RDF export step). The loader reads `src/ontology_configs.py` and batch-loads TSVs from `data/processed/`.

### Running the Pipeline

```bash
# Full pipeline: download → parse → TSV export → Memgraph load
python src/main.py

# Parse and export TSVs only (no graph load)
python src/main.py --skip-neo4j

# Use existing cached data (no downloads)
python src/main.py --skip-download

# Both flags
python src/main.py --skip-download --skip-neo4j
```

### Memgraph Connection

- Default: `bolt://localhost:7687` (Docker) or `bolt://localhost:7688` (local dev)
- Environment variables: `MEMGRAPH_URI`, `MEMGRAPH_USERNAME`, `MEMGRAPH_PASSWORD`
- The loader uses the Neo4j Python driver (compatible with Memgraph's Bolt protocol)

---

## The Loader: `src/memgraph_loader.py`

Key behaviors:
- Reads config entries from `src/ontology_configs.py`
- For each entry, reads the corresponding TSV from `data/processed/<source>/<filename>.tsv`
- **Node entries**: Uses `MERGE` on the primary key to avoid duplicates
- **Relationship entries**: Uses `MATCH` on subject/object nodes, then `MERGE` the relationship
- **source_label**: Automatically sets `r.source` property on every relationship from the config's `source_label` field
- Processes entries in order — node configs should come before relationship configs

---

## Docker Deployment

```bash
# Deploy web app + Memgraph
cp .env.example .env           # Fill in credentials
docker compose up -d           # App at http://localhost:5050

# Import pre-built graph data
./scripts/import_graph.sh data/export/memgraph-data.tar.gz

# Export graph data for transfer
./scripts/export_graph.sh      # Produces data/export/memgraph-data.tar.gz (~1.2 GB)
```

### Docker Compose Services

| Service | Port | Purpose |
|---------|------|---------|
| `memgraph` | 7687 (bolt) | Graph database |
| `web` | 5050 (http) | Flask web app + API |

---

## Verifying Graph Contents

After loading, verify via Cypher queries:

```cypher
-- Total counts
MATCH (n) RETURN count(n) AS nodes;
MATCH ()-[r]->() RETURN count(r) AS relationships;

-- Counts by label
MATCH (n) RETURN labels(n) AS label, count(n) AS count ORDER BY count DESC;

-- Counts by relationship type
MATCH ()-[r]->() RETURN type(r) AS type, count(r) AS count ORDER BY count DESC;

-- Source label coverage
MATCH ()-[r]->() RETURN r.source AS source, count(r) AS count ORDER BY count DESC;
```

### Expected Stats
- ~4.9M nodes | ~7.7M relationships
- 17 node types | 42 relationship types
- 21 source labels on relationships
