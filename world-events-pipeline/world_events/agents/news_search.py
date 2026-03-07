"""
world_events/agents/news_search.py

NewsSearchAgent — retrieves GDELT articles using artlist mode.
Strategy: MCP-first with direct HTTP fallback when MCP returns nothing.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from world_events.agents.base import BaseAgent
from world_events.logging_utils import log
from world_events.models import Article
from world_events.rate_limiter import call_gdelt_tool_with_backoff, direct_gdelt_request_with_backoff
from world_events.utils import parse_iso_datetime

if TYPE_CHECKING:
    from mcp import ClientSession
    from world_events.models import PipelineState


def _parse_articles(source_data: Any) -> List[Article]:
    """Convert a raw GDELT artlist response into Article objects."""
    out: List[Article] = []
    if not isinstance(source_data, dict):
        return out

    articles = source_data.get("articles") or source_data.get("docs") or []
    for item in articles:
        if not isinstance(item, dict):
            continue

        title = str(item.get("title") or "").strip()
        link = str(item.get("url") or item.get("link") or "").strip()

        published_raw = str(item.get("seendate") or item.get("published") or "").strip()
        published_dt = parse_iso_datetime(published_raw) if published_raw else None

        summary: Optional[str] = item.get("snippet") or item.get("summary") or item.get("description")
        if not summary:
            bits: List[str] = []
            for key, label in [("domain", "domain"), ("language", "lang"), ("sourcecountry", "sourcecountry")]:
                val = item.get(key)
                if val:
                    bits.append(f"{label}={val}")
            summary = "; ".join(bits) or None

        out.append(
            Article(
                source="gdelt",
                title=title,
                link=link,
                published=published_dt,
                summary=str(summary).strip() if summary else None,
                raw=item,
            )
        )
    return out


class NewsSearchAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__("NewsSearchAgent")

    async def run(self, session: "ClientSession", state: "PipelineState") -> None:
        assert state.gdelt_limiter is not None
        mode = "artlist"
        parsed: List[Article] = []

        if state.params.use_mcp_for_gdelt:
            payload: Dict[str, Any] = {
                "query": state.query,
                "mode": mode,
                "limit": state.params.gdelt_limit,
            }
            data = await call_gdelt_tool_with_backoff(
                session=session,
                limiter=state.gdelt_limiter,
                payload=payload,
                max_retries=state.params.gdelt_max_retries,
            )
            parsed = _parse_articles(data)
            log(f"GDELT MCP artlist parsed_articles={len(parsed)}")

            if not parsed:
                reason = "MCP returned no data" if data is None else "MCP returned 0 articles"
                log(
                    f"GDELT MCP artlist empty ({reason}) "
                    "-> sleeping 8s then trying direct fallback"
                )
                await asyncio.sleep(8)
                direct = await direct_gdelt_request_with_backoff(
                    state=state,
                    query=state.query,
                    mode=mode,
                    timespan=state.params.timespan,
                    maxrecords=state.params.gdelt_limit,
                )
                parsed = _parse_articles(direct)
                log(f"GDELT direct artlist parsed_articles={len(parsed)}")
        else:
            log("Bypassing MCP for GDELT (direct-only artlist)")
            direct = await direct_gdelt_request_with_backoff(
                state=state,
                query=state.query,
                mode=mode,
                timespan=state.params.timespan,
                maxrecords=state.params.gdelt_limit,
            )
            parsed = _parse_articles(direct)
            log(f"GDELT direct artlist parsed_articles={len(parsed)}")

        state.gdelt_articles = parsed
