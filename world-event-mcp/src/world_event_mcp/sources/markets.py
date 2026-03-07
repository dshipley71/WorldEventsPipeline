"""Financial market sentiment data sources for world-event-mcp.

Provides async functions for macro sentiment signals (Fear & Greed index,
Bitcoin mempool fees) using completely free, no-key-required public APIs.
"""

import asyncio
import logging
from datetime import datetime, timezone

from ..fetcher import Fetcher

logger = logging.getLogger("world-event-mcp.sources.markets")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_FEAR_GREED_URL = "https://api.alternative.me/fng/?limit=1"
_MEMPOOL_FEES_URL = "https://mempool.space/api/v1/fees/recommended"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def _fetch_fear_greed(fetcher: Fetcher) -> dict | None:
    """Fetch the Crypto Fear & Greed Index from alternative.me (free, no key)."""
    data = await fetcher.get_json(
        _FEAR_GREED_URL,
        source="alternative-me",
        cache_key="markets:macro:fear_greed",
        cache_ttl=300,
    )
    if data is None:
        return None
    try:
        entry = data["data"][0]
        return {
            "value": int(entry["value"]),
            "classification": entry.get("value_classification"),
            "source": "alternative-me",
        }
    except (KeyError, IndexError, TypeError, ValueError):
        return None


async def _fetch_mempool_fees(fetcher: Fetcher) -> dict | None:
    """Fetch recommended Bitcoin mempool fee rates from mempool.space (free, no key)."""
    data = await fetcher.get_json(
        _MEMPOOL_FEES_URL,
        source="mempool",
        cache_key="markets:macro:mempool_fees",
        cache_ttl=300,
    )
    if data is None:
        return None
    return {
        "fastest_fee": data.get("fastestFee"),
        "half_hour_fee": data.get("halfHourFee"),
        "hour_fee": data.get("hourFee"),
        "economy_fee": data.get("economyFee"),
        "minimum_fee": data.get("minimumFee"),
        "source": "mempool",
    }


async def fetch_macro_signals(fetcher: Fetcher) -> dict:
    """Aggregate 2 free macro sentiment signals into a single dashboard payload.

    Fetches the Crypto Fear & Greed Index and Bitcoin mempool fee rates.
    Each signal is fetched independently — a failure in one does not
    affect the other.

    Returns::

        {"signals": {"fear_greed": {...}, "mempool_fees": {...}},
         "source": "multi", "timestamp": "<iso>"}
    """
    fear_greed, mempool_fees = await asyncio.gather(
        _fetch_fear_greed(fetcher),
        _fetch_mempool_fees(fetcher),
    )

    return {
        "signals": {
            "fear_greed": fear_greed,
            "mempool_fees": mempool_fees,
        },
        "source": "multi",
        "timestamp": _utc_now_iso(),
    }
