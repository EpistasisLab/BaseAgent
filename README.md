# BaseAgent

A multi-agent AI system that autonomously builds disease-specific knowledge graphs. Given a disease scope and a template codebase, a team of specialist agents — ontology engineer, database curator, parser writer, mapping specialist, and evaluator — collaborates to produce a Memgraph-compatible, OWL-guided knowledge graph for your disease of interest.

## What it does

BaseAgent takes a disease (e.g., Alzheimer's disease, cardiovascular disease) and:

1. Configures the ontology and project scope for the target disease
2. Enables relevant biomedical databases (DisGeNET, PharmGKB, ClinicalTrials.gov, and more)
3. Writes and verifies data parsers for each enabled source
4. Maps parsed data to OWL node and edge types
5. Generates Cypher import scripts and CSV files for Memgraph

See [alzkb.ipynb](alzkb.ipynb) and [parkinson.ipynb](parkinson.ipynb) for end-to-end examples.

## Features

- 🤖 **Flexible LLM Support** - Works with OpenAI, Anthropic, Google Gemini, AWS Bedrock, Groq, and custom providers
- 🔧 **Dynamic Tool Integration** - Easy-to-use tool registration and management system
- 📊 **Resource Management** - Built-in management for tools, data lakes, and software libraries
- 🔄 **MCP Server Integration** - Support for Model Context Protocol servers (local stdio + remote Streamable HTTP with auth headers)
- 🧠 **State Management** - Powered by LangGraph for complex agent workflows
- 📈 **Usage Tracking** - Built-in metrics for token usage and cost monitoring
- 🔍 **Tool Retrieval** - Intelligent tool selection based on task requirements
- 💾 **Persistent Checkpointing** - SQLite-backed state persistence across sessions; resume tasks after process restart
- 🛑 **Human-in-the-Loop** - Pause before code execution for review; approve or reject with feedback
- 🔒 **REPL Namespace Isolation** - Each agent instance owns an isolated Python execution namespace; concurrent agents cannot corrupt each other's variables or plots
- 🔗 **Subgraph Extraction** - `get_subgraph()` returns an uncompiled `StateGraph` for embedding in parent LangGraph workflows (multi-agent composition)
- 🤝 **Multi-Agent Orchestration** - `AgentTeam` coordinates multiple specialist agents via a supervisor LLM that routes dynamically between agents

## Requirements

- Python 3.12+
- An LLM API key (Anthropic, OpenAI, Azure, or Google)
- The [alzkb-updater](https://github.com/BinglanLi/alzkb-updater) template repo cloned locally — the example notebooks and `examples/13_disease_kg.py` expect it at `~/GitHub/alzkb-updater`

## Installation

```bash
git clone https://github.com/BinglanLi/BaseAgent.git
cd BaseAgent
uv pip install -e .
```

### Knowledge graph dependencies

To build disease-specific knowledge graphs, install the `kg` dependency group and [ista](https://github.com/RomanoLab/ista):

```bash
# Install kg group (bioinformatics + database libraries)
uv sync --group kg

# Clone and install ista (knowledge graph statistics)
git clone --recurse-submodules --branch v0.1.1 https://github.com/RomanoLab/ista .ista
uv pip install -e .ista
# alternative: CXXFLAGS="-I/opt/homebrew/opt/mysql-client/include" uv pip install -e .ista
```

## Quick Start

**Option 1 — command line** (runs Parkinson's disease by default; edit the script to change the disease):

```bash
export ANTHROPIC_API_KEY=your_key
python examples/13_disease_kg.py
```

**Option 2 — Jupyter notebook**:

- **[alzkb.ipynb](alzkb.ipynb)** — Alzheimer's disease knowledge graph
- **[cardiokb.ipynb](cardiokb.ipynb)** — Cardiovascular disease knowledge graph

Both walk through assembling a team of specialist agents and running them end-to-end with human-in-the-loop review checkpoints.

> **MCP filesystem access**: agents read and write the KG repo via the filesystem MCP server configured in `examples/mcp_config.yaml`. Open that file and set the `root` path to your template repo before running.

## Agent Team

A typical build uses these specialist agents coordinated by a supervisor LLM:

| Agent | Role |
|---|---|
| `ontology_agent` | Configures OWL schema and disease scope in `config/project.yaml` |
| `database_agent` | Enables relevant sources in `config/databases.yaml` |
| `engineer_agent` | Writes and validates data parsers in `src/parsers/` |
| `mapping_agent` | Maps parsed columns to OWL node/edge types in `config/ontology_mappings.yaml` |
| `memgraph_agent` | Runs the full pipeline and validates the Cypher export |
| `evaluator_agent` | Runs evaluation scripts and flags tier-1 failures |
| `hitl_agent` | Calls `ask_user` to surface agent summaries and relay user feedback |

Each agent is a `BaseAgent` instance loaded with a domain-specific skill (e.g., `parser-protocol`, `ontology-protocol`) from the `skills/` directory.

## Configuration

Set your LLM provider key:

```bash
# Choose one
export ANTHROPIC_API_KEY=your_key
export OPENAI_API_KEY=your_key
export GOOGLE_API_KEY=your_key
```

For Azure Foundry deployments, see the environment variable reference in `BaseAgent/config.py`.

## Development

```bash
# Run tests (no API key needed)
cd BaseAgent/tests && pytest -m "not integration"

# Format and lint
black BaseAgent/
ruff check BaseAgent/
```

Architecture and module documentation lives in `.claude/`.

## License

MIT — see [LICENSE](LICENSE).

## Acknowledgments

Built with [LangChain](https://github.com/langchain-ai/langchain) and [LangGraph](https://github.com/langchain-ai/langgraph).
Inspired by the [Biomni](https://github.com/openbmb/Biomni) project.
