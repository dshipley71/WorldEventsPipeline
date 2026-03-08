# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

World Events MCP Server — 89 tools across 30+ domains providing real-time global intelligence from free public APIs. Serves two interfaces: MCP stdio (for Claude Code/Cursor) and a Click CLI with Rich output. Python 3.11+, built with hatchling.

## Commands

```bash
# Install
pip install -e ".[dev]"

# Run MCP server (stdio mode)
world-events-mcp

# Run tests (pytest-asyncio, auto mode)
pytest
pytest --cov=world_events_mcp
pytest src/world_events_mcp/tests/test_sources.py::test_fetch_market_quotes -v  # single test

# CLI
intel markets                    # stock indices
intel earthquakes --min-mag 5.0  # USGS quakes
intel status                     # cache + circuit breaker health
```

## Architecture

Two consumers share the same source modules and infrastructure stack:

```
server.py (MCP stdio)  ─┐
cli.py (Click CLI)      ─┘─> sources/*.py ─> Fetcher ─> CircuitBreaker ─> Cache (SQLite)
                                                                   ~/.cache/world-events-mcp/cache.db
```

**Infrastructure layer** (`fetcher.py`, `cache.py`, `circuit_breaker.py`):
- `Fetcher`: Centralized async HTTP client (httpx). All external calls go through `get_json()`, `get_text()`, or `get_xml()`. Handles retries (2 max), per-source rate limiting, and stale-data fallback (never returns blank if old data exists).
- `CircuitBreaker`: Per-source tracking. 3 consecutive failures trips the breaker for 5 minutes. Each RSS feed gets its own breaker (`rss:bbc_world`).
- `Cache`: SQLite WAL-mode TTL cache. `get()` returns live data, `get_stale()` returns expired data for fallback.

**Source modules** (`sources/*.py`): Each module exports `async def fetch_*(fetcher: Fetcher, **kwargs) -> dict`. Pure data fetching — no MCP awareness. 30 modules covering markets, seismology, military, cyber, health, tech, environmental, etc. The `news` module includes `fetch_gdelt_search` with 8 output modes (artlist, 5 timelines, tonechart, timelinevolinfo), sort, date-range (STARTDATETIME/ENDDATETIME), and convenience filters for sourcelang, sourcecountry, and GKG theme.

**Analysis modules** (`analysis/*.py`): Cross-domain intelligence that consumes outputs from multiple sources. Includes signal aggregation, instability indexing, NLP (entity extraction, classification, clustering, spike detection via Welford's algorithm), and strategic synthesis.

**Static config** (`config/*.py`): Curated datasets — 22 intel hotspots, 70+ military bases, 40 ports, 24 pipelines, 24 nuclear facilities, 34 undersea cables, 48 AI datacenters, 27 spaceports, 27 mineral deposits, 82 stock exchanges, 105 major cities, 28 world leaders, 36 APT groups.

## Adding a New Tool

1. Create `sources/your_source.py` with `async def fetch_your_data(fetcher: Fetcher, **kwargs) -> dict`
2. Use `fetcher.get_json(url, source="your-source", cache_key=..., cache_ttl=300)` — this gives you caching, retries, circuit breaking, and rate limiting automatically
3. In `server.py`: import the module, add a `Tool(...)` to the `TOOLS` list, add a `case` to `_dispatch()`
4. Optionally add a CLI command to `cli.py`
5. Add tests using `respx` to mock HTTP (see `tests/test_sources.py` for pattern)

## Key Patterns

- **Source name string**: The `source` parameter in `fetcher.get_json()` identifies the API for circuit breaking and rate limiting. Must match entries in `_SOURCE_RATE_LIMITS` if rate-limited (e.g., `"yahoo-finance"`, `"coingecko"`, `"adsblol"`).
- **Tool dispatch**: `server.py` uses Python `match/case` to route tool names to source functions. Tool names follow `intel_*` convention.
- **All source functions take `fetcher` as first arg** — never construct your own httpx client.
- **Tests strip proxy env vars** automatically via `conftest.py` fixture (prevents SOCKS proxy interference). The conftest also resets global fetcher rate-limit locks between tests to avoid cross-event-loop binding.

## Environment Variables

Optional configuration (all data sources work without any API keys):
- `OLLAMA_API_URL` — local Ollama LLM URL (default: `http://localhost:11434`)
- `OLLAMA_MODEL` — Ollama model to use (default: `llama3.2`)
- `WORLD_INTEL_LOG_LEVEL` — log level (default: `INFO`)
- `WORLD_INTEL_GDELT_MIN_INTERVAL` — minimum seconds between GDELT requests (default: `6.0`)
- `WORLD_INTEL_FETCHER_TIMEOUT` — HTTP timeout in seconds (default: `15.0`)
- `WORLD_INTEL_FETCHER_MAX_RETRIES` — max HTTP retries (default: `2`)

## Testing

Tests use `respx` to mock httpx responses. Fixtures in `conftest.py` provide `cache` (tmp_path SQLite) and `fetcher` (with clean breaker). Tests are async (`pytest-asyncio` in auto mode). Proxy env vars are stripped automatically.
