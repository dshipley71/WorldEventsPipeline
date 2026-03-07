"""
world_events/agents/structured_output.py

StructuredOutputAgent — serialises the complete pipeline state into a
structured JSON document stored in ``state.output_json``.

The orchestrator prints the JSON *after* restoring stdout to the Jupyter/Colab
wrapper (MCP's stdio_client temporarily swaps it to ``sys.__stdout__``).
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Dict

from world_events.agents.base import BaseAgent
from world_events.logging_utils import log
from world_events.models import Article

if TYPE_CHECKING:
    from mcp import ClientSession
    from world_events.models import PipelineState


def _article_to_dict(a: Article) -> Dict[str, Any]:
    return {
        "source": a.source,
        "title": a.title,
        "link": a.link,
        "published": a.published.isoformat() if a.published else None,
        "summary": a.summary,
        "llm_summary": (a.raw or {}).get("llm_summary"),
    }


class StructuredOutputAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__("StructuredOutputAgent")

    async def run(self, session: "ClientSession", state: "PipelineState") -> None:  # noqa: ARG002
        output = {
            "query": state.query,
            "parameters": {
                "timespan": state.params.timespan,
                "spike_threshold": state.params.spike_threshold,
                "window_days": state.params.window_days,
                "gdelt_limit": state.params.gdelt_limit,
                "rss_limit": state.params.rss_limit,
                "category": state.params.category,
                "use_mcp_for_gdelt": state.params.use_mcp_for_gdelt,
                "gdelt_min_interval_seconds": state.params.gdelt_min_interval_seconds,
                "gdelt_max_retries": state.params.gdelt_max_retries,
                "semantic_rss_enabled": state.params.semantic_rss_enabled,
                "semantic_min_score": state.params.semantic_min_score,
                "semantic_top_k": state.params.semantic_top_k,
                "gdelt_rerank_enabled": state.params.gdelt_rerank_enabled,
                "gdelt_rerank_top_k": state.params.gdelt_rerank_top_k,
                "llm_enabled": state.params.llm_enabled,
                "llm_host": state.params.llm_host,
                "llm_model": state.params.llm_model,
                "llm_max_articles": state.params.llm_max_articles,
                "cross_source_content_mode": state.params.cross_source_content_mode,
            },
            "timeline": [
                {
                    "date": p.date.isoformat(),
                    "volume_intensity": p.volume_intensity,
                    "raw_volume": p.raw_volume,
                    "tone": p.tone,
                }
                for p in state.timeline
            ],
            "spikes": [
                {
                    "date": s.date.isoformat(),
                    "raw_volume": s.raw_volume,
                    "zscore": s.zscore,
                }
                for s in state.spikes
            ],
            "articles": {
                "gdelt": [_article_to_dict(a) for a in state.gdelt_articles],
                "rss": [_article_to_dict(a) for a in state.rss_articles],
            },
            "analysis": {
                "summary": state.analysis_summary,
                "risk_assessment": state.risk_assessment,
                "cross_source_review": state.cross_source_review,
                "cross_source_review_sources": state.cross_source_review_sources,
            },
            "mcp_enrichment": {
                "keyword_spikes": state.mcp_keyword_spikes,
                "news_clusters": state.mcp_news_clusters,
                "entities": state.mcp_entities,
            },
            "artifacts": {
                "plot_png_path": state.plot_png_path,
                "plot_png_base64": state.plot_png_base64,
                "plot_data": state.plot_data,
            },
        }

        # Store on state — orchestrator prints after stdout is restored.
        state.output_json = json.dumps(output, indent=2)
        log("StructuredOutputAgent: output stored in state.output_json")
