---
name: evaluation-protocol
description: Use when running or interpreting the CardioKB evaluation suite. Covers the eval script (eval/eval_after_memgraph.py), output JSON format, the three-tier metric system, blocking vs. monitoring thresholds, and interpreting results. Use when asked to evaluate pipeline output, diagnose zero-count failures, or interpret eval reports.
---

## Eval Script

CardioKB uses a single eval script that queries the live Memgraph instance:

| Script | Prerequisite | What it checks |
|--------|-------------|----------------|
| `eval/eval_after_memgraph.py` | Full pipeline run + Memgraph loaded | Node/relationship counts per source, cross-source merge analysis, pass/fail per source |

The script connects to Memgraph at `bolt://localhost:7687` and queries actual graph contents.

---

## CLI

```bash
# Run evaluation against live Memgraph
python eval/eval_after_memgraph.py

# Output report to file
python eval/eval_after_memgraph.py --output eval/reports/eval_report.md
```

---

## Tier System

| Tier | Label | Action |
|------|-------|--------|
| 1 | Block Release | Zero node/edge counts for expected types block release |
| 2 | Monitor Trends | Track across runs; investigate regressions |
| 3 | Periodic Audit | Scheduled checks against external benchmarks |

**Blocking failures (Tier 1)**:
- Any node or edge count = 0 for an expected source
- Missing `source` property on relationships
- Source not present in graph at all

---

## Key Metrics

For each of the 24 sources, the eval checks:
- Node counts by label
- Relationship counts by type
- `source` property present on all relationships
- Cross-source merge success (e.g., Gene nodes from multiple sources merge on `geneSymbol`)

---

## Expected Graph Stats (Reference)

- ~4.9M nodes | ~7.7M relationships | 17 node types | 42 relationship types | 24 sources | 21 source labels
- All relationships carry a `source` property identifying the originating database
