# AGENTS.md — World-Events Pipeline Agent Reference

> **Audience:** Claude Code (agentic), human developers, and CI pipelines.
> This file is the authoritative reference for every agent in the pipeline.
> Keep it in sync with any changes to `world_events/agents/`.

---

## Pipeline Overview

```
QueryInputAgent
    │
    ▼
NewsSearchAgent          ← GDELT artlist (MCP-first, HTTP fallback)
    │
    ▼
TimelineAnalysisAgent    ← timelinevol + timelinevolraw + timelinetone
    │
    ▼
SpikeDetectionAgent      ← z-score on raw volume
    │
    ▼
EventCorrelationAgent    ← RSS fetch → time-window gate → MiniLM semantic rank
    │
    ▼
GDELTReRankAgent         ← MiniLM re-rank of GDELT articles by query similarity
    │
    ▼
GDELTArticleSummaryAgent ← per-article LLM summaries (Ollama Cloud)
    │
    ▼
MCPEnrichmentAgent       ← keyword spikes + news clusters + entity extraction (parallel)
    │
    ▼
CrossSourceReviewAgent   ← cited intelligence review (LLM, token-budgeted)
    │
    ▼
NarrativeSynthesisAgent  ← summary text + risk label
    │
    ▼
PlottingAgent            ← 4-panel Matplotlib dashboard → PNG + base64
    │
    ▼
StructuredOutputAgent    ← full JSON output → state.output_json
```

All agents implement `BaseAgent` from `world_events/agents/base.py`:

```python
class BaseAgent:
    name: str
    async def run(self, session: ClientSession, state: PipelineState) -> None: ...
```

---

## Agent Reference

### 1. `QueryInputAgent`
**File:** `world_events/agents/query_input.py`

Strips and validates `state.query`. Raises `ValueError` for empty queries.

**Reads:** `state.query`  
**Writes:** `state.query` (normalised)  
**Fails hard on:** empty query string

---

### 2. `NewsSearchAgent`
**File:** `world_events/agents/news_search.py`

Fetches GDELT articles via `intel_gdelt_search` MCP tool (`mode=artlist`).

**Strategy:**
1. Call MCP tool with throttle/retry (`rate_limiter.call_gdelt_tool_with_backoff`).
2. If MCP returns 0 articles, sleep 8 s then fall back to direct GDELT HTTP.
3. If `params.use_mcp_for_gdelt=False`, skip MCP entirely.

**Reads:** `state.query`, `state.params.{gdelt_limit, use_mcp_for_gdelt, ...}`  
**Writes:** `state.gdelt_articles: List[Article]`  
**MCP tool:** `intel_gdelt_search`  
**Rate limiter:** shared `state.gdelt_limiter`

---

### 3. `TimelineAnalysisAgent`
**File:** `world_events/agents/timeline_analysis.py`

Fetches three GDELT timeline modes and merges them into `TimelinePoint` objects.

| Mode | Meaning |
|------|---------|
| `timelinevol` | Normalised volume intensity |
| `timelinevolraw` | Raw article count |
| `timelinetone` | Average tone score |

**Strategy:** MCP-first for each mode; direct HTTP fallback on `None` response.

**Reads:** `state.query`, `state.params.{timespan, use_mcp_for_gdelt, ...}`  
**Writes:** `state.timeline: List[TimelinePoint]`  
**MCP tool:** `intel_gdelt_search`

---

### 4. `SpikeDetectionAgent`
**File:** `world_events/agents/spike_detection.py`

Z-score spike detection on `raw_volume` values from `state.timeline`.

**Algorithm:**
1. Compute mean and sample std of non-null raw volumes.
2. Any point where `z > params.spike_threshold` becomes a `Spike`.
3. Requires ≥ 3 timeline points; std=0 → no spikes.

**Reads:** `state.timeline`, `state.params.spike_threshold`  
**Writes:** `state.spikes: List[Spike]`  
**No MCP / LLM dependency**

---

### 5. `EventCorrelationAgent`
**File:** `world_events/agents/event_correlation.py`

Fetches RSS articles via `intel_news_feed` MCP tool, applies spike time-window
gating, then runs MiniLM semantic ranking.

**Time-window logic:**
- Spikes present → build windows of `[spike_date ± window_days]`.
- No spikes, timeline present → window spans full timeline ± `window_days`.
- Neither → last 7 days.

**Semantic ranking** (`embeddings.semantic_rank_rss`):
- Score = `0.65 × query_sim + 0.35 × gdelt_context_sim`
- Threshold: `params.semantic_min_score` (default 0.35)
- Kept: top `params.semantic_top_k` (default 20)

When `params.semantic_rss_enabled=False`, takes raw first `rss_limit` articles.

