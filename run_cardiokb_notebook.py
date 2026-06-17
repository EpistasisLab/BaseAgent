"""Run cardiokb.ipynb cells 1-6 as a script (imports → agents → team → run_sync)."""
import os
import sys

# Fix SDK 0.95.0 conflict before any imports
os.environ.pop("ANTHROPIC_FOUNDRY_RESOURCE", None)

import nest_asyncio
nest_asyncio.apply()

from BaseAgent import BaseAgent, AgentTeam, MaxRoundsExceededError
from BaseAgent.agent_spec import AgentSpec

MCP_CONFIG = "examples/mcp_config.yaml"
SKILLS_DIR = "skills"
TEMPLATE_SRC = os.path.expanduser("~/Desktop/Cardio-KB")

# --- Cell 2: Token summary ---
def _print_token_summary(agents: list):
    print("\n=== Token usage ===")
    totals = {"input": 0, "output": 0, "total": 0}
    for agent in agents:
        metrics = agent.usage_metrics
        input_tokens = sum(m.input_tokens or 0 for m in metrics)
        output_tokens = sum(m.output_tokens or 0 for m in metrics)
        total_tokens = sum(m.total_tokens or 0 for m in metrics)
        cost = sum(m.cost or 0.0 for m in metrics)
        cost_str = f"  ${cost:.4f}" if cost else ""
        print(f"  {agent.spec.name}: {input_tokens} in / {output_tokens} out / {total_tokens} total{cost_str}")
        totals["input"] += input_tokens
        totals["output"] += output_tokens
        totals["total"] += total_tokens
    print(f"  {'─' * 40}")
    print(f"  all agents:  {totals['input']} in / {totals['output']} out / {totals['total']} total")

# --- Cell 4: Agent definitions ---
ontology_agent = BaseAgent(
    skills_directory=SKILLS_DIR,
    spec=AgentSpec(
        name="ontology_agent",
        role=(
            "A biomedical ontology engineer managing the OWL schema and schema definition files. "
            "You own ontology/cardiokb_ontology.rdf, ontology/schema/node_types.txt, and "
            "ontology/schema/edge_types.txt. You add or modify OWL classes, object properties, "
            "data properties, and edgeSource annotations. You keep node_types.txt and edge_types.txt "
            "in sync with the RDF. You do NOT own or edit src/ontology_configs.py — that belongs to "
            "mapping_agent. Only modify the RDF on explicit request. Never edit Python source files."
        ),
        llm="azure-claude-haiku-4-5",
        skill_names=["ontology-protocol"],
    ),
    require_approval="never",
)
ontology_agent.add_mcp(MCP_CONFIG)

engineer_agent = BaseAgent(
    skills_directory=SKILLS_DIR,
    spec=AgentSpec(
        name="engineer_agent",
        role=(
            "A Python software engineer writing parsers under src/parsers/. "
            "Each parser inherits from BaseParser (src/parsers/base_parser.py) and downloads data "
            "from one biomedical source, returning clean pandas DataFrames. "
            "Follow the registration checklist: src/parsers/__init__.py import, "
            "src/main.py PARSERS dict and create_parsers() instantiation. "
            "Run `python src/main.py --skip-memgraph` to verify each parser produces TSVs. "
            "Never hardcode disease-specific values or credentials in parser code. "
            "You do NOT modify ontology/cardiokb_ontology.rdf or src/ontology_configs.py."
        ),
        llm="azure-claude-sonnet-4-6",
        skill_names=["parser-protocol"],
    ),
    require_approval="never",
)
engineer_agent.add_mcp(MCP_CONFIG)

