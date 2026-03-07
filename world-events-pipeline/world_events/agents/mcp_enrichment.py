"""
world_events/agents/mcp_enrichment.py

MCPEnrichmentAgent — calls three MCP analysis tools in parallel to enrich
pipeline state with NLP-grounded context BEFORE CrossSourceReviewAgent runs.

Tools (all no-API-key required):
  intel_keyword_spikes   — statistically significant keyword surges
                           (z-score / ratio vs Welford rolling baseline).
  intel_news_clusters    — groups RSS articles into topic clusters
                           by Jaccard similarity.
  intel_extract_entities — regex-NER on GDELT article titles;
                           returns countries, leaders, orgs, CVEs, APTs.

Results are stored in PipelineState and injected into the CrossSourceReview
LLM prompt as a compact ENRICHMENT CONTEXT block.

All three calls are fire-and-forget: failures are logged but never block
the pipeline.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, Dict, List

from world_events.agents.base import BaseAgent
from world_events.logging_utils import log
from world_events.utils import load_json_from_content, truncate

if TYPE_CHECKING:
    from mcp import ClientSession
    from world_events.models import PipelineState


class MCPEnrichmentAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__("MCPEnrichmentAgent")

    # ── individual tool fetchers ──────────────────────────────────────────────

    async def _fetch_keyword_spikes(
        self, session: "ClientSession"
    ) -> List[Dict[str, Any]]:
        try:
            result = await session.call_tool(
                "intel_keyword_spikes", {"min_count": 3, "z_threshold": 2.0}
            )
            data = load_json_from_content(result.content)
            if not isinstance(data, dict):
                return []
            spikes = data.get("spikes") or []
            log(f"MCPEnrichmentAgent: keyword_spikes spike_count={len(spikes)}")
            return spikes[:20]
        except Exception as exc:
            log(f"MCPEnrichmentAgent: keyword_spikes failed: {exc}")
            return []

    async def _fetch_news_clusters(
        self, session: "ClientSession", state: "PipelineState"
    ) -> List[Dict[str, Any]]:
        try:
            cat = state.params.category or "geopolitics"
            result = await session.call_tool(
                "intel_news_clusters",
                {"category": cat, "limit": 100, "threshold": 0.25},
            )
            data = load_json_from_content(result.content)
            if not isinstance(data, dict):
                return []
            clusters = data.get("clusters") or []
            log(f"MCPEnrichmentAgent: news_clusters cluster_count={len(clusters)}")
            return clusters[:8]
        except Exception as exc:
            log(f"MCPEnrichmentAgent: news_clusters failed: {exc}")
            return []

    async def _fetch_entities(
        self, session: "ClientSession", state: "PipelineState"
    ) -> Dict[str, Any]:
        try:
            parts: List[str] = []
            for a in state.gdelt_articles[:40]:
                bits = [a.title]
                if a.summary:
                    bits.append(a.summary[:200])
                parts.append(" ".join(bits))
            combined = " ".join(parts).strip()
            text = combined[: state.params.mcp_enrichment_entity_text_limit] if combined else ""

            if not text:
                log("MCPEnrichmentAgent: no GDELT text for entity extraction")
                return {}

            result = await session.call_tool("intel_extract_entities", {"text": text})
            data = load_json_from_content(result.content)
            if not isinstance(data, dict):
                return {}

            entities = data.get("entities") or {}
            by_type = data.get("by_type") or {}
            log(
                f"MCPEnrichmentAgent: entities total={data.get('total_entities', 0)} "
                f"countries={by_type.get('countries', 0)} "
                f"leaders={by_type.get('leaders', 0)} "
                f"orgs={by_type.get('organizations', 0)}"
            )
            return entities
        except Exception as exc:
            log(f"MCPEnrichmentAgent: entities failed: {exc}")
            return {}

    # ── main entry point ──────────────────────────────────────────────────────

    async def run(self, session: "ClientSession", state: "PipelineState") -> None:
        if not state.params.mcp_enrichment_enabled:
            log("MCPEnrichmentAgent: disabled, skipping")
            return

        log("MCPEnrichmentAgent: launching 3 parallel MCP enrichment calls")
        results = await asyncio.gather(
            self._fetch_keyword_spikes(session),
            self._fetch_news_clusters(session, state),
            self._fetch_entities(session, state),
            return_exceptions=True,
        )
        spike_result, cluster_result, entity_result = results

        state.mcp_keyword_spikes = (
            [] if isinstance(spike_result, Exception) else (spike_result or [])
        )
        if isinstance(spike_result, Exception):
            log(f"MCPEnrichmentAgent: keyword_spikes raised: {spike_result}")

        state.mcp_news_clusters = (
            [] if isinstance(cluster_result, Exception) else (cluster_result or [])
        )
        if isinstance(cluster_result, Exception):
            log(f"MCPEnrichmentAgent: news_clusters raised: {cluster_result}")

        state.mcp_entities = (
            {} if isinstance(entity_result, Exception)
            else (entity_result if isinstance(entity_result, dict) else {})
        )
        if isinstance(entity_result, Exception):
            log(f"MCPEnrichmentAgent: entities raised: {entity_result}")

        log(
            f"MCPEnrichmentAgent: complete "
            f"keyword_spikes={len(state.mcp_keyword_spikes)} "
            f"news_clusters={len(state.mcp_news_clusters)} "
            f"entity_types={len(state.mcp_entities)}"
        )
