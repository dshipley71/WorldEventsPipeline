#!/usr/bin/env python3
"""
World Intelligence MCP Server — News Edition
=============================================

Three news intelligence tools powered by free public APIs (no API keys required):

  intel_news_feed        — RSS aggregation across 24 categories / 119 feeds
  intel_trending_keywords— Keyword spike detection from recent headlines
  intel_gdelt_search     — GDELT 2.0 Doc API: 65-language global news search
  intel_status           — Server health and cache statistics
"""

import asyncio
import json
import logging
import os
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from .cache import Cache
from .circuit_breaker import CircuitBreaker
from .fetcher import Fetcher
from .sources import news

logging.basicConfig(
    level=os.environ.get("WORLD_INTEL_LOG_LEVEL", "INFO"),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("world-events-mcp")

server = Server("world-events-mcp")
cache = Cache()
breaker = CircuitBreaker(failure_threshold=3, cooldown_seconds=300)

_fetcher_timeout = float(os.environ.get("WORLD_INTEL_FETCHER_TIMEOUT", "15.0"))
_fetcher_retries = int(os.environ.get("WORLD_INTEL_FETCHER_MAX_RETRIES", "2"))
fetcher = Fetcher(cache=cache, breaker=breaker, default_timeout=_fetcher_timeout, max_retries=_fetcher_retries)

# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

TOOLS: list[Tool] = [
    Tool(
        name="intel_news_feed",
        description=(
            "Get aggregated intelligence news from 119 RSS feeds across 24 categories. "
            "Covers geopolitics, security, tech, finance, military, science, think tanks, "
            "regional (middle_east, asia_pacific, africa, latin_america, europe, south_asia, "
            "central_asia, arctic), energy, government, crisis, maritime, space, nuclear, climate."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "categories": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": [
                            "geopolitics", "security", "technology", "finance", "military",
                            "science", "think_tanks", "middle_east", "asia_pacific", "africa",
                            "latin_america", "multilingual", "energy", "government", "crisis",
                            "europe", "south_asia", "health", "central_asia", "arctic",
                            "maritime", "space", "nuclear", "climate",
                        ],
                    },
                    "description": "Category filters. Omit to fetch all 24 categories.",
                },
                "limit": {"type": "integer", "description": "Max articles (default 50)", "default": 50},
            },
        },
    ),
    Tool(
        name="intel_gdelt_search",
        description=(
            "Search GDELT 2.0 Doc API across 65 languages of global news coverage. "
            "No API key required. Returns article lists, coverage volume timelines, "
            "tone analysis, and language/country breakdowns. "
            "Supports advanced query operators: phrase matching (\"north korea\"), "
            "boolean OR ((iran OR iraq)), exclusion (-sport), domain filter (domain:reuters.com), "
            "proximity (near20:\"missile launch\"), repeat (repeat3:\"sanctions\"), "
            "tone filter (tone<-5), theme (theme:TERROR), source language (sourcelang:zh), "
            "source country (sourcecountry:RS)."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query. Supports GDELT operators: \"phrase\", (a OR b), -exclude, domain:, domainis:, near20:, repeat3:, tone<-5, toneabs>10.",
                    "default": "conflict",
                },
                "mode": {
                    "type": "string",
                    "description": (
                        "Output mode:\n"
                        "  artlist              – list of matching articles (default)\n"
                        "  timelinevol          – coverage % of all global news by time step\n"
                        "  timelinevolraw       – raw article counts by time step\n"
                        "  timelinevolinfo      – timelinevol + top-10 articles driving each spike\n"
                        "  timelinetone         – average tone of coverage by time step\n"
                        "  timelinesourcecountry– coverage volume broken down by source country\n"
                        "  timelinelang         – coverage volume broken down by language\n"
                        "  tonechart            – emotional histogram (full tone distribution)"
                    ),
                    "enum": [
                        "artlist",
                        "timelinevol",
                        "timelinevolraw",
                        "timelinevolinfo",
                        "timelinetone",
                        "timelinesourcecountry",
                        "timelinelang",
                        "tonechart",
                    ],
                    "default": "artlist",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max records for artlist mode. Default 75, max 250.",
                    "default": 75,
                },
                "timespan": {
                    "type": "string",
                    "description": (
                        "Relative time window backwards from now. "
                        "Format: NNmin (e.g. '15min'), NNh ('6h'), NNd ('7d'), NNw ('2w'), NNm ('3m'). "
                        "Omit to use GDELT default (~3 months). "
                        "Mutually exclusive with startdatetime/enddatetime."
                    ),
                },
                "sort": {
                    "type": "string",
                    "description": (
                        "Sort order for artlist mode:\n"
                        "  DateDesc  – newest first (best for monitoring)\n"
                        "  DateAsc   – oldest first\n"
                        "  ToneAsc   – most negative first (threat monitoring)\n"
                        "  ToneDesc  – most positive first\n"
                        "  HybridRel – relevance + source popularity (default)"
                    ),
                    "enum": ["DateDesc", "DateAsc", "ToneDesc", "ToneAsc", "HybridRel"],
                },
                "startdatetime": {
                    "type": "string",
                    "description": "Precise search start in YYYYMMDDHHMMSS format (UTC). Must be within last 3 months.",
                },
                "enddatetime": {
                    "type": "string",
                    "description": "Precise search end in YYYYMMDDHHMMSS format (UTC). Must be within last 3 months.",
                },
                "sourcelang": {
                    "type": "string",
                    "description": "Filter to articles in this language. ISO 639 code (e.g. 'zh', 'ru', 'ar', 'es', 'fr').",
                },
                "sourcecountry": {
                    "type": "string",
                    "description": "Filter to press outlets in this country. FIPS-2 code (e.g. 'RS', 'CN', 'IR', 'US').",
                },
                "theme": {
                    "type": "string",
                    "description": "GDELT GKG theme for broad topic matching. Examples: TERROR, MILITARY, WMD, ELECTION_FRAUD, PROTEST, SANCTION, CYBER_ATTACK.",
                },
                "timelinesmooth": {
                    "type": "integer",
                    "description": "Moving-window smoothing steps for timeline modes (1–30).",
                },
            },
        },
    ),
    Tool(
        name="intel_gdelt_timeline",
        description=(
            "GDELT DOC 2.0 coverage timeline for one or two queries. "
            "Returns a time-series of news volume (%), raw counts, average tone, "
            "or per-country / per-language breakdowns — ready for charting. "
            "When two queries are supplied both series are returned in a single response "
            "so they can be overlaid on the same chart.\n\n"
            "Modes:\n"
            "  timelinevol          – % of global news coverage over time (default)\n"
            "  timelinevolraw       – raw article counts over time\n"
            "  timelinetone         – average tone (positive/negative) over time\n"
            "  timelinesourcecountry– volume broken down by publishing country\n"
            "  timelinelang         – volume broken down by language\n\n"
            "Timespan examples: '15min', '6h', '7d' (default), '2w', '1m', '3m'.\n"
            "Smoothing 1-30 reduces noise; higher values shift peaks slightly right."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Primary search query. Supports all GDELT operators.",
                    "default": "conflict",
                },
                "query2": {
                    "type": "string",
                    "description": "Optional second query for side-by-side comparison on the same timeline.",
                },
                "mode": {
                    "type": "string",
                    "description": "Timeline mode (see tool description).",
                    "enum": [
                        "timelinevol",
                        "timelinevolraw",
                        "timelinetone",
                        "timelinesourcecountry",
                        "timelinelang",
                    ],
                    "default": "timelinevol",
                },
                "timespan": {
                    "type": "string",
                    "description": "Lookback window: '15min', '6h', '7d' (default), '2w', '1m', '3m'.",
                    "default": "7d",
                },
                "smoothing": {
                    "type": "integer",
                    "description": "Moving-window smoothing steps 1–30 (default 3). Higher = smoother, slight rightward peak shift.",
                    "default": 3,
                },
                "sourcelang": {
                    "type": "string",
                    "description": "Restrict to articles in this language. ISO 639 code (e.g. 'zh', 'ru', 'ar').",
                },
                "sourcecountry": {
                    "type": "string",
                    "description": "Restrict to outlets in this country. FIPS-2 code (e.g. 'US', 'RS', 'CN').",
                },
                "theme": {
                    "type": "string",
                    "description": "GDELT GKG theme filter. Examples: TERROR, MILITARY, WMD, PROTEST, SANCTION.",
                },
                "startdatetime": {
                    "type": "string",
                    "description": "Precise start in YYYYMMDDHHMMSS UTC (overrides timespan). Max 3 months back.",
                },
                "enddatetime": {
                    "type": "string",
                    "description": "Precise end in YYYYMMDDHHMMSS UTC.",
                },
            },
            "required": ["query"],
        },
    ),
    Tool(
        name="intel_status",
        description="Get server health, circuit breaker status, cache statistics, and data source freshness.",
        inputSchema={"type": "object", "properties": {}},
    ),
]


