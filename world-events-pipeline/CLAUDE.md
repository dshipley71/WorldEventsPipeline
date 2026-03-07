# CLAUDE.md — World-Events Pipeline

> This file guides Claude Code when working in this repository.
> Read it before making any code changes.

---

## Repository Map

```
world-events-pipeline/
├── AGENTS.md                    ← agent-by-agent reference (read this!)
├── CLAUDE.md                    ← this file
├── README.md                    ← end-user docs
├── requirements.txt
├── pyproject.toml
│
├── world_events/                 ← main package
│   ├── __init__.py              ← public API re-exports
│   ├── __main__.py              ← python -m world_events entry
│   ├── config.py                ← PipelineParameters dataclass
│   ├── models.py                ← Article, PipelineState, Spike, TimelinePoint
│   ├── logging_utils.py         ← log() helper (Rich + ANSI fallback)
│   ├── utils.py                 ← pure utility functions (no agent deps)
│   ├── rate_limiter.py          ← AsyncRateLimiter + GDELT backoff wrappers
│   ├── embeddings.py            ← MiniLM model + semantic_rank_rss / semantic_rerank_gdelt
│   ├── llm.py                   ← get_ollama_client() factory
│   ├── orchestrator.py          ← WorldEventsOrchestrator (agent sequencing)
│   └── agents/
│       ├── __init__.py          ← re-exports all agent classes
│       ├── base.py              ← BaseAgent
│       ├── query_input.py
│       ├── news_search.py
│       ├── timeline_analysis.py
│       ├── spike_detection.py
│       ├── event_correlation.py
│       ├── gdelt_rerank.py
│       ├── gdelt_summary.py
│       ├── mcp_enrichment.py
│       ├── cross_source_review.py
│       ├── narrative_synthesis.py
│       ├── plotting.py
│       └── structured_output.py
│
├── scripts/
│   └── run_pipeline.py          ← CLI entry point
│
└── tests/
    ├── test_models_and_utils.py
    └── test_spike_detection.py
```

---

## Core Principles

### 1. Agent Ordering is Dependency-Driven

The pipeline in `orchestrator.py` runs agents in a fixed sequence.
**Do not reorder** without checking the data flow diagram in `AGENTS.md`.

Critical ordering constraints:
- `GDELTReRankAgent` **before** `GDELTArticleSummaryAgent` — summaries must
  cover the re-ranked articles that `CrossSourceReviewAgent` will select.
- `MCPEnrichmentAgent` **before** `CrossSourceReviewAgent` — enrichment context
  is injected into the review prompt.

### 2. PipelineState is the Shared Blackboard

All agents read from and write to `PipelineState` (defined in `models.py`).
Never pass data between agents through return values — always update state.

### 3. No Circular Imports

Import hierarchy (top → bottom, no upward imports):

```
config.py
    ↓
models.py
    ↓
logging_utils.py  utils.py  rate_limiter.py  embeddings.py  llm.py
    ↓
agents/base.py
    ↓
agents/{individual agents}
    ↓
agents/__init__.py
    ↓
orchestrator.py
```

### 4. TYPE_CHECKING Guards for Forward References

When an agent needs to reference `PipelineState` or `ClientSession` in type
annotations only, use:

```python
from __future__ import annotations
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from mcp import ClientSession
    from world_events.models import PipelineState
```

This avoids circular import issues at runtime.

### 5. Agents Must Be Independently Testable

- No agent should require a live MCP connection or LLM to be unit-tested.
- Use `unittest.mock.MagicMock()` for `session` and `AsyncMock` for async calls.
- See `tests/test_spike_detection.py` as the canonical example.

---

## Common Tasks

### Run the full pipeline (CLI)
```bash
python scripts/run_pipeline.py "Taiwan Strait tensions"
python scripts/run_pipeline.py --gdelt-direct-only "South China Sea"
python -m world_events "ICE Protests"
```

### Run from Jupyter/Colab
```python
from world_events.orchestrator import WorldEventsOrchestrator
orch = WorldEventsOrchestrator()
state = await orch.run_query("ICE Protests")
```

### Run tests
```bash
pip install pytest pytest-asyncio
pytest tests/ -v
```

### Add a new agent
1. Create `world_events/agents/my_agent.py` — inherit `BaseAgent`.
2. Implement `async def run(self, session, state) -> None`.
3. Add to `world_events/agents/__init__.py` exports.
4. Insert at the correct position in `WorldEventsOrchestrator._build_agent_sequence()`.
5. Update `AGENTS.md` with full documentation.
6. Write tests in `tests/test_my_agent.py`.

### Tune pipeline behaviour
All tunable parameters live in `world_events/config.py` (`PipelineParameters`).
Override at runtime:

```python
state = PipelineState(query="...")
state.params.spike_threshold = 1.5
state.params.llm_max_articles = 30
```

---

## Rate Limiting & GDELT Quotas

- `params.gdelt_min_interval_seconds` (default 6.0) is enforced by `AsyncRateLimiter`
  before **every** GDELT call (MCP or direct).
- MCP calls share the same limiter instance (`state.gdelt_limiter`).
- Do not remove or bypass the rate limiter — GDELT will 429.

---

## LLM Integration

- Ollama Cloud bearer token read from `OLLAMA_API_KEY` env var or Colab Secrets.
- `get_ollama_client(state)` in `llm.py` returns `(client, model)` or `None`.
- All LLM calls are wrapped in `asyncio.wait_for(..., timeout=llm_timeout_seconds)`.
- Agents that call LLM must gracefully degrade when `client_model is None`.

---

## Token Budget (CrossSourceReviewAgent)

- Budget: **80 000** estimated tokens (3 chars/token — conservative for multilingual content).
- Static source caps: 16 GDELT + 8 RSS = 24 total (never inflated during spikes).
- 2-pass narrowing activates on "prompt too long" errors — selector uses a lightweight
  title manifest, not the full prompt.

---

## Key Fixes Applied in This Refactor

| Fix | Location |
|-----|----------|
| `GDELTReRankAgent` was declared but missing from agent sequence | `orchestrator.py` |
| Token estimator uses 3 chars/token (was 4 — underestimated by 20–40%) | `cross_source_review.py` |
| Static source caps (were inflated during spikes, causing context overflow) | `cross_source_review.py` |
| `llm_max_articles=24` aligned with `MAX_GDELT_SOURCES=16` + buffer | `config.py` |
| 2-pass selector now sends title manifest only (was full prompt — defeated the purpose) | `cross_source_review.py` |
| `asyncio.wait_for` timeout on every LLM call | `gdelt_summary.py`, `cross_source_review.py` |
| `semantic_debug_top_n: Optional[int]` (was invalid `int = None`) | `config.py` |
| `StructuredOutputAgent` stores to state; orchestrator prints after stdout restore | `structured_output.py`, `orchestrator.py` |
| Direct GDELT fallback on timeline modes (only artlist had it before) | `timeline_analysis.py` |

---

## Do Not

- Import from `orchestrator.py` inside any agent module.
- Use `print()` inside agents — always use `log()` from `logging_utils.py`.
- Skip the rate limiter for GDELT calls.
- Inflate source caps in `CrossSourceReviewAgent` during spike conditions.
- Store sensitive keys (API keys, tokens) in source files — use env vars.
