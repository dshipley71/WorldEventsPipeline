"""
world_events_mcp/utils.py

Shared utility helpers used across sources/ and analysis/ modules.
Import from here instead of defining locally.
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


def utc_now_iso() -> str:
    """Return current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two points in kilometres (Haversine formula)."""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2) ** 2
    )
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


async def safe_fetch(coro, label: str, context: str = "") -> dict:
    """Await *coro*, returning {} on any exception and logging a warning."""
    prefix = f"{context}: " if context else ""
    try:
        return await coro
    except Exception as exc:
        logger.warning("%s%s failed: %s", prefix, label, exc)
        return {}