**Reads:** `state.{query, spikes, timeline, gdelt_articles, params}`  
**Writes:** `state.rss_articles: List[Article]`  
**MCP tool:** `intel_news_feed`

---

### 6. `GDELTReRankAgent`
**File:** `world_events/agents/gdelt_rerank.py`

Re-ranks `state.gdelt_articles` by MiniLM cosine similarity to `state.query`.

**Must run before** `GDELTArticleSummaryAgent` so that:
- LLM summaries cover only the top-k most relevant articles.
- `CrossSourceReviewAgent` receives a pre-filtered list.

Skips silently when `params.gdelt_rerank_enabled=False`.

**Reads:** `state.{query, gdelt_articles, params.gdelt_rerank_{enabled,top_k,...}}`  
**Writes:** `state.gdelt_articles` (replaced with top-k re-ranked subset)  
**Embedding helper:** `embeddings.semantic_rerank_gdelt`

---

### 7. `GDELTArticleSummaryAgent`
**File:** `world_events/agents/gdelt_summary.py`

Generates a 1–3 sentence LLM summary for each of the top `llm_max_articles`
GDELT articles, stored in `article.raw["llm_summary"]`.

**Prompt fields:** domain, language, published, title, snippet, url.  
**LLM options:** `num_predict=120` (≈ 3 sentences max).  
**Timeout:** `params.llm_timeout_seconds` per article.  
**Skips** when `OLLAMA_API_KEY` is absent or `params.llm_enabled=False`.

**Reads:** `state.{gdelt_articles, params.llm_*}`  
**Writes:** `article.raw["llm_summary"]` for each processed article  
**LLM:** Ollama Cloud (see `world_events/llm.py`)

---

### 8. `MCPEnrichmentAgent`
**File:** `world_events/agents/mcp_enrichment.py`

Calls three MCP tools **in parallel** (`asyncio.gather`) to enrich state with
statistical and NLP context before the cross-source review.

| Tool | Purpose | Stored in |
|------|---------|-----------|
| `intel_keyword_spikes` | Keyword z-score / ratio surges | `state.mcp_keyword_spikes` |
| `intel_news_clusters` | Jaccard topic clusters from RSS | `state.mcp_news_clusters` |
| `intel_extract_entities` | Regex-NER on GDELT titles | `state.mcp_entities` |

All three calls are **fire-and-forget**: `Exception`s are logged but never
propagate. The pipeline continues even if all three fail.

Skips entirely when `params.mcp_enrichment_enabled=False`.

**Reads:** `state.{gdelt_articles, params.{category, mcp_enrichment_*}}`  
**Writes:** `state.{mcp_keyword_spikes, mcp_news_clusters, mcp_entities}`  
**MCP tools:** `intel_keyword_spikes`, `intel_news_clusters`, `intel_extract_entities`

---

### 9. `CrossSourceReviewAgent`
**File:** `world_events/agents/cross_source_review.py`

The core intelligence synthesis agent. Produces a cited, structured review
grounded exclusively in the provided source cards.

**Source selection (static caps — never inflated during spikes):**

| Pool | Hard cap |
|------|----------|
| GDELT sources | 16 |
| RSS sources | 8 |
| Total | 24 |

**Source selection logic:**
- Spikes present → prefer articles in `[spike_date ± window_days]`; pad to cap
  if fewer than 6 GDELT / 3 RSS match.
- No spikes → first N of each pool.

**Content mode** (`params.cross_source_content_mode`):
- `"llm_summary"` (default): use `article.raw["llm_summary"]` if ≥ `min_llm_summary_chars`; else fall back to raw snippet.
- `"content"`: always use raw snippet/content.

**Token budget:** 80 000 estimated tokens (3 chars/token).  
**LLM options:** `num_predict=1500`.  
**2-pass narrowing:** if prompt is too long, a lightweight title manifest is sent
to a selector LLM call (≤ 200 tokens output) to pick ≤ 12 sources, then the
full review runs on the narrowed set.

**Output JSON schema (from LLM):**
```json
{"review": "...", "sources_used": ["S001", "S003"]}
```

**Enrichment context** (from MCPEnrichmentAgent) is injected into the prompt
as a `ENRICHMENT CONTEXT` block for statistical grounding.

**Reads:** `state.{gdelt_articles, rss_articles, spikes, mcp_*, params}`  
**Writes:** `state.{cross_source_review, cross_source_review_sources}`  
**LLM:** Ollama Cloud  
**Skips** when LLM unavailable

---

### 10. `NarrativeSynthesisAgent`
**File:** `world_events/agents/narrative_synthesis.py`

Produces a one-line human-readable summary and a simple risk label.