# ---------------------------------------------------------------------------
# Tool dispatch
# ---------------------------------------------------------------------------

async def _dispatch(name: str, arguments: dict[str, Any]) -> Any:
    """Route tool call to the appropriate source function."""
    match name:
        case "intel_news_feed":
            return await news.fetch_news_feed(
                fetcher,
                categories=arguments.get("categories"),
                limit=arguments.get("limit", 50),
            )

        case "intel_gdelt_search":
            return await news.fetch_gdelt_search(
                fetcher,
                query=arguments.get("query", "conflict"),
                mode=arguments.get("mode", "artlist"),
                limit=arguments.get("limit", 75),
                timespan=arguments.get("timespan"),
                sort=arguments.get("sort"),
                startdatetime=arguments.get("startdatetime"),
                enddatetime=arguments.get("enddatetime"),
                sourcelang=arguments.get("sourcelang"),
                sourcecountry=arguments.get("sourcecountry"),
                theme=arguments.get("theme"),
                timelinesmooth=arguments.get("timelinesmooth"),
            )

        case "intel_gdelt_timeline":
            query = arguments.get("query", "conflict")
            query2 = arguments.get("query2")
            mode = arguments.get("mode", "timelinevol")
            timespan = arguments.get("timespan", "7d")
            smoothing = arguments.get("smoothing", 3)
            sourcelang = arguments.get("sourcelang")
            sourcecountry = arguments.get("sourcecountry")
            theme = arguments.get("theme")
            startdatetime = arguments.get("startdatetime")
            enddatetime = arguments.get("enddatetime")

            # Fetch primary series
            primary = await news.fetch_gdelt_search(
                fetcher,
                query=query,
                mode=mode,
                timespan=timespan if not startdatetime else None,
                startdatetime=startdatetime,
                enddatetime=enddatetime,
                sourcelang=sourcelang,
                sourcecountry=sourcecountry,
                theme=theme,
                timelinesmooth=smoothing,
            )

            result: dict = {
                "mode": mode,
                "timespan": timespan,
                "smoothing": smoothing,
                "series": [
                    {"query": query, "data": primary.get("timeline", [])}
                ],
                "source": "gdelt",
                "timestamp": primary.get("timestamp"),
            }

            # Optionally fetch second series for comparison
            if query2:
                secondary = await news.fetch_gdelt_search(
                    fetcher,
                    query=query2,
                    mode=mode,
                    timespan=timespan if not startdatetime else None,
                    startdatetime=startdatetime,
                    enddatetime=enddatetime,
                    sourcelang=sourcelang,
                    sourcecountry=sourcecountry,
                    theme=theme,
                    timelinesmooth=smoothing,
                )
                result["series"].append(
                    {"query": query2, "data": secondary.get("timeline", [])}
                )

            return result

        case "intel_status":
            all_breakers = breaker.status()
            # Only surface sources that have seen failures — keeps output clean
            # after fetching 100+ RSS feeds (all-healthy = empty dict)
            problem_breakers = {
                src: info for src, info in all_breakers.items()
                if info.get("total_failures", 0) > 0 or info.get("status") != "closed"
            }
            return {
                "sources_tracked": len(all_breakers),
                "problem_sources": len(problem_breakers),
                "circuit_breakers": problem_breakers,
                "cache": cache.stats(),
                "cache_freshness": cache.freshness(),
                "data_sources": {
                    "news": ["rss-aggregator (119 feeds, 24 categories)", "gdelt"],
                },
            }

        case _:
            return {"error": f"Unknown tool: {name}"}


# ---------------------------------------------------------------------------
# MCP handlers
# ---------------------------------------------------------------------------

@server.list_tools()
async def list_tools() -> list[Tool]:
    return TOOLS


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any] | None) -> list[TextContent]:
    args = arguments or {}
    logger.info("Tool call: %s(%s)", name, json.dumps(args, default=str)[:200])
    try:
        result = await _dispatch(name, args)
    except KeyError as exc:
        logger.warning("Missing required argument for %s: %s", name, exc)
        result = {"error": f"Missing required argument: {exc}"}
    except Exception as exc:  # noqa: BLE001
        logger.exception("Unhandled error in tool %s: %s", name, exc)
        result = {"error": f"Internal error in {name}: {type(exc).__name__}: {exc}"}
    return [TextContent(type="text", text=json.dumps(result, indent=2, default=str))]


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def _run() -> None:
    logger.info("World Events MCP Server starting (%d tools)", len(TOOLS))
    try:
        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream, server.create_initialization_options())
    finally:
        await fetcher.close()
        cache.close()
        logger.info("World Events MCP Server shut down cleanly")


def run() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    run()
