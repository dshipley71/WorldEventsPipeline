"""Financial market macro signal data sources for world-events-mcp.

Provides the Bitcoin/crypto Fear & Greed Index (alternative.me) and
Bitcoin mempool fee data (mempool.space).  Both are completely free with
no API key required.
"""

import asyncio
import logging
from datetime import datetime, timezone

from ..fetcher import Fetcher
from ..utils import utc_now_iso

logger = logging.getLogger("world-events-mcp.sources.markets")


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_FEAR_GREED_URL = "https://api.alternative.me/fng/?limit=1"
_MEMPOOL_FEES_URL = "https://mempool.space/api/v1/fees/recommended"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------



# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def _fetch_fear_greed(fetcher: Fetcher) -> dict | None:
    """Fetch the current Bitcoin/Crypto Fear & Greed Index from alternative.me."""
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
    """Fetch recommended Bitcoin mempool fee rates from mempool.space."""
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
    """Fetch free macro signals: Fear & Greed Index and Bitcoin mempool fees.

    Both signals are fetched in parallel.  A failure in one does not
    affect the other.

    Sources:
        - alternative.me Fear & Greed Index (no key required)
        - mempool.space fee estimates (no key required)

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
        "timestamp": utc_now_iso(),
    }
