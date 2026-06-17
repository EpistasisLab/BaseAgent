# BaseAgent Validation Report: Recreating CardioKB

**Date:** April 16, 2026
**Prepared by:** Asma Nawaz
**Purpose:** Validate BaseAgent's ability to autonomously construct the CardioKB cardiovascular disease knowledge graph from scratch, using only a task prompt, schema templates, and a list of 26 public databases.

---

## 1. Executive Summary

BaseAgent (v0.1.0) was tasked with recreating CardioKB, a CVD-focused biomedical knowledge graph originally built with a custom Python pipeline of 26 hand-written parsers. The agent was given:

- A list of 26 databases with URLs and access types
- A schema of 19 node types and 43 edge types
- CVD disease terms for filtering
- An empty Memgraph instance

**Result:** BaseAgent successfully built a functional knowledge graph with **1,036,899 nodes**, **10,800,305 edges**, **all 19 node types**, **41 of 43 edge types**, and data from **all 26 sources**. Five framework bugs were discovered and patched during the process.

| Metric | Original CardioKB | BaseAgent Build | Match |
|--------|-------------------|-----------------|-------|
| Total Nodes | 4,896,258 | 1,036,899 | 21.2% |
| Total Edges | 7,683,150 | 10,800,305 | 140.6% |
| Node Types | 19 | 19 | 100% |
| Edge Types | 43 | 41 | 95.3% |
| Source Labels | 23 | 22 | 95.7% |
| Data Sources | 26 | 26 | 100% |
| Build Time | ~4 hours (pipeline) | ~12 hours (agent) | -- |
| LLM | -- | claude-sonnet-4-6 | -- |
| Infra | Custom Python pipeline | BaseAgent + LangGraph | -- |

---

## 2. Bugs Found in BaseAgent (5 Total)

### Bug 1: SqliteSaver Checkpointer Incompatibility (BLOCKING)

**File:** `BaseAgent/base_agent.py`, line 1031
**Severity:** Blocking -- prevents agent from starting

**What happens:** When you create a BaseAgent with `checkpoint_db_path` set to a file (for session persistence), the agent crashes immediately on startup before doing any work.

**Technical detail:** The `_create_checkpointer()` method calls `SqliteSaver.from_conn_string(db_path)` and passes the return value directly to `workflow.compile(checkpointer=...)`. In langgraph >= 1.1.x / langgraph-checkpoint-sqlite >= 3.0, `from_conn_string()` returns a `_GeneratorContextManager` (a context manager), not a `SqliteSaver` instance. LangGraph's compile step validates the type and rejects it:

```
TypeError: Invalid checkpointer provided. Expected an instance of
BaseCheckpointSaver. Received _GeneratorContextManager.
```

**Fix applied:**
```python
saver_cm = SqliteSaver.from_conn_string(db_path)
if hasattr(saver_cm, '__enter__'):
    self._checkpointer_cm = saver_cm
    return saver_cm.__enter__()
return saver_cm
```

**Recommendation:** Enter the context manager before passing to compile, and call `__exit__()` in the `close()` method for proper cleanup.

---

### Bug 2: Missing Token Usage Attributes (MINOR)

**File:** `BaseAgent/base_agent.py`
**Severity:** Minor -- cosmetic crash after successful run

**What happens:** The README and example code reference `agent.total_input_tokens`, `agent.total_output_tokens`, and `agent.total_cost` for post-run cost reporting. These attributes do not exist on the `BaseAgent` class. Accessing them raises `AttributeError` after the agent has already completed its work.

**Fix applied:** Wrapped in `hasattr()` check in `build_cardiokb.py`. Proper fix should add these properties to `BaseAgent`.

---

### Bug 3: AnthropicFoundry base_url / resource Conflict (BLOCKING)

**File:** `BaseAgent/llm.py`, lines 400-407 and 517-523
**Severity:** Blocking -- prevents Azure Foundry from working

**What happens:** When using Azure AI Foundry as the LLM provider, the agent crashes because the Anthropic SDK's `AnthropicFoundry` client receives both `base_url` and `resource` arguments, which are mutually exclusive.

**Technical detail:** BaseAgent reads `ANTHROPIC_FOUNDRY_BASE_URL` from `.env` and passes it as `base_url`. However, the Anthropic Python SDK also auto-reads `ANTHROPIC_FOUNDRY_RESOURCE` from the environment (commonly set system-wide for tools like Claude Code). When both are present, the SDK raises:

