"""Internet infrastructure monitoring for world-event-mcp.

Provides real-time data on internet outages (IODA — Georgia Tech Internet
Intelligence, public API, no auth required) and undersea cable corridor
health (NGA Maritime Safety Information).
"""

import logging
import re
from datetime import datetime, timezone, timedelta

from ..fetcher import Fetcher

logger = logging.getLogger("world-event-mcp.sources.infrastructure")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_NGA_BROADCAST_WARN_URL = (
    "https://msi.nga.mil/api/publications/broadcast-warn"
)

# Known undersea cable corridors as rough lat/lon bounding boxes.
CABLE_CORRIDORS: dict[str, dict] = {
    "transatlantic_north": {
        "lat_range": (35, 55),
        "lon_range": (-70, -5),
        "cables": ["TAT-14", "AC-1", "MAREA", "Dunant"],
    },
    "transatlantic_south": {
        "lat_range": (-5, 35),
        "lon_range": (-50, 0),
        "cables": ["SAex1", "SACS", "EllaLink"],
    },
    "transpacific": {
        "lat_range": (20, 50),
        "lon_range": (120, -120),
        "cables": ["FASTER", "Unity", "SJC"],
    },
    "asia_europe": {
        "lat_range": (-5, 35),
        "lon_range": (30, 120),
        "cables": ["SEA-ME-WE 6", "AAE-1", "FLAG"],
    },
    "red_sea": {
        "lat_range": (10, 30),
        "lon_range": (30, 50),
        "cables": ["FALCON", "EIG", "AAE-1"],
    },
    "mediterranean": {
        "lat_range": (30, 45),
        "lon_range": (-5, 35),
        "cables": ["SEA-ME-WE 3/4", "MedNautilus"],
    },
}

# Keywords that indicate a navigational warning is cable-related.
_CABLE_KEYWORDS = re.compile(
    r"\b(cable|submarine|fiber|anchor|dredg)\b", re.IGNORECASE
)

# Pattern for DMS coordinates like "32-15.5N/044-30.2E" or "32-15N 044-30E".
_DMS_PATTERN = re.compile(
    r"(\d{1,3})-(\d{1,2}(?:\.\d+)?)\s*([NS])\s*[/ ]\s*"
    r"(\d{1,3})-(\d{1,2}(?:\.\d+)?)\s*([EW])"
)

# Pattern for decimal lat/lon like "32.258N 44.503E" or "32.258/44.503".
_DECIMAL_PATTERN = re.compile(
    r"(\d{1,3}(?:\.\d+)?)\s*([NS])\s*[/ ]\s*"
    r"(\d{1,3}(?:\.\d+)?)\s*([EW])"
)

_STATUS_LABELS = {0: "clear", 1: "advisory", 2: "at_risk", 3: "disrupted"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _extract_coordinates(text: str) -> list[tuple[float, float]]:
    """Extract (lat, lon) pairs from navigational warning text."""
    coords: list[tuple[float, float]] = []

    for match in _DMS_PATTERN.finditer(text):
        deg_lat, min_lat, ns, deg_lon, min_lon, ew = match.groups()
        lat = float(deg_lat) + float(min_lat) / 60.0
        lon = float(deg_lon) + float(min_lon) / 60.0
        if ns == "S":
            lat = -lat
        if ew == "W":
            lon = -lon
        coords.append((lat, lon))

    for match in _DECIMAL_PATTERN.finditer(text):
        lat_val, ns, lon_val, ew = match.groups()
        lat = float(lat_val)
        lon = float(lon_val)
        if ns == "S":
            lat = -lat
        if ew == "W":
            lon = -lon
        coords.append((lat, lon))

    return coords


def _point_in_corridor(lat: float, lon: float, corridor: dict) -> bool:
    """Check whether a (lat, lon) point falls within a cable corridor bbox."""
    lat_lo, lat_hi = corridor["lat_range"]
    lon_lo, lon_hi = corridor["lon_range"]

    if not (lat_lo <= lat <= lat_hi):
        return False

    if lon_lo > lon_hi:
        return lon >= lon_lo or lon <= lon_hi
    return lon_lo <= lon <= lon_hi


# ---------------------------------------------------------------------------
# IODA: Georgia Tech Internet Intelligence (public, no auth required)
# ---------------------------------------------------------------------------

_IODA_OUTAGES_URL = "https://api.ioda.inetintel.cc.gatech.edu/v2/outages/overall"


async def fetch_internet_outages(fetcher: Fetcher) -> dict:
    """Fetch recent internet outages from the IODA public API.

    Uses the Georgia Tech Internet Intelligence (IODA) API — completely
    free, no authentication required.

    Returns:
        Dict with outages list, ongoing/total counts, source, and timestamp.
    """
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=7)

    data = await fetcher.get_json(
        url=_IODA_OUTAGES_URL,
        source="ioda",
        cache_key="infra:outages:ioda",
        cache_ttl=300,
        params={
            "from": int(since.timestamp()),
            "until": int(now.timestamp()),
            "limit": 20,
        },
        timeout=15.0,
    )

    now_iso = _utc_now_iso()

    if data is None:
        logger.warning("IODA API returned no data")
        return {
            "outages": [],
            "ongoing_count": 0,
            "total_7d": 0,
            "source": "ioda-gatech",
            "timestamp": now_iso,
        }

    raw_items = data if isinstance(data, list) else data.get("data", [])
    if not isinstance(raw_items, list):
        raw_items = []

    outages: list[dict] = []
    ongoing_count = 0

    for item in raw_items:
        if not isinstance(item, dict):
            continue

        entity = item.get("entity", {}) if isinstance(item.get("entity"), dict) else {}
        events = item.get("events", []) if isinstance(item.get("events"), list) else [item]

        for ev in events:
            if not isinstance(ev, dict):
                continue
            start = ev.get("from") or ev.get("start")
            end = ev.get("until") or ev.get("end")
            is_ongoing = end is None

            if is_ongoing:
                ongoing_count += 1

            outages.append({
                "id": ev.get("id") or entity.get("code"),
                "start": start,
                "end": end,
                "description": ev.get("summary", entity.get("name", "")),
                "scope": ev.get("level", "unknown"),
                "countries": [entity.get("code", "")] if entity.get("code") else [],
                "asns": [],
                "is_ongoing": is_ongoing,
            })

    return {
        "outages": outages,
        "ongoing_count": ongoing_count,
        "total_7d": len(outages),
        "source": "ioda-gatech",
        "timestamp": now_iso,
    }


