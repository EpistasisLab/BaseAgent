#!/usr/bin/env python
import os
os.chdir('/Users/nawaza/Desktop/BaseAgent')

from dotenv import load_dotenv
load_dotenv('/Users/nawaza/Desktop/BaseAgent/.env')

import nest_asyncio
nest_asyncio.apply()

from BaseAgent import BaseAgent
from BaseAgent.agent_spec import AgentSpec

BASEAGENT_DIR = os.path.expanduser('~/Desktop/BaseAgent')
CARDIO_KB_DIR = os.path.expanduser('~/Desktop/Cardio-KB')
MCP_CONFIG = f"{BASEAGENT_DIR}/examples/mcp_config.yaml"
SKILLS_DIR = f"{BASEAGENT_DIR}/skills"

# Create engineer agent for DrugBank parser
engineer_agent = BaseAgent(
    skills_directory=SKILLS_DIR,
    spec=AgentSpec(
        name="engineer_agent",
        role=(
            f"A Python software engineer writing parsers under {CARDIO_KB_DIR}/src/parsers/. "
            f"Each parser inherits from BaseParser and downloads data from one biomedical source, "
            f"returning clean pandas DataFrames. Follow the full registration checklist: "
            f"{CARDIO_KB_DIR}/src/parsers/__init__.py and {CARDIO_KB_DIR}/src/main.py PARSERS dict. "
            f"Run `python {CARDIO_KB_DIR}/src/main.py --source <name>` to verify each parser produces TSVs. "
            f"Never hardcode any disease-specific values in the parser code. "
            f"Never hardcode any credentials."
            f"Never modify OWL files or ontology_mappings.yaml."
        ),
        llm="azure-claude-sonnet-4-6",
        skill_names=["parser-protocol"],
    ),
    require_approval="never",
)
engineer_agent.add_mcp(MCP_CONFIG)

print("Engineer agent created!")

# Task for DrugBank parser
task = f"""
Create a NEW DrugBank parser from scratch for CardioKB at {CARDIO_KB_DIR}.

DrugBank provides comprehensive drug information including:
- Drug names, descriptions, and identifiers
- Drug-gene interactions (targets, enzymes, transporters, carriers)
- Drug-drug interactions
- Drug categories and classifications

Requirements:
1. Create {CARDIO_KB_DIR}/src/parsers/drugbank_parser.py that inherits from BaseParser
2. The parser should:
   - Download DrugBank XML data (or use existing data in {CARDIO_KB_DIR}/data/raw/drugbank/)
   - Parse drug information: drugbank_id, name, description, cas_number, groups
   - Parse drug-gene interactions: drug binds gene relationships
   - Output TSVs to {CARDIO_KB_DIR}/data/processed/drugbank/
3. Register the parser in {CARDIO_KB_DIR}/src/parsers/__init__.py
4. Add entry to databases.yaml config
5. Add ontology mappings to {CARDIO_KB_DIR}/config/ontology_mappings.yaml for:
   - Drug nodes
   - drugBindsGene relationships
6. Test by running: python {CARDIO_KB_DIR}/src/main.py --source drugbank

Output the generated TSV files and report the counts.
"""

print("Running engineer agent for DrugBank parser...")
_log, result = engineer_agent.run(task, thread_id="drugbank_parser")
print("\n" + "="*80)
print("RESULT:")
print("="*80)
print(result[1] if isinstance(result, tuple) else result)
