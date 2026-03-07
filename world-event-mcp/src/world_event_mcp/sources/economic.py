"""Economic indicator data sources.

Fetches development indicators (World Bank) for the world-event-mcp server.
No API key required.
"""

import asyncio
import logging
from datetime import datetime, timezone

from ..fetcher import Fetcher

logger = logging.getLogger("world-event-mcp.sources.economic")


# ---------------------------------------------------------------------------
# World Bank: Development indicators
# ---------------------------------------------------------------------------

_WB_BASE = "https://api.worldbank.org/v2/country"

_DEFAULT_INDICATORS = [
    "NY.GDP.MKTP.CD",   # GDP (current US$)
    "FP.CPI.TOTL.ZG",   # Inflation, consumer prices (annual %)
    "SL.UEM.TOTL.ZS",   # Unemployment, total (% of labor force)
]


async def fetch_world_bank_indicators(
    fetcher: Fetcher,
    country: str = "USA",
    indicators: list[str] | None = None,
) -> dict:
    """Fetch World Bank development indicators for a country.

    Defaults to GDP, inflation, and unemployment for the USA.
    Indicators are fetched in parallel.

    Returns a dict with ``country``, ``indicators`` (list of dicts with
    ``id``, ``name``, and ``values``), plus metadata.
    """
    indicator_ids = indicators or _DEFAULT_INDICATORS

    async def _fetch_one(indicator: str) -> dict | None:
        url = f"{_WB_BASE}/{country}/indicator/{indicator}"
        params = {
            "format": "json",
            "per_page": 5,
            "date": "2020:2025",
        }
        return await fetcher.get_json(
            url,
            source="world-bank",
            cache_key=f"economic:wb:{country}:{indicator}",
            cache_ttl=86400,
            params=params,
        )

    responses = await asyncio.gather(
        *[_fetch_one(ind) for ind in indicator_ids]
    )

    parsed_indicators: list[dict] = []

    for indicator_id, raw in zip(indicator_ids, responses):
        entry: dict = {
            "id": indicator_id,
            "name": indicator_id,
            "values": [],
        }

        if raw is None:
            parsed_indicators.append(entry)
            continue

        try:
            # World Bank v2 JSON returns a 2-element list:
            # [metadata_dict, data_records_list]
            if isinstance(raw, list) and len(raw) >= 2:
                records = raw[1]
                if records and isinstance(records, list):
                    # Extract human-readable indicator name from first record
                    first = records[0]
                    ind_info = first.get("indicator", {})
                    if isinstance(ind_info, dict):
                        entry["name"] = ind_info.get("value", indicator_id)

                    for rec in records:
                        year = rec.get("date")
                        value = rec.get("value")
                        if year is not None:
                            parsed_value: float | None = None
                            if value is not None:
                                try:
                                    parsed_value = float(value)
                                except (ValueError, TypeError):
                                    pass
                            entry["values"].append({
                                "year": year,
                                "value": parsed_value,
                            })
        except (KeyError, TypeError, IndexError) as exc:
            logger.warning(
                "Failed to parse World Bank indicator %s for %s: %s",
                indicator_id, country, exc,
            )

        parsed_indicators.append(entry)

    return {
        "country": country,
        "indicators": parsed_indicators,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "source": "world-bank",
    }
