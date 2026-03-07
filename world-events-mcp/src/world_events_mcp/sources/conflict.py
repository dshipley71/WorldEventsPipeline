"""Conflict and crisis data sources for world-events-mcp.

Fetches humanitarian dataset metadata from HDX (Humanitarian Data Exchange).
No API key required.
"""

import logging
from datetime import datetime, timezone

from ..fetcher import Fetcher

logger = logging.getLogger("world-events-mcp.sources.conflict")


# ---------------------------------------------------------------------------
# HDX: Humanitarian Data Exchange (CKAN API)
# ---------------------------------------------------------------------------

_HDX_SEARCH_URL = "https://data.humdata.org/api/3/action/package_search"


async def fetch_humanitarian_summary(
    fetcher: Fetcher,
    country: str | None = None,
) -> dict:
    """Fetch recent humanitarian crisis datasets from HDX (Humanitarian Data Exchange).

    No API key required.  Uses the CKAN package_search API.

    Args:
        fetcher: Shared HTTP fetcher with caching and circuit breaking.
        country: Optional ISO 3166-1 alpha-3 country code (lowercase) to
                 filter datasets by geographic group.

    Returns:
        Dict with datasets list, count, source, and timestamp.
    """
    now = datetime.now(timezone.utc)

    params: dict = {
        "q": "crisis",
        "rows": 20,
        "sort": "metadata_modified desc",
    }
    if country:
        params["fq"] = f"groups:{country.lower()}"

    cache_country = country or "global"
    data = await fetcher.get_json(
        _HDX_SEARCH_URL,
        source="hdx",
        cache_key=f"conflict:humanitarian:{cache_country}",
        cache_ttl=21600,
        params=params,
    )

    if data is None:
        logger.warning("HDX API returned no data")
        return {
            "datasets": [],
            "count": 0,
            "source": "hdx",
            "timestamp": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }

    datasets = []
    results = data.get("result", {}).get("results", [])

    for dataset in results:
        notes = dataset.get("notes") or ""
        if len(notes) > 200:
            notes = notes[:200] + "..."

        org = dataset.get("organization") or {}
        org_title = org.get("title") if isinstance(org, dict) else None

        datasets.append({
            "name": dataset.get("name"),
            "title": dataset.get("title"),
            "organization": org_title,
            "metadata_modified": dataset.get("metadata_modified"),
            "num_resources": dataset.get("num_resources"),
            "notes": notes,
        })

    return {
        "datasets": datasets,
        "count": len(datasets),
        "source": "hdx",
        "timestamp": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