mapping_agent = BaseAgent(
    skills_directory=SKILLS_DIR,
    spec=AgentSpec(
        name="mapping_agent",
        role=(
            "A knowledge graph mapping specialist who exclusively owns src/ontology_configs.py. "
            "You map processed TSV columns to graph node types and relationship types with properties. "
            "Every relationship entry must include a source_label field. "
            "Verify all type names against ontology/schema/node_types.txt and edge_types.txt before writing. "
            "Never edit parser Python files or the OWL RDF file (ontology/cardiokb_ontology.rdf)."
        ),
        llm="azure-claude-haiku-4-5",
        skill_names=["mapping-protocol"],
    ),
    require_approval="never",
)
mapping_agent.add_mcp(MCP_CONFIG)

memgraph_agent = BaseAgent(
    skills_directory=SKILLS_DIR,
    spec=AgentSpec(
        name="memgraph_agent",
        role=(
            "A graph database engineer who runs the full CardioKB pipeline and validates graph contents. "
            "Run `python src/main.py` inside the repo to download, parse, and load all sources into Memgraph. "
            "Verify graph contents via Cypher queries against the live Memgraph instance. "
            "Use --skip-download to re-parse cached data, --skip-memgraph to skip graph loading."
        ),
        llm="azure-claude-haiku-4-5",
        skill_names=["memgraph-protocol"],
    ),
    require_approval="never",
)
memgraph_agent.add_mcp(MCP_CONFIG)

evaluator_agent = BaseAgent(
    skills_directory=SKILLS_DIR,
    spec=AgentSpec(
        name="evaluator_agent",
        role=(
            "A KG quality evaluator who runs eval/eval_after_memgraph.py against the live Memgraph "
            "instance. Report tier-1 blocking failures (zero node/edge counts, missing source properties) "
            "and overall KG quality. Flag any blocking failures that must be resolved before the KG is used."
        ),
        llm="azure-claude-haiku-4-5",
        skill_names=["evaluation-protocol"],
    ),
    require_approval="never",
)
evaluator_agent.add_mcp(MCP_CONFIG)

hitl_agent = BaseAgent(
    skills_directory=SKILLS_DIR,
    spec=AgentSpec(
        name="hitl_agent",
        role=(
            "A human review coordinator. Summarize the previous agent's output in less than 5 bullet "
            "points with descriptions on the task, target file(s), and rationale. "
            "Then call 'ask_user' with the summary and a clear yes/no question. "
        ),
        llm="azure-claude-haiku-4-5",
        skill_names=["hitl-protocol"],
    ),
    require_approval="never",
)
hitl_agent.add_mcp(MCP_CONFIG)

# --- Cell 5: Team and task ---
agents = [
    ontology_agent, engineer_agent, evaluator_agent, mapping_agent, memgraph_agent, hitl_agent,
]

team = AgentTeam(
    agents=agents,
    supervisor_llm="azure-claude-opus-4-7",
    max_rounds=200,
)

CARDIOKB_SOURCES = [
    "ClinicalTrials.gov (ClinicalTrialsParser)",
    "ClinPGx (ClinPGxParser)",
    "NCBI Gene (NCBIGeneParser)",
    "DoRothEA (DoRothEAParser)",
    "DrugBank (DrugBankParser)",
    "Disease Ontology (DiseaseOntologyParser)",
    "Gene Ontology (GeneOntologyParser)",
    "Uberon (UberonParser)",
    "MeSH (MeSHParser)",
    "SIDER (SIDERParser) — legacy, no live API",
    "LINCS L1000 (LINCS1000Parser) — legacy",
    "MEDLINE (MEDLINECooccurrenceParser) — legacy, pinned commit",
    "DrugCentral (DrugCentralParser)",
    "BindingDB (BindingDBParser)",
    "PubTator Central (PubTatorParser)",
    "CTD (CTDParser)",
    "Bgee (BgeeParser)",
    "Jensen TISSUES (JensenTissuesParser)",
    "HPO (HPOParser)",
    "Reactome (ReactomeParser)",
    "STRING (STRINGParser)",
    "OpenTargets (OpenTargetsParser)",
    "HGNC Families (HGNCFamiliesParser)",
    "ClinVar (ClinVarParser)",
]

