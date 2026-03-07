# World-Events Pipeline

A modular, production-grade **multi-agent geopolitical intelligence pipeline**
built on GDELT DOC 2.0, RSS feeds, MCP tool servers, and Ollama Cloud LLMs.

---

## Features

- **GDELT integration** — artlist, timelinevol, timelinevolraw, timelinevolinfo, timelinetone, timelinesourcecountry, timelinelang, tonechart (MCP-first with direct HTTP fallback)
- **Statistical spike detection** — z-score analysis on raw article volume
- **MiniLM semantic ranking** — re-ranks both GDELT and RSS articles by query relevance
- **Parallel MCP enrichment** — keyword spikes, topic clusters, NER entity extraction
- **LLM intelligence synthesis** — per-article summaries + cited cross-source review (Ollama Cloud)
- **4-panel Matplotlib dashboard** — volume intensity, raw count, tone, spike overlay
- **Structured JSON output** — full pipeline state serialised for downstream consumption
- **Jupyter/Colab compatible** — handles ipykernel stdout/stderr limitations

---

## Quick Start

### Installation

```bash
git clone https://github.com/your-org/world-events-pipeline
cd world-events-pipeline
pip install -r requirements.txt
```

### CLI usage

```bash
export OLLAMA_API_KEY="your-key-here"

python scripts/run_pipeline.py "ICE Protests"
python scripts/run_pipeline.py --gdelt-direct-only "Taiwan Strait"
python -m world_events "South China Sea"
```

### Jupyter / Colab

```python
import os
os.environ["OLLAMA_API_KEY"] = "your-key-here"   # or use Colab Secrets

from world_events.orchestrator import WorldEventsOrchestrator
orch = WorldEventsOrchestrator()
state = await orch.run_query("ICE Protests")
```

---

## Architecture

See [`AGENTS.md`](AGENTS.md) for the full per-agent reference.

```
QueryInput → NewsSearch → TimelineAnalysis → SpikeDetection
    → EventCorrelation → GDELTReRank → GDELTSummary
    → MCPEnrichment → CrossSourceReview → NarrativeSynthesis
    → Plotting → StructuredOutput
```

All agents share a `PipelineState` blackboard and are sequenced by
`WorldEventsOrchestrator`. Agents are independently testable without
MCP or LLM connectivity.

---

## Configuration

All parameters live in `world_events/config.py` (`PipelineParameters`).
Key settings:

| Parameter | Default | Description |
|-----------|---------|-------------|
| `timespan` | `14d` | GDELT query window |
| `spike_threshold` | `2.0` | Z-score threshold for spikes |
| `gdelt_limit` | `100` | Max GDELT articles per call |
| `semantic_min_score` | `0.35` | MiniLM min similarity for RSS |
| `llm_model` | `gemma3:27b` | Ollama model name |
| `cross_source_content_mode` | `llm_summary` | Use LLM summaries or raw snippets |

Override at runtime:

```python
from world_events.models import PipelineState
state = PipelineState(query="my query")
state.params.spike_threshold = 1.5
state.params.timespan = "7d"
```

---

## Environment Variables

| Variable | Description |
|----------|-------------|
| `OLLAMA_API_KEY` | Ollama Cloud bearer token (required for LLM steps) |
| `OLLAMA_HOST` | Override Ollama endpoint (default: `https://ollama.com`) |
| `OLLAMA_MODEL` | Override model name (default: `gemma3:27b`) |

---

## MCP Server

The pipeline connects to a `world-events-mcp` MCP server on `$PATH`.
Override the command name:

```python
orch = WorldEventsOrchestrator(server_command="my-custom-mcp")
```

### MCP tools used

| Tool | Purpose |
|------|---------|
| `intel_gdelt_search` | GDELT artlist, all timeline modes, tonechart, with sort, date range, source country/lang/theme filters |
| `intel_news_feed` | RSS article fetch |
| `intel_keyword_spikes` | Trending keyword detection |
| `intel_news_clusters` | Topic cluster grouping |
| `intel_extract_entities` | Named entity recognition |

---

## Testing

```bash
pip install pytest pytest-asyncio
pytest tests/ -v
```

---

## Project Structure

```
world-events-pipeline/
├── AGENTS.md              # agent-by-agent reference
├── CLAUDE.md              # Claude Code guidance
├── README.md
├── requirements.txt
├── pyproject.toml
├── world_events/
│   ├── config.py          # PipelineParameters
│   ├── models.py          # data models
│   ├── logging_utils.py   # log() helper
│   ├── utils.py           # pure utilities
│   ├── rate_limiter.py    # AsyncRateLimiter + GDELT wrappers
│   ├── embeddings.py      # MiniLM semantic ranking
│   ├── llm.py             # Ollama client factory
│   ├── orchestrator.py    # WorldEventsOrchestrator
│   └── agents/            # 12 pipeline agents
├── scripts/
│   └── run_pipeline.py    # CLI entry point
└── tests/
    ├── test_models_and_utils.py
    └── test_spike_detection.py
```

---

## License

MIT