```
ValueError: base_url and resource are mutually exclusive
```

Additionally, `_build_model_kwargs()` only reads `ANTHROPIC_FOUNDRY_BASE_URL`, with no support for `ANTHROPIC_FOUNDRY_RESOURCE`.

**Fix applied:**
1. Added `ANTHROPIC_FOUNDRY_RESOURCE` support in `_build_model_kwargs()` -- constructs the URL from the resource name if `BASE_URL` is not set.
2. In the Foundry client construction, extract the resource name from standard-format URLs (`https://<resource>.services.ai.azure.com/anthropic/`) and pass `resource=` instead of `base_url=`.
3. Clear conflicting env vars before constructing the client.

**Recommendation:** Support both `ANTHROPIC_FOUNDRY_RESOURCE` and `ANTHROPIC_FOUNDRY_BASE_URL` as first-class configuration options, with resource taking precedence when both are set.

---

### Bug 4: Assistant Message Prefill Rejected by claude-sonnet-4-6 (BLOCKING)

**File:** `BaseAgent/nodes.py`, line 268
**Severity:** Blocking -- prevents use of newer Claude models

**What happens:** After the agent executes code and receives output, the next LLM call crashes with:

```
This model does not support assistant message prefill.
The conversation must end with a user message.
```

**Technical detail:** In the `execute` node, execution observations (stdout/stderr from code blocks) are appended to the conversation as `AIMessage`:

```python
state["input"].append(AIMessage(content=observation.strip()))
```

This creates a sequence of `AIMessage -> AIMessage` (the code response + the observation). When the agent loops back to the `generate` node, the conversation ends with an assistant message. Older Claude models (3.5, 4, Sonnet 4-5) tolerate this, but `claude-sonnet-4-6` enforces that conversations must end with a user message.

**Fix applied:** Changed to `HumanMessage`:
```python
state["input"].append(HumanMessage(content=observation.strip()))
```

This is also semantically correct -- observations are environment feedback, not assistant output.

---

### Bug 5: No Retry/Backoff on Rate Limit (429) Errors (BLOCKING)

**File:** `BaseAgent/nodes.py`, lines 121-123
**Severity:** Blocking -- crashes long-running tasks

**What happens:** During long tasks, the conversation context grows with each code execution cycle. Eventually the input tokens per request exceed the provider's per-minute rate limit (e.g., Azure Foundry's 250,000 uncached input tokens/minute). The agent crashes instead of waiting and retrying.

**Technical detail:** The LLM invocation has a bare try/except that immediately re-raises all errors:

```python
try:
    output = agent.llm.invoke(input)
except Exception as exc:
    raise LLMError(str(exc)) from exc
```

A 429 rate limit error is transient -- waiting 60 seconds would allow the request to succeed. Without retry logic, the agent loses all progress.

**Fix applied:** Added exponential backoff retry:
```python
max_retries = 5
for attempt in range(max_retries + 1):
    try:
        output = agent.llm.invoke(input)
        break
    except Exception as exc:
        err_str = str(exc)
        is_rate_limit = "429" in err_str or "RateLimit" in err_str or "rate limit" in err_str.lower()
        if is_rate_limit and attempt < max_retries:
            wait = 60 * (attempt + 1)  # 60s, 120s, 180s, 240s, 300s
            print(f"Rate limit hit (attempt {attempt + 1}/{max_retries + 1}). Waiting {wait}s...")
            time.sleep(wait)
        else:
            raise LLMError(err_str) from exc
```

**Note:** In the final successful build (12 hours), the retry logic was never triggered -- the rate limit was avoided naturally. However, it was triggered in earlier builds that used a smaller model with faster output, causing more rapid context growth.

---

## 3. Node Type Comparison (19 Types)

