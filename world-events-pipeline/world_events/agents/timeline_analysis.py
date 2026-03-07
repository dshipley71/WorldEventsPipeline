"""
world_events/agents/timeline_analysis.py

TimelineAnalysisAgent — fetches timelinevol, timelinevolraw, and timelinetone
from GDELT (MCP-first, direct fallback) and merges them into TimelinePoint list.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from world_events.agents.base import BaseAgent
from world_events.logging_utils import log
from world_events.models import TimelinePoint
from world_events.rate_limiter import call_gdelt_tool_with_backoff, direct_gdelt_request_with_backoff

if TYPE_CHECKING:
    from mcp import ClientSession
    from world_events.models import PipelineState

_TIMELINE_MODES = ["timelinevol", "timelinevolraw", "timelinetone"]


def _parse_series(data: Any) -> Dict[datetime, float]:
    """Extract a date→value mapping from a GDELT timeline response."""
    series: Dict[datetime, float] = {}
    if not isinstance(data, dict):
        return series

    for entry in data.get("timeline") or []:
        if not isinstance(entry, dict):
            continue
        points = entry.get("data") if isinstance(entry.get("data"), list) else None
        if not points:
            continue
        for p in points:
            if not isinstance(p, dict):
                continue
            ds = p.get("date")
            val = p.get("value")
            if not ds or val is None:
                continue
            try:
                dt = datetime.strptime(str(ds), "%Y%m%dT%H%M%SZ").replace(tzinfo=None)
                series[dt] = float(val)
            except Exception:
                continue
        break  # GDELT wraps the series in the first list element

    return series


class TimelineAnalysisAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__("TimelineAnalysisAgent")

    async def run(self, session: "ClientSession", state: "PipelineState") -> None:
        assert state.gdelt_limiter is not None
        timelines: Dict[str, Any] = {}

        for mode in _TIMELINE_MODES:
            data: Optional[Any] = None

            if state.params.use_mcp_for_gdelt:
                payload = {
                    "query": state.query,
                    "mode": mode,
                    "timespan": state.params.timespan,
                }
                data = await call_gdelt_tool_with_backoff(
                    session=session,
                    limiter=state.gdelt_limiter,
                    payload=payload,
                    max_retries=state.params.gdelt_max_retries,
                )
                if data is None:
                    log(f"GDELT MCP {mode} returned None -> direct fallback")
                    data = await direct_gdelt_request_with_backoff(
                        state=state,
                        query=state.query,
                        mode=mode,
                        timespan=state.params.timespan,
                        maxrecords=state.params.gdelt_limit,
                    )
            else:
                data = await direct_gdelt_request_with_backoff(
                    state=state,
                    query=state.query,
                    mode=mode,
                    timespan=state.params.timespan,
                    maxrecords=state.params.gdelt_limit,
                )

            timelines[mode] = data

        vol_int = _parse_series(timelines.get("timelinevol"))
        raw_vol = _parse_series(timelines.get("timelinevolraw"))
        tone = _parse_series(timelines.get("timelinetone"))

        all_dates = sorted(set(vol_int.keys()) | set(raw_vol.keys()) | set(tone.keys()))
        state.timeline = [
            TimelinePoint(
                date=d,
                volume_intensity=vol_int.get(d),
                raw_volume=raw_vol.get(d),
                tone=tone.get(d),
            )
            for d in all_dates
        ]

        log(
            f"TimelineAnalysis complete points={len(state.timeline)} "
            f"vol={len(vol_int)} raw={len(raw_vol)} tone={len(tone)}"
        )
