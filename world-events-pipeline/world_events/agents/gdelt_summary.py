"""
world_events/agents/gdelt_summary.py

GDELTArticleSummaryAgent — generates concise (1–3 sentence) LLM summaries
for each GDELT article, stored in ``article.raw["llm_summary"]``.

Runs after GDELTReRankAgent so all summarised articles are the same ones
CrossSourceReviewAgent will select (eliminates the prior coverage gap).
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from world_events.agents.base import BaseAgent
from world_events.llm import get_ollama_client
from world_events.logging_utils import log
from world_events.utils import article_domain_lang, truncate, safe_llm_text

if TYPE_CHECKING:
    from mcp import ClientSession
    from world_events.models import PipelineState


class GDELTArticleSummaryAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__("GDELTArticleSummaryAgent")

    async def run(self, session: "ClientSession", state: "PipelineState") -> None:  # noqa: ARG002
        client_model = get_ollama_client(state)
        if client_model is None:
            log("GDELTArticleSummaryAgent: LLM unavailable — skipping")
            return

        client, model = client_model

        if not state.gdelt_articles:
            log("GDELTArticleSummaryAgent: no GDELT articles")
            return

        n = min(state.params.llm_max_articles, len(state.gdelt_articles))
        log(f"GDELTArticleSummaryAgent: summarising {n} articles with {model}")

        for i, art in enumerate(state.gdelt_articles[:n], start=1):
            domain, lang = article_domain_lang(art)
            published = art.published.isoformat() if art.published else "unknown"

            prompt = (
                "You are a careful analyst. Use ONLY the provided fields. Do not guess.\n"
                "Write a 1–3 sentence summary of the article.\n"
                "Include domain and language explicitly in the summary.\n\n"
                f"domain: {domain}\n"
                f"language: {lang}\n"
                f"published: {published}\n"
                f"title: {truncate(art.title, 260)}\n"
                f"snippet: {truncate(art.summary or '', 750)}\n"
                f"url: {art.link}\n"
            )

            log(f"LLM summary {i}/{n}: {domain} | {lang} | {art.title[:80]!r}")

            try:
                resp = await asyncio.wait_for(
                    asyncio.to_thread(
                        client.chat,
                        model,
                        messages=[{"role": "user", "content": prompt}],
                        options={"num_predict": 120},
                        stream=False,
                    ),
                    timeout=state.params.llm_timeout_seconds,
                )
                content = safe_llm_text(resp)
                art.raw["llm_summary"] = content.strip() if content else ""
            except asyncio.TimeoutError:
                art.raw["llm_summary"] = ""
                log(
                    f"GDELTArticleSummaryAgent: timeout "
                    f"({state.params.llm_timeout_seconds}s) article {i}/{n}"
                )
            except Exception as exc:
                art.raw["llm_summary"] = ""
                log(f"GDELTArticleSummaryAgent: error: {exc}")