| Node Type | Original CardioKB | BaseAgent Build | Ratio | Diagnosis |
|-----------|-------------------|-----------------|-------|-----------|
| Variant | 4,488,042 | 221,645 | 4.9% | BaseAgent parsed a subset of ClinVar (likely variant_summary.txt only, not the full VCF). Original pipeline uses comprehensive ClinVar FTP extraction with all variant types. |
| Gene | 194,559 | 64,231 | 33.0% | BaseAgent likely filtered to human protein-coding genes only. Original loads all NCBI Gene entries for Homo sapiens including pseudogenes, ncRNA genes, etc. |
| ClinicalTrial | 85,691 | 2,677 | 3.1% | BaseAgent queried ClinicalTrials.gov API with fewer CVD terms or pagination limits. Original pipeline queries 184 CVD terms with full pagination. |
| BiologicalProcess | 24,547 | 24,427 | 99.5% | Near-exact match. Minor difference from GO version or filtering. |
| Drug | 24,429 | 637,821 | 2611% | BaseAgent loaded CTD chemicals broadly without deduplication against DrugBank. Original merges DrugBank (19,842) + CTD unique additions (4,572) with strict dedup. |
| Phenotype | 19,389 | 19,388 | ~100% | Effectively identical. |
| BodyPart | 14,937 | 14,970 | 100.2% | Near-exact match. |
| Disease | 12,096 | 2,561 | 21.2% | BaseAgent applied aggressive CVD filtering on Disease Ontology. Original loads the full Disease Ontology (all 12K diseases) since other sources reference non-CVD diseases too. |
| MolecularFunction | 10,123 | 10,056 | 99.3% | Near-exact match. |
| SideEffect | 5,734 | 4,251 | 74.1% | Partial SIDER parsing -- some CUI mappings likely missed. |
| Species | 4,645 | 4,645 | 100% | Exact match. AnAge fully loaded. |
| CellularComponent | 4,069 | 4,076 | 100.2% | Near-exact match. |
| Pathway | 2,806 | 2,836 | 101.1% | Near-exact match. Slight version difference in Reactome data. |
| GeneFamily | 1,934 | 3,287 | 170% | BaseAgent loaded more family entries, possibly including non-human or deprecated families. |
| PharmacologicClass | 1,646 | 2,359 | 143.3% | BaseAgent loaded additional pharmacologic classes from DrugCentral, possibly without filtering to graph-linked drugs only. |
| Symptom | 966 | 15,947 | 1651% | BaseAgent loaded the full MeSH symptom tree. Original only loads symptoms referenced by MEDLINE cooccurrence edges. |
| DrugLabel | 378 | 29 | 7.7% | BaseAgent parsed a subset of ClinPGx drug labels. Original loads all CPIC-annotated labels. |
| TranscriptionFactor | 367 | 367 | 100% | Exact match. |
| AgeingProperty | 3 | 1,326 | 44200% | BaseAgent created individual AgeingProperty nodes per drug-aging association instead of 3 categorical nodes (pro-longevity, anti-longevity, no effect). |

---

## 4. Edge Type Comparison (43 Types)

### Edges Present in Both (41 types)