THREAD_ID = "cardiokb_full_rebuild"

task = f"""
Coordinate a team of agents to verify and rebuild the full CardioKB knowledge graph at {TEMPLATE_SRC}.

CardioKB integrates 24 deduplicated data sources into a Memgraph graph database for CVD research.
The graph should produce ~4.9M nodes, ~7.7M relationships, 17 node types, 42 relationship types, and 21 source labels.

## Key Files
- OWL ontology: ontology/cardiokb_ontology.rdf (defines classes, properties, edgeSource annotations)
- Schema: ontology/schema/node_types.txt (17 types), ontology/schema/edge_types.txt (relationship types)
- Ontology configs: src/ontology_configs.py (86 entries mapping TSVs to graph schema)
- Pipeline orchestrator: src/main.py (PARSERS dict, create_parsers(), pipeline flags)
- Parsers: src/parsers/*.py and src/parsers/hetionet_components/*.py (24 parsers inheriting BaseParser)
- Loader: src/memgraph_loader.py (Cypher batch loader, auto-sets r.source from config source_label)
- Disease scope: ontology/disease_filter.txt → ontology/diseases/cvd.txt (184 CVD terms)

## All 24 Sources (process sequentially)
{chr(10).join(f"  {{i+1}}. {{s}}" for i, s in enumerate(CARDIOKB_SOURCES))}

## Agent Responsibilities
- ontology_agent: Owns ontology/cardiokb_ontology.rdf and ontology/schema/ files. Ensures RDF classes,
  properties, and edgeSource annotations are correct. Does NOT edit src/ontology_configs.py.
- engineer_agent: Owns src/parsers/*.py and src/main.py. Creates/updates parsers, registers them.
  Verifies with `python src/main.py --skip-memgraph`.
- mapping_agent: Exclusively owns src/ontology_configs.py. Maps TSV columns to graph types/properties.
  Every relationship entry must have source_label. Validates against schema files.
- memgraph_agent: Runs full pipeline (`python src/main.py`), verifies graph via Cypher queries.
- evaluator_agent: Runs eval/eval_after_memgraph.py, reports tier-1 blocking failures.
- hitl_agent: Pauses for user review before major config changes.

## Process for Each Source
1. engineer_agent: Verify parser exists, downloads correctly, produces expected TSVs
2. mapping_agent: Verify ontology_configs.py entries match TSV columns and schema types
3. ontology_agent: Verify RDF has correct OWL classes/properties with edgeSource for this source
4. If any issues found, fix them (respecting ownership boundaries)
5. After all 24 sources verified, memgraph_agent runs full pipeline
6. evaluator_agent runs eval and reports results

## Constraints
- Do not create new parsers from scratch — all 24 already exist. Fix/update only if broken.
- Do not hardcode disease-specific values in parsers.
- Every relationship in ontology_configs.py must have source_label.
- Three legacy sources (SIDER, LINCS L1000, MEDLINE) are retained as-is.
- src/ontology_configs.py ownership is mapping_agent ONLY.
"""

# --- Cell 6: Run ---
print("=" * 60)
print("Starting CardioKB Full Rebuild via BaseAgent Team")
print(f"Sources: {len(CARDIOKB_SOURCES)}")
print(f"Agents: {[a.spec.name for a in agents]}")
print(f"Supervisor: azure-claude-opus-4-7")
print("=" * 60)

try:
    _log, result = team.run_sync(task, thread_id=THREAD_ID)
    print("\n" + "=" * 60)
    print("BUILD COMPLETE")
    print("=" * 60)
    print(result)
except MaxRoundsExceededError:
    print("\n" + "=" * 60)
    print("MAX ROUNDS REACHED — run 'Continue' cell to resume")
    print("=" * 60)
except Exception as e:
    print(f"\nBuild failed with error: {e}")

_print_token_summary(agents)
