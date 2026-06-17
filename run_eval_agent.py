"""
Run a BaseAgent with the evaluation-protocol skill to write eval scripts for CardioKB.

The agent will read CardioKB's ontology_configs.py and processed TSV structure,
then generate evaluation scripts based on eval_metrics.md.

Usage:
    conda activate baseagent
    cd ~/Desktop/BaseAgent
    python run_eval_agent.py
"""

import os
import sys

from dotenv import load_dotenv
load_dotenv()

from BaseAgent import BaseAgent
from BaseAgent.agent_spec import AgentSpec

SKILLS_DIR = "skills"
MCP_CONFIG = "examples/mcp_config.yaml"
CARDIOKB_ROOT = os.path.expanduser("~/Desktop/Cardio-KB")

agent = BaseAgent(
    skills_directory=SKILLS_DIR,
    spec=AgentSpec(
        name="evaluator_agent",
        role=(
            "A KG quality evaluator who writes evaluation scripts. "
            "You have deep expertise in biomedical knowledge graph quality assurance. "
            "You write Python scripts that compute metrics from processed TSV files "
            "and from a live Memgraph database. Follow the evaluation-protocol skill "
            "and eval_metrics.md reference for the full metric catalog."
        ),
        llm="azure-claude-sonnet-4-6",
        skill_names=["evaluation-protocol"],
    ),
    require_approval="never",
)
agent.add_mcp(MCP_CONFIG)

task = f"""
Write TWO new evaluation scripts for the CardioKB project at {CARDIOKB_ROOT}.

CardioKB is different from alzkb-updater — it does NOT use config/project.yaml,
config/databases.yaml, or config/ontology_mappings.yaml. Instead it uses:
  - src/ontology_configs.py — a Python module with 86 ontology config dicts
    mapping parsed TSV files to graph node/relationship types, properties, and loading strategies
  - data/processed/<source_name>/*.tsv — processed TSV files from 26 parsers
  - Memgraph database accessible via bolt://localhost:7687 (with auth from env vars
    MEMGRAPH_URI, MEMGRAPH_USERNAME, MEMGRAPH_PASSWORD)
  - src/parsers/ — 26 parser classes inheriting from base_parser.py

IMPORTANT CONTEXT:
  - CardioKB has NO OWL/RDF files and NO ontology population step
  - Data flows: raw download → parser → TSV → Memgraph load (via Cypher UNWIND batches)
  - The graph has 19 node types, 43 relationship types, 26 data sources
  - All relationships carry a `source` property (e.g., source: "OpenTargets")

YOUR TASK — Write these two scripts into {CARDIOKB_ROOT}/eval/:

1. eval_after_parser.py
   - Reads ontology configs from src/ontology_configs.py to discover expected TSV files
   - Computes all implementable "After Parser" metrics from eval_metrics.md:
     Tier 1: Source database extraction, TSV structural integrity, Extracted record counts,
             Filter pass rate, Duplication rate per ontology
     Tier 2: Null/empty field rate per property, Identifier format validity rate,
             Property value constraint violations, Source schema conformance
     Tier 3: Extraction timestamp per source
   - Output: JSON report matching the eval_metrics.md schema

2. eval_after_memgraph.py
   - Connects to Memgraph via bolt protocol (using Memgraph-compatible driver, env vars for auth)
   - Computes all implementable "After Memgraph Export" metrics from eval_metrics.md:
     Tier 1: Total node count per label, Total edge count per type,
             Relationship resolution rate (cross-check TSV rows vs graph)
     Tier 2: Orphan node rate, Duplicate edge rate,
             Largest connected component fraction, Average node degree per label
     Tier 3: High-degree outlier count per relationship type
   - Output: JSON report matching the eval_metrics.md schema

BEFORE writing the scripts:
  1. Read {CARDIOKB_ROOT}/src/ontology_configs.py to understand the config structure
  2. Read {CARDIOKB_ROOT}/src/parsers/base_parser.py to understand parser structure
  3. List {CARDIOKB_ROOT}/data/processed/ to see available source directories
  4. Read a few sample TSV files to understand column structure
  5. Read the eval_metrics.md and eval_metrics.json references thoroughly

REQUIREMENTS:
  - Each script must be standalone (no dependency on alzkb-updater configs)
  - Use argparse with --output flag for JSON file output
  - Match the JSON output schema from the evaluation-protocol skill
  - Import ontology configs directly from CardioKB's src/ontology_configs.py
  - Handle missing files gracefully (some sources may not have been parsed yet)
  - Use the Memgraph (neo4j-compatible) driver for Memgraph queries (already in CardioKB's dependencies)
"""

print("Starting evaluator agent...")
print(f"Target: {CARDIOKB_ROOT}/eval/")
print("The agent will ask for approval before writing files.\n")

_log, result = agent.run(task)
print("\n=== Agent finished ===")
print(result)