| Edge Type | Original | BaseAgent | Ratio | Diagnosis |
|-----------|----------|-----------|-------|-----------|
| hasVariant | 2,267,095 | 221,429 | 9.8% | Proportional to Variant node count reduction (subset of ClinVar). |
| variantInGene | 2,267,095 | 221,429 | 9.8% | Same as above -- reverse direction of hasVariant. |
| bodyPartUnderexpressesGene | 784,026 | 422,604 | 53.9% | BaseAgent applied stricter filtering (gold quality only) on Bgee data. |
| geneAssociatesWithDisease | 777,271 | 291,069 | 37.4% | Combines OpenTargets + PubTator in original. BaseAgent loaded OpenTargets with different EFO-to-DOID mapping coverage. |
| geneExpressedInBodyPart | 215,235 | 54,389 | 25.3% | Jensen TISSUES parsed with higher confidence threshold or fewer tissues. |
| geneAssociatesWithPhenotype | 162,994 | 266,981 | 163.8% | BaseAgent loaded more HPO gene-phenotype annotations, possibly including lower-confidence associations. |
| geneRegulatesGene | 150,540 | 265,667 | 176.4% | BaseAgent merged LINCS L1000 + Hetionet regulatory edges. Original uses LINCS L1000 only. |
| compoundCausesSideEffect | 148,518 | 140,677 | 94.7% | Close match. Minor SIDER parsing differences. |
| geneInteractsWithGene | 121,170 | 229,000 | 189.0% | BaseAgent used a lower STRING confidence threshold. Original uses >700; agent likely used >400 or default. |
| chemicalIncreasesExpression | 116,451 | 343,863 | 295.3% | BaseAgent loaded CTD chemical-gene interactions more broadly, without CVD gene filtering. |
| variantAssociatedWithDisease | 99,707 | 105,784 | 106.1% | Close match with slightly different ClinVar disease mapping. |
| associatedWithVariant | 99,707 | 105,784 | 106.1% | Reverse of above. |
| chemicalDecreasesExpression | 97,951 | 328,761 | 335.6% | Same as chemicalIncreasesExpression -- broader CTD loading. |
| geneParticipatesInBiologicalProcess | 50,350 | 126,038 | 250.4% | BaseAgent loaded all GO annotations, not just those for CVD-associated genes. |
| geneInPathway | 44,979 | 136,956 | 304.5% | BaseAgent loaded all human Reactome pathways, not filtered to CVD gene set. |
| pathwayContainsGene | 44,979 | 136,956 | 304.5% | Reverse of above. |
| STUDIES_CONDITION | 27,866 | 1,543 | 5.5% | Fewer ClinicalTrial nodes = fewer condition edges. |
| geneHasMolecularFunction | 26,935 | 77,848 | 289.1% | Broader GO annotation loading. |
| geneInSpecies | 26,417 | 64,231 | 243.2% | BaseAgent assigned species to all loaded genes. Original only assigns to a curated subset. |
| geneAssociatedWithCellularComponent | 25,794 | 91,608 | 355.2% | Broader GO annotation loading. |
| TESTS_INTERVENTION | 17,492 | 404 | 2.3% | Proportional to ClinicalTrial reduction. |
| compoundInPharmacologicClass | 16,403 | 24,230 | 147.7% | More DrugCentral pharmacologic class assignments loaded. |
| pharmacologicClassIncludesCompound | 16,403 | 24,230 | 147.7% | Reverse of above. |
| transcriptionFactorInteractsWithGene | 12,985 | 15,082 | 116.1% | BaseAgent loaded DoRothEA with lower confidence threshold (A+B+C+D vs A+B+C). |
| chemicalBindsGene | 12,250 | 849,957 | 6938% | BaseAgent loaded the full BindingDB dataset without filtering to known Drug nodes. Original filters to drugs already in the graph. |
| drugBindsGene | 12,099 | 13,426 | 110.9% | Close match. Slight DrugBank parsing differences. |
| compoundUpregulatesGene | 10,278 | 2,098,580 | 20418% | BaseAgent loaded full LINCS L1000 without CVD gene or significance filtering. Original applies strict z-score thresholds. |
| compoundDownregulatesGene | 10,218 | 1,881,238 | 18411% | Same as above. |
| geneInFamily | 5,123 | 34,021 | 664.1% | BaseAgent loaded all HGNC family memberships. Original filters to graph-present genes. |
| familyContainsGene | 5,123 | 34,021 | 664.1% | Reverse of above. |
| diseaseAssociatesWithDisease | 4,320 | 17,261 | 399.6% | BaseAgent loaded PubTator disease-disease associations without CVD AND-filter. Original requires both diseases to be CVD-related. |
| bodyPartOverexpressesGene | 1,872 | 2,166,937 | 115754% | Largest discrepancy. BaseAgent loaded all Bgee overexpression data. Original applies stringent CVD gene + expression score filtering. |
| VARIANT_IN | 1,091 | 0 | 0% | **Missing.** ClinPGx VARIANT_IN edges not created. |
| drugLabelAnnotatesGene | 503 | 158 | 31.4% | Partial ClinPGx parsing. |
| associatedWithAging | 386 | 1,832 | 474.6% | Loaded more DrugAge associations, possibly including non-CVD genes. |
| drugLabelDescribesDrug | 345 | 320 | 92.8% | Close match. |
| diseaseIsSubtypeOf | 258 | 687 | 266.3% | BaseAgent loaded more Disease Ontology hierarchy. Original filters to CVD subtree. |
| drugTreatsDisease | 250 | 4,153 | 1661% | BaseAgent loaded all DrugCentral treatment relationships. Original filters to CVD diseases. |
| diseaseLocalizesToAnatomy | 244 | 365 | 149.6% | More MEDLINE cooccurrence edges loaded. |
| AFFECTS_RESPONSE_TO | 243 | 561 | 230.9% | More ClinPGx pharmacogenomic associations loaded. |
| diseasePresentsSymptom | 117 | 218 | 186.3% | More MEDLINE symptom cooccurrence loaded. |
| drugPalliatesDisease | 96 | 0 | 0% | **Missing.** DrugCentral palliative relationships not created as separate edge type. |
| diseaseResemblesDisease | 4 | 7 | 175% | Minor difference in MEDLINE similarity edges. |

