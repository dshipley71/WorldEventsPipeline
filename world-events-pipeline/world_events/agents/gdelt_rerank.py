"""
world_events/agents/gdelt_rerank.py

GDELTReRankAgent — re-ranks the GDELT article list by semantic similarity
to the user query using MiniLM embeddings.

Must run BEFORE GDELTArticleSummaryAgent so that:
  - LLM summaries are generated only for the top-k most relevant articles.
  - CrossSourceReviewAgent receives a pre-filtered, relevance-sorted list.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from world_events.agents.base import BaseAgent
from world_events.embeddings import semantic_rerank_gdelt
from world_events.logging_utils import log

if TYPE_CHECKING:
    from mcp import ClientSession
    from world_events.models import PipelineState


class GDELTReRankAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__("GDELTReRankAgent")

    async def run(self, session: "ClientSession", state: "PipelineState") -> None:  # noqa: ARG002
        if not state.params.gdelt_rerank_enabled:
            log("GDELTReRankAgent: disabled, skipping")
            return
        if not state.gdelt_articles:
            log("GDELTReRankAgent: no GDELT articles to re-rank")
            return

        original_count = len(state.gdelt_articles)
        reranked = semantic_rerank_gdelt(state, state.gdelt_articles)
        state.gdelt_articles = reranked
        log(
            f"GDELTReRankAgent: kept top_k={len(reranked)} "
            f"from {original_count} original articles"
        )