# ---------------------------------------------------------------------------
# Undersea Cable Corridor Health (NGA Maritime Safety Information)
# ---------------------------------------------------------------------------

async def fetch_cable_health(fetcher: Fetcher) -> dict:
    """Assess undersea cable corridor health using NGA broadcast warnings.

    Fetches navigational warnings from the NGA Maritime Safety Information
    (MSI) API (public US government endpoint, no auth required), extracts
    coordinates from warning text, and scores each known cable corridor.

    Returns:
        Dict with corridor statuses, warning counts, source, and timestamp.
    """
    data = await fetcher.get_json(
        url=_NGA_BROADCAST_WARN_URL,
        source="nga-msi",
        cache_key="infra:cables",
        cache_ttl=180,
        params={"output": "json"},
    )

    now_iso = _utc_now_iso()

    if data is None:
        logger.warning("NGA MSI broadcast warnings API returned no data")
        corridors_result = {}
        for name, info in CABLE_CORRIDORS.items():
            corridors_result[name] = {
                "status_score": 0,
                "status_label": "clear",
                "cables": info["cables"],
                "relevant_warnings": [],
            }
        return {
            "corridors": corridors_result,
            "warnings_total": 0,
            "cable_related_warnings": 0,
            "source": "nga-msi",
            "timestamp": now_iso,
        }

    raw_warnings: list = []
    if isinstance(data, list):
        raw_warnings = data
    elif isinstance(data, dict):
        for key in ("broadcast-warn", "broadcastWarn", "warnings", "result", "data"):
            candidate = data.get(key)
            if isinstance(candidate, list):
                raw_warnings = candidate
                break

    corridor_warnings: dict[str, list[dict]] = {name: [] for name in CABLE_CORRIDORS}
    cable_related_count = 0

    for warning in raw_warnings:
        if not isinstance(warning, dict):
            continue

        text = warning.get("text", "") or ""
        msg_year = warning.get("msgYear")
        msg_number = warning.get("msgNumber")
        nav_area = warning.get("navArea", "")
        subregion = warning.get("subregion", "")
        status = warning.get("status", "")
        issue_date = warning.get("issueDate", "")

        has_cable_keyword = bool(_CABLE_KEYWORDS.search(text))
        if has_cable_keyword:
            cable_related_count += 1

        coords = _extract_coordinates(text)

        warning_summary = {
            "msgYear": msg_year,
            "msgNumber": msg_number,
            "navArea": nav_area,
            "subregion": subregion,
            "status": status,
            "issueDate": issue_date,
            "has_cable_keyword": has_cable_keyword,
            "text_snippet": text[:200] if text else "",
        }

        for lat, lon in coords:
            for corridor_name, corridor_info in CABLE_CORRIDORS.items():
                if _point_in_corridor(lat, lon, corridor_info):
                    corridor_warnings[corridor_name].append(warning_summary)
                    break

    corridors_result: dict[str, dict] = {}
    for name, info in CABLE_CORRIDORS.items():
        warnings_in_corridor = corridor_warnings[name]
        cable_mentions = sum(1 for w in warnings_in_corridor if w["has_cable_keyword"])

        if not warnings_in_corridor:
            score = 0
        elif cable_mentions >= 2 or len(warnings_in_corridor) >= 3:
            score = 3
        elif cable_mentions >= 1 or len(warnings_in_corridor) >= 2:
            score = 2
        else:
            score = 1

        corridors_result[name] = {
            "status_score": score,
            "status_label": _STATUS_LABELS[score],
            "cables": info["cables"],
            "relevant_warnings": warnings_in_corridor,
        }

    return {
        "corridors": corridors_result,
        "warnings_total": len(raw_warnings),
        "cable_related_warnings": cable_related_count,
        "source": "nga-msi",
        "timestamp": now_iso,
    }