### Missing Edge Types (2 types)

| Edge Type | Original Count | Source | Why Missing |
|-----------|---------------|--------|-------------|
| VARIANT_IN | 1,091 | ClinPGx | BaseAgent parsed ClinPGx gene-drug relationships but did not create the VARIANT_IN edge type linking variants to genes from ClinPGx data. |
| drugPalliatesDisease | 96 | DrugCentral | BaseAgent loaded DrugCentral treatment data as `drugTreatsDisease` but did not distinguish palliative relationships as a separate edge type. |

---

## 5. Source Label Comparison

| Source Label | Original Edges | BaseAgent Edges | Present |
|-------------|---------------|-----------------|---------|
| Bgee | 785,898 | 2,589,541 | Yes |
| BindingDB | 12,250 | 849,957 | Yes |
| CTD | 214,402 | 672,624 | Yes |
| ClinPGx | 2,182 | 1,039 | Yes |
| ClinVar | 4,733,604 | 654,426 | Yes |
| ClinicalTrials.gov | 45,358 | 1,947 | Yes |
| Disease Ontology | 258 | 687 | Yes |
| DoRothEA | 12,985 | 15,082 | Yes |
| DrugAge | 386 | 1,832 | Yes |
| DrugBank | 12,099 | -- | No* |
| DrugCentral | 32,992 | 66,039 | Yes |
| Gene Ontology | 103,079 | 295,494 | Yes |
| HGNC | 10,246 | 68,042 | Yes |
| HPO | 162,994 | 266,981 | Yes |
| Jensen TISSUES | 215,235 | 54,389 | Yes |
| LINCS L1000 | 171,036 | 4,245,485 | Yes |
| MEDLINE | 365 | 590 | Yes |
| NCBI Gene | 26,417 | 64,231 | Yes |
| OpenTargets | 777,271 | 291,069 | Yes |
| PubTator | 4,320 | 17,261 | Yes |
| Reactome | 89,958 | 273,912 | Yes |
| SIDER | 148,518 | 140,677 | Yes |
| STRING | 121,170 | 229,000 | Yes |

*DrugBank edges (drugBindsGene: 13,426) were loaded but without a `source: "DrugBank"` label -- they were sourced from Hetionet's pre-extracted DrugBank data.

---

## 6. Key Findings and Diagnosis

### Why BaseAgent has fewer nodes (1.04M vs 4.9M)

The 3.8M node gap is almost entirely explained by two sources:

1. **ClinVar Variants:** Original has 4,488,042 Variant nodes vs BaseAgent's 221,645. The original pipeline downloads the full ClinVar VCF and variant_summary files, extracting every variant. BaseAgent parsed a subset, likely using only the variant_summary.txt file with size limits on the download.

2. **Gene coverage:** Original has 194,559 Gene nodes (all human NCBI Gene entries) vs BaseAgent's 64,231 (likely filtered to protein-coding genes only).

Together, these two sources account for ~4.4M of the 4.9M original nodes.

### Why BaseAgent has more edges (10.8M vs 7.7M)

BaseAgent applied **less aggressive filtering** on several high-volume sources:

1. **LINCS L1000** (4.2M edges vs 171K): BaseAgent loaded the full LINCS dataset without z-score significance filtering. The original pipeline applies strict thresholds.
2. **Bgee** (2.6M vs 786K): BaseAgent loaded all expression data. The original filters by CVD gene set and expression score.
3. **BindingDB** (850K vs 12K): BaseAgent loaded the entire BindingDB binding dataset. The original filters to drugs already present in the graph.
4. **CTD** (673K vs 214K): Loaded without CVD gene restriction.
5. **GO annotations** (295K vs 103K): Loaded all annotations, not just CVD-associated genes.

The fundamental difference: **CardioKB's pipeline applies CVD-focused filtering at every stage**, while BaseAgent loaded data more broadly and relied on CVD filtering primarily at the disease level.

