"""
world_events/agents/event_correlation.py

EventCorrelationAgent — fetches RSS feed articles via MCP, applies a
time-window gate around detected spikes, then runs MiniLM semantic ranking
to select the most query-relevant items.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from world_events.agents.base import BaseAgent
from world_events.embeddings import semantic_rank_rss
from world_events.logging_utils import log
from world_events.models import Article
from world_events.utils import load_json_from_content, parse_iso_datetime

if TYPE_CHECKING:
    from mcp import ClientSession
    from world_events.models import PipelineState


async def _fetch_rss(session: "ClientSession", state: "PipelineState") -> List[Article]:
    payload: Dict[str, Any] = {"limit": state.params.rss_limit}
    if state.params.category:
        payload["category"] = state.params.category

    log(
        f"RSS->intel_news_feed start "
        f"category={state.params.category} limit={state.params.rss_limit}"
    )
    t0 = time.time()
    result = await session.call_tool("intel_news_feed", payload)
    data = load_json_from_content(result.content)
    dt = time.time() - t0

    if not isinstance(data, dict):
        log(f"RSS->intel_news_feed done ({dt:.2f}s) invalid response")
        return []

    items = data.get("items") or []
    log(f"RSS->intel_news_feed done ({dt:.2f}s) items={len(items)}")

    out: List[Article] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        link = str(item.get("link") or "").strip()
        published_raw = str(item.get("published") or "").strip()
        published_dt = parse_iso_datetime(published_raw) if published_raw else None
        summary_val = item.get("summary")
        summary_str = str(summary_val).strip() if summary_val is not None else ""
        out.append(
            Article(
                source="rss",
                title=title,
                link=link,
                published=published_dt,
                summary=summary_str or None,
                raw=item,
            )
        )
    return out


class EventCorrelationAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__("EventCorrelationAgent")

    async def run(self, session: "ClientSession", state: "PipelineState") -> None:
        rss_all = await _fetch_rss(session, state)
        log(
            f"RSS fetched items={len(rss_all)} "
            f"category={state.params.category} limit={state.params.rss_limit}"
        )

        if state.params.semantic_rss_enabled:
            # Build time windows around spikes (or fall back to full timeline span)
            windows: List[tuple]
            if state.spikes:
                windows = [
                    (
                        s.date - timedelta(days=state.params.window_days),
                        s.date + timedelta(days=state.params.window_days),
                    )
                    for s in state.spikes
                ]
            elif state.timeline:
                start = min(p.date for p in state.timeline) - timedelta(days=state.params.window_days)
                end = max(p.date for p in state.timeline) + timedelta(days=state.params.window_days)
                windows = [(start, end)]
            else:
                now = datetime.now(timezone.utc).replace(tzinfo=None)
                windows = [(now - timedelta(days=7), now)]

            def in_any_window(pub: Optional[datetime]) -> bool:
                if pub is None:
                    return False
                return any(ws <= pub <= we for ws, we in windows)

            rss_windowed = [a for a in rss_all if in_any_window(a.published)]
            log(f"RSS window-gated={len(rss_windowed)} windows={len(windows)}")
            state.rss_articles = semantic_rank_rss(state, rss_windowed, state.gdelt_articles)
        else:
            state.rss_articles = rss_all[: state.params.rss_limit]

        log(
            f"EventCorrelation done "
            f"gdelt={len(state.gdelt_articles)} rss={len(state.rss_articles)}"
        )
