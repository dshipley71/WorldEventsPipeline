"""
world_events/rate_limiter.py

AsyncRateLimiter and the two GDELT call wrappers
(MCP-with-backoff and direct-HTTP-with-backoff).
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Any, Dict, Optional

import requests

from world_events.logging_utils import log
from world_events.utils import load_json_from_content

if TYPE_CHECKING:
    from mcp import ClientSession
    from world_events.models import PipelineState

GDELT_URL = "https://api.gdeltproject.org/api/v2/doc/doc"


class AsyncRateLimiter:
    """Token-bucket style rate limiter safe for use in async code."""

    def __init__(self, min_interval_seconds: float) -> None:
        self.min_interval_seconds = float(min_interval_seconds)
        self._last_call_ts: float = 0.0

    async def wait(self, context: str = "") -> None:
        now = time.time()
        elapsed = now - self._last_call_ts
        remaining = self.min_interval_seconds - elapsed
        if remaining > 0:
            log(f"RateLimit sleep={remaining:.2f}s context={context}")
            await asyncio.sleep(remaining)
        self._last_call_ts = time.time()


# ── MCP call wrapper ──────────────────────────────────────────────────────────

async def call_gdelt_tool_with_backoff(
    session: "ClientSession",
    limiter: AsyncRateLimiter,
    payload: Dict[str, Any],
    max_retries: int,
) -> Any:
    """
    Call the MCP ``intel_gdelt_search`` tool with throttling and retry/backoff.
    Returns parsed JSON dict on success, None after all retries exhausted.
    """
    mode = str(payload.get("mode", ""))
    timespan = str(payload.get("timespan", ""))
    limit = payload.get("limit")

    for attempt in range(max_retries + 1):
        ctx = f"MCP intel_gdelt_search mode={mode} attempt={attempt + 1}/{max_retries + 1}"
        await limiter.wait(context=ctx)

        log(f"MCP->intel_gdelt_search start mode={mode} timespan={timespan} limit={limit}")
        t0 = time.time()
        data: Any = None
        err: Optional[str] = None

        try:
            result = await session.call_tool("intel_gdelt_search", payload)
            data = load_json_from_content(result.content)
        except Exception as e:
            err = str(e)

        dt = time.time() - t0

        if isinstance(data, dict):
            art_n = len(data.get("articles") or [])
            tl_n = len(data.get("timeline") or [])
            log(
                f"MCP->intel_gdelt_search done mode={mode} ({dt:.2f}s) "
                f"articles={art_n} timeline_series={tl_n}"
            )
            return data

        log(
            f"MCP->intel_gdelt_search {'error' if err else 'invalid response'} "
            f"mode={mode} ({dt:.2f}s)"
            + (f": {err}" if err else "")
        )

        if attempt < max_retries:
            backoff = limiter.min_interval_seconds * (attempt + 1)
            log(f"MCP->intel_gdelt_search retrying mode={mode} backoff={backoff:.1f}s")
            await asyncio.sleep(backoff)

    log(f"MCP->intel_gdelt_search failed mode={mode} after retries")
    return None


# ── Direct HTTP wrapper ───────────────────────────────────────────────────────

def _direct_gdelt_request_sync(
    query: str, mode: str, timespan: str, maxrecords: int
) -> Optional[Dict[str, Any]]:
    params: Dict[str, Any] = {
        "query": query,
        "mode": mode,
        "timespan": timespan,
        "format": "json",
    }
    if mode == "artlist":
        params["maxrecords"] = maxrecords

    r = requests.get(GDELT_URL, params=params, timeout=180)
    if r.status_code != 200:
        return None
    return r.json()


async def direct_gdelt_request_with_backoff(
    state: "PipelineState",
    query: str,
    mode: str,
    timespan: str,
    maxrecords: int,
) -> Optional[Dict[str, Any]]:
    """
    Direct HTTP call to GDELT using the shared limiter and retry/backoff logic.
    Falls back to this when the MCP server returns nothing.
    """
    assert state.gdelt_limiter is not None
    limiter: AsyncRateLimiter = state.gdelt_limiter

    for attempt in range(state.params.gdelt_max_retries + 1):
        ctx = f"Direct GDELT mode={mode} attempt={attempt + 1}/{state.params.gdelt_max_retries + 1}"
        await limiter.wait(context=ctx)

        log(f"Direct->GDELT start mode={mode} timespan={timespan} maxrecords={maxrecords}")
        t0 = time.time()
        data: Optional[Dict[str, Any]] = None
        err: Optional[str] = None

        try:
            data = await asyncio.to_thread(
                _direct_gdelt_request_sync, query, mode, timespan, maxrecords
            )
        except Exception as e:
            err = str(e)

        dt = time.time() - t0

        if isinstance(data, dict):
            art_n = len(data.get("articles") or data.get("docs") or [])
            tl_n = len(data.get("timeline") or [])
            log(
                f"Direct->GDELT done mode={mode} ({dt:.2f}s) "
                f"articles={art_n} timeline_series={tl_n}"
            )
            return data

        log(
            f"Direct->GDELT {'error' if err else 'empty/failed'} "
            f"mode={mode} ({dt:.2f}s)"
            + (f": {err}" if err else "")
        )

        if attempt < state.params.gdelt_max_retries:
            backoff = state.params.gdelt_min_interval_seconds * (attempt + 1)
            log(f"Direct->GDELT retrying mode={mode} backoff={backoff:.1f}s")
            await asyncio.sleep(backoff)

    log(f"Direct->GDELT failed mode={mode} after retries")
    return None