### Why 2 edge types are missing

Both are minor edge types with low counts in the original:
- `VARIANT_IN` (1,091 edges): ClinPGx variant-gene links -- the agent created other ClinPGx edges but missed this specific type.
- `drugPalliatesDisease` (96 edges): The agent merged palliative and treatment relationships under `drugTreatsDisease`.

---

## 7. Overall Assessment

### What BaseAgent Did Well

1. **Complete source coverage:** All 26 databases were accessed, downloaded, and parsed. No source was skipped entirely.
2. **Schema compliance:** All 19 node types were created with correct primary keys. 41 of 43 edge types were generated.
3. **Source provenance:** 22 of 23 source labels were correctly applied to relationships.
4. **Autonomous operation:** After receiving the task prompt, the agent worked for 12 hours without human intervention, writing its own download code, parsers, Cypher queries, and error handling.
5. **Infrastructure creation:** The agent created reusable parser scripts in `./src/parsers/` and organized processed data in `./data/processed/` with proper directory structure.

### What Needs Improvement

1. **Disease filtering consistency:** The biggest gap is inconsistent CVD filtering. Some sources were loaded in their entirety (LINCS, BindingDB, Bgee) while others were aggressively filtered (Disease Ontology, ClinicalTrials.gov). A production pipeline needs uniform filtering logic.
2. **Deduplication:** Drug nodes (637K vs 24K) show that the agent loaded CTD chemicals without deduplicating against DrugBank, inflating the node count.
3. **ClinVar completeness:** Only 5% of variants were loaded, suggesting the agent downloaded a subset rather than the full ClinVar data.
4. **Edge type precision:** Two edge types were missed, and several were conflated (palliative vs treatment).
5. **Build time:** 12 hours vs 4 hours for the original pipeline, due to the iterative LLM reasoning overhead.

### Framework Bugs Impact

All 5 bugs found were in BaseAgent's framework code, not in the agent's reasoning:

| Bug | Impact on Build | Workaround Difficulty |
|-----|-----------------|----------------------|
| #1 SqliteSaver | Blocked startup entirely | Easy (use in-memory) |
| #2 Token metrics | Cosmetic only | Trivial |
| #3 Foundry config | Blocked Azure Foundry | Medium (env var juggling) |
| #4 Message prefill | Blocked claude-sonnet-4-6 | Easy (one-line fix) |
| #5 Rate limit retry | Crashed long tasks | Medium (add retry loop) |

Bugs #1, #3, and #4 are blockers that prevent basic functionality. They should be fixed before any production use.

### Conclusion

BaseAgent demonstrated that an LLM agent **can** autonomously construct a biomedical knowledge graph from a schema specification and database list. The resulting graph covers all intended sources and node/edge types, with reasonable counts for most categories.

However, the graph is **not a drop-in replacement** for CardioKB. The key gaps are:
- Inconsistent disease-scope filtering (some sources loaded too broadly, others too narrowly)
- Missing deduplication logic for cross-source entities (especially drugs)
- Incomplete large-file downloads (ClinVar, NCBI Gene)

For validation purposes, this demonstrates BaseAgent is a viable tool for **rapid prototyping** of knowledge graphs, but the output requires manual review and tuning to match a production-quality pipeline.

---

## Appendix A: Configuration Used

```
LLM: claude-sonnet-4-6
Provider: Azure AI Foundry (MooreLabGPT4 resource)
Database: Memgraph (bolt://localhost:7688)
Approval mode: never (auto-execute)
Checkpoint: in-memory
Build log: 13,035 lines
Rate limit retries: 0 (none needed)
```

## Appendix B: Files Generated by BaseAgent

**Parsers** (`./src/parsers/`):
- `utils.py` -- shared utilities (CVD filtering, Memgraph connection, download helpers)
- `parse_ncbi_gene.py` -- NCBI Gene parser
- `parse_disease_ontology.py` -- Disease Ontology OBO parser
- `parse_drugbank.py` -- DrugBank XML parser (requires manual download)
- `cardiokb_pipeline.py` -- orchestration script

**Processed data** (`./data/processed/`): 26 source directories with TSV files.

## Appendix C: Bugs Filed

All 5 bugs should be reported to the BaseAgent maintainer (Binglan Li) at:
https://github.com/BinglanLi/BaseAgent/issues