| Spike count | Risk label |
|-------------|-----------|
| 0 | `low` |
| 1–2 | `moderate` |
| ≥ 3 | `high` |

**Reads:** `state.{query, spikes, gdelt_articles, rss_articles}`  
**Writes:** `state.{analysis_summary, risk_assessment}`  
**No MCP / LLM dependency**

---

### 11. `PlottingAgent`
**File:** `world_events/agents/plotting.py`

Renders a 4-panel Matplotlib intelligence dashboard:

1. **Volume Intensity** (`timelinevol`)
2. **Raw Article Volume** (`timelinevolraw`)
3. **Tone** (`timelinetone`, with zero-line)
4. **Spike Overlay** (raw volume + threshold line + spike scatter)

Saves PNG to disk and base64-encodes it for embedding.  
Calls `IPython.display.display()` when running in Jupyter/Colab.  
Silently skips when `state.timeline` is empty.

**Default output path:** `/content/timeline_analysis_plots.png`  
Override by passing `output_path=` to the constructor.

**Reads:** `state.{timeline, spikes, params.spike_threshold, query}`  
**Writes:** `state.{plot_png_path, plot_png_base64, plot_data}`  
**Requires:** `matplotlib`

---

### 12. `StructuredOutputAgent`
**File:** `world_events/agents/structured_output.py`

Serialises the entire pipeline state to a single JSON document and stores it
in `state.output_json`. The orchestrator prints it **after** restoring stdout
so the output appears in the Jupyter/Colab cell.

**Output schema (top-level keys):**
```
query, parameters, timeline[], spikes[], articles{gdelt[], rss[]},
analysis{summary, risk_assessment, cross_source_review, cross_source_review_sources[]},
mcp_enrichment{keyword_spikes[], news_clusters[], entities{}},
artifacts{plot_png_path, plot_png_base64, plot_data{}}
```

**Reads:** entire `PipelineState`  
**Writes:** `state.output_json: str`

---

## State Flow Diagram

```
PipelineState fields populated by each agent:

query (validated)                  ← QueryInputAgent
gdelt_articles                     ← NewsSearchAgent
timeline                           ← TimelineAnalysisAgent
spikes                             ← SpikeDetectionAgent
rss_articles                       ← EventCorrelationAgent
gdelt_articles (re-ranked)         ← GDELTReRankAgent
article.raw["llm_summary"]         ← GDELTArticleSummaryAgent
mcp_keyword_spikes                 ← MCPEnrichmentAgent
mcp_news_clusters                  ← MCPEnrichmentAgent
mcp_entities                       ← MCPEnrichmentAgent
cross_source_review                ← CrossSourceReviewAgent
cross_source_review_sources        ← CrossSourceReviewAgent
analysis_summary, risk_assessment  ← NarrativeSynthesisAgent
plot_png_path, plot_png_base64     ← PlottingAgent
plot_data                          ← PlottingAgent
output_json                        ← StructuredOutputAgent
```

---

## Adding a New Agent

1. Create `world_events/agents/my_agent.py` inheriting `BaseAgent`.
2. Implement `async def run(self, session, state) -> None`.
3. Export it from `world_events/agents/__init__.py`.
4. Insert it at the correct position in `WorldEventsOrchestrator._build_agent_sequence()`.
5. Document it in this file under the appropriate step number.
6. Write unit tests in `tests/test_my_agent.py`.

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `OLLAMA_API_KEY` | *(required for LLM steps)* | Ollama Cloud bearer token |
| `OLLAMA_HOST` | `https://ollama.com` | Override Ollama endpoint |
| `OLLAMA_MODEL` | `gemma3:27b` | Override model name |

API key is also readable from **Google Colab Secrets** (`OLLAMA_API_KEY`).

---

## MCP Tools Used

| MCP Tool | Agent(s) | Purpose |
|----------|---------|---------|
| `intel_gdelt_search` | NewsSearchAgent, TimelineAnalysisAgent | GDELT artlist + timelines |
| `intel_news_feed` | EventCorrelationAgent | RSS feed fetch |
| `intel_keyword_spikes` | MCPEnrichmentAgent | Trending keyword detection |
| `intel_news_clusters` | MCPEnrichmentAgent | Topic cluster grouping |
| `intel_extract_entities` | MCPEnrichmentAgent | NER on article text |

---

## Testing

```bash
# All tests
pytest tests/ -v

# Specific modules
pytest tests/test_models_and_utils.py -v
pytest tests/test_spike_detection.py -v

# With coverage
pytest tests/ --cov=world_events --cov-report=term-missing
```

Tests are isolated from MCP and LLM dependencies using `unittest.mock`.
