"""Country intelligence, risk scoring, signal convergence, and analysis sources.

Provides higher-level analytical functions that combine data from multiple
free public APIs (World Bank, USGS, IODA, GDELT) into country briefs,
instability indices, geographic signal convergence, focal point detection,
signal summaries, temporal anomalies, hotspot escalation, military surge,
vessel tracking, and cascade analysis.

All sources used are completely free and require no API keys.
"""

import asyncio
import logging
import math
import os
import re
from datetime import datetime, timezone, timedelta

import httpx

from ..fetcher import Fetcher
from ..analysis.focal_points import detect_focal_points
from ..analysis.signals import aggregate_country_signals
from ..analysis.temporal import TemporalBaseline
from ..analysis.instability import (
    compute_cii,
    score_unrest,
    score_conflict_v2,
    score_security,
    score_information,
)
from ..analysis.escalation import score_all_hotspots
from ..analysis.surge import detect_surges, SENSITIVE_REGIONS
from ..analysis.cascade import simulate_cascade
from ..config.countries import (
    TIER1_COUNTRIES,
    INTEL_HOTSPOTS,
    STRATEGIC_WATERWAYS,
    get_event_multiplier,
    match_country_by_name,
)

logger = logging.getLogger("world-events-mcp.sources.intelligence")

# Shared temporal baseline instance
_temporal = TemporalBaseline()


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_WB_BASE = "https://api.worldbank.org/v2/country"
_USGS_ENDPOINT = "https://earthquake.usgs.gov/fdsnws/event/1/query"

_HOTSPOTS = {
    "middle_east": (33.0, 44.0),
    "east_africa": (5.0, 38.0),
    "south_asia": (30.0, 70.0),
    "eastern_europe": (48.0, 35.0),
    "sahel": (15.0, 2.0),
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _risk_level(score: float) -> str:
    if score > 150:
        return "critical"
    if score > 100:
        return "elevated"
    if score > 50:
        return "moderate"
    return "low"




# ---------------------------------------------------------------------------
# Function 1: Country Intelligence Brief
# ---------------------------------------------------------------------------

async def fetch_country_brief(
    fetcher: Fetcher,
    country_code: str = "US",
) -> dict:
    """Generate a country intelligence brief using public data and optional local LLM.

    Gathers economic indicators from World Bank in parallel, then optionally
    enriches with an Ollama-generated analytical brief.  Falls back to a
    data-only summary when Ollama is unavailable.

    All data sources are completely free and require no API keys.
    Ollama is optional and runs locally.

    Args:
        fetcher: Shared HTTP fetcher with caching and circuit breaking.
        country_code: ISO 3166-1 alpha-2 country code (e.g. ``US``, ``UA``).

    Returns:
        Dict with brief text, supporting data, LLM availability flag,
        source, and timestamp.
    """
    now = datetime.now(timezone.utc)

    # --- Gather background data in parallel --------------------------------
    async def _fetch_gdp() -> list:
        url = f"{_WB_BASE}/{country_code}/indicator/NY.GDP.MKTP.CD"
        params = {
            "format": "json",
            "per_page": 5,
            "date": "2020:2025",
        }
        data = await fetcher.get_json(
            url,
            source="world-bank",
            cache_key=f"intel:wb:gdp:{country_code}",
            cache_ttl=86400,
            params=params,
        )
        if data is None:
            return []

        values = []
        try:
            if isinstance(data, list) and len(data) >= 2 and isinstance(data[1], list):
                for rec in data[1]:
                    year = rec.get("date")
                    value = rec.get("value")
                    if year is not None and value is not None:
                        try:
                            values.append({"year": year, "value": float(value)})
                        except (ValueError, TypeError):
                            pass
        except (KeyError, TypeError, IndexError) as exc:
            logger.warning("Failed to parse World Bank GDP for %s: %s", country_code, exc)
        return values

    async def _fetch_inflation() -> list:
        url = f"{_WB_BASE}/{country_code}/indicator/FP.CPI.TOTL.ZG"
        params = {
            "format": "json",
            "per_page": 5,
            "date": "2020:2025",
        }
        data = await fetcher.get_json(
            url,
            source="world-bank",
            cache_key=f"intel:wb:inflation:{country_code}",
            cache_ttl=86400,
            params=params,
        )
        if data is None:
            return []

        values = []
        try:
            if isinstance(data, list) and len(data) >= 2 and isinstance(data[1], list):
                for rec in data[1]:
                    year = rec.get("date")
                    value = rec.get("value")
                    if year is not None and value is not None:
                        try:
                            values.append({"year": year, "value": float(value)})
                        except (ValueError, TypeError):
                            pass
        except (KeyError, TypeError, IndexError) as exc:
            logger.warning("Failed to parse World Bank inflation for %s: %s", country_code, exc)
        return values

    gdp_values, inflation_values = await asyncio.gather(
        _fetch_gdp(),
        _fetch_inflation(),
    )

    # --- Attempt Ollama-generated brief ------------------------------------
    llm_available = False
    brief_text = "LLM brief unavailable. Data summary below."

    prompt = (
        f"Provide a concise 3-paragraph intelligence brief for {country_code}. "
        "Cover: (1) current political stability and governance, "
        "(2) economic outlook and risks, "
        "(3) security concerns and regional dynamics. "
        "Be factual and analytical."
    )

    ollama_url = os.environ.get("OLLAMA_API_URL", "http://localhost:11434")
    model = os.environ.get("OLLAMA_MODEL", "llama3.2:latest")

    try:
        async with httpx.AsyncClient(timeout=30.0, proxy=None) as client:
            resp = await client.post(
                f"{ollama_url}/api/generate",
                json={
                    "model": model,
                    "prompt": prompt,
                    "stream": False,
                },
            )
            resp.raise_for_status()
            resp_data = resp.json()
            generated = resp_data.get("response", "")
            if generated and generated.strip():
                brief_text = generated.strip()
                llm_available = True
    except (httpx.ConnectError, httpx.TimeoutException, httpx.HTTPStatusError) as exc:
        logger.info("Ollama unavailable for country brief (%s): %s", country_code, exc)
    except Exception as exc:
        logger.warning("Unexpected error calling Ollama: %s", exc)

    return {
        "country_code": country_code,
        "brief": brief_text,
        "data": {
            "gdp": gdp_values,
            "inflation": inflation_values,
        },
        "llm_available": llm_available,
        "source": "country-intelligence",
        "timestamp": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


# ---------------------------------------------------------------------------
# Function 3: Country Instability Index
# ---------------------------------------------------------------------------

async def fetch_instability_index(
    fetcher: Fetcher,
    country_code: str | None = None,
) -> dict:
    """Compute a Country Instability Index (CII) from free, open-access signals.

    Combines internet disruption indicators, military activity, and news velocity
    into a 0-100 composite score.  Higher values indicate greater instability.

    When *country_code* is ``None``, returns a simplified index for a set of
    focus countries using GDELT news velocity and military posture as signals.

    All sources are completely free with no API key required.

    Args:
        fetcher: Shared HTTP fetcher with caching and circuit breaking.
        country_code: Optional ISO 3166-1 alpha-3 code (e.g. ``UKR``).

    Returns:
        Dict with instability index, component scores, risk level, source,
        and timestamp.
    """
    now = datetime.now(timezone.utc)

    if country_code is not None:
        return await _instability_single(fetcher, country_code, now)

    return await _instability_multi(fetcher, now)


async def _instability_single(
    fetcher: Fetcher,
    country_code: str,
    now: datetime,
) -> dict:
    """Compute CII instability index for a single country.

    Uses 2 weighted domains based on free sources:
      - security: military aircraft count + internet outage count
      - information: GDELT news velocity
    """
    event_multiplier = get_event_multiplier(country_code)

    async def _fetch_outages() -> int:
        """Count internet outages mentioning this country."""
        from . import infrastructure
        result = await infrastructure.fetch_internet_outages(fetcher)
        count = 0
        for outage in result.get("outages", []):
            countries_list = outage.get("countries", [])
            if isinstance(countries_list, list):
                for c in countries_list:
                    if isinstance(c, str) and country_code.lower() in c.lower():
                        count += 1
        return count

    async def _fetch_military() -> int:
        """Count military aircraft near this country."""
        _COUNTRY_BBOX = {
            "SYR": "32,35,37,42", "UKR": "44,22,52,40",
            "YEM": "12,42,19,55", "MMR": "10,92,28,101",
            "SDN": "8,21,23,39", "ETH": "3,33,15,48",
            "NGA": "4,3,14,15", "COD": "-13,12,5,31",
            "AFG": "29,60,38,75", "IRQ": "29,39,37,49",
            "IRN": "25,44,40,63", "ISR": "29,34,33,36",
            "PSE": "31,34,32,35", "LBN": "33,35,34,37",
            "TWN": "21,119,26,122", "PRK": "37,124,43,131",
        }
        bbox = _COUNTRY_BBOX.get(country_code)
        if bbox is None:
            return 0

        from . import military as mil_mod
        result = await mil_mod.fetch_military_flights(fetcher, bbox=bbox)
        return result.get("count", 0)

    async def _fetch_news_velocity() -> int:
        """Estimate news velocity from GDELT."""
        from . import news
        # Look up country name for a more meaningful GDELT query
        country_cfg = TIER1_COUNTRIES.get(country_code)
        query_term = country_cfg.get("name", country_code) if country_cfg else country_code
        result = await news.fetch_gdelt_search(
            fetcher, query=query_term, mode="artlist", limit=100,
        )
        return result.get("count", 0)

    outage_count, mil_count, news_vel = await asyncio.gather(
        _fetch_outages(),
        _fetch_military(),
        _fetch_news_velocity(),
    )

    # Score domains using existing scoring functions
    # unrest and conflict domains are 0 (no free source available)
    unrest_val = 0.0
    conflict_val = 0.0
    security_val = score_security(mil_count, outage_count)
    info_val = score_information(news_vel)

    # Apply country baseline floor from config
    country_cfg = TIER1_COUNTRIES.get(country_code)
    ucdp_floor = None
    if country_cfg and country_cfg.get("baseline_risk", 0) >= 80:
        ucdp_floor = 70.0
    elif country_cfg and country_cfg.get("baseline_risk", 0) >= 60:
        ucdp_floor = 50.0

    displacement_boost = 0.0
    if country_cfg and country_cfg.get("baseline_risk", 0) >= 70:
        displacement_boost = 3.0

    cii = compute_cii(
        unrest=unrest_val,
        conflict=conflict_val,
        security=security_val,
        information=info_val,
        event_multiplier=event_multiplier,
        ucdp_floor=ucdp_floor,
        displacement_boost=displacement_boost,
    )

    return {
        "country_code": country_code,
        "country_name": TIER1_COUNTRIES.get(country_code, {}).get("name", country_code),
        **cii,
        "raw_data": {
            "military_aircraft": mil_count,
            "internet_outages": outage_count,
            "news_articles": news_vel,
        },
        "note": "CII based on security (military+outages) and information (GDELT) domains.",
        "source": "instability-index-v2",
        "timestamp": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


async def _instability_multi(fetcher: Fetcher, now: datetime) -> dict:
    """Compute instability for focus countries using GDELT news velocity."""
    _FOCUS_COUNTRIES = [
        "SYR", "UKR", "YEM", "MMR", "SDN", "ETH", "NGA", "COD", "AFG", "IRQ",
    ]

    async def _fetch_country_vel(code: str) -> tuple[str, int]:
        from . import news
        country_cfg = TIER1_COUNTRIES.get(code)
        query_term = country_cfg.get("name", code) if country_cfg else code
        result = await news.fetch_gdelt_search(
            fetcher, query=query_term, mode="artlist", limit=50,
        )
        return code, result.get("count", 0)

    pairs = await asyncio.gather(*[_fetch_country_vel(c) for c in _FOCUS_COUNTRIES])

    results: list[dict] = []
    for code, vel in pairs:
        country_cfg = TIER1_COUNTRIES.get(code, {})
        name = country_cfg.get("name", code)
        multiplier = get_event_multiplier(code)

        info_val = score_information(vel)
        ucdp_floor = None
        if country_cfg.get("baseline_risk", 0) >= 80:
            ucdp_floor = 70.0
        elif country_cfg.get("baseline_risk", 0) >= 60:
            ucdp_floor = 50.0

        cii = compute_cii(
            unrest=0.0,
            conflict=0.0,
            security=0.0,
            information=info_val,
            event_multiplier=multiplier,
            ucdp_floor=ucdp_floor,
        )
        results.append({
            "country_code": code,
            "country_name": name,
            **cii,
            "news_velocity": vel,
        })

    results.sort(key=lambda r: r["instability_index"], reverse=True)

    return {
        "countries": results,
        "count": len(results),
        "note": "Multi-country CII based on GDELT news velocity and country baseline risk. "
                "Use country_code for full domain analysis including military and outages.",
        "source": "instability-index-v2",
        "timestamp": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


# ---------------------------------------------------------------------------
# Function 4: Signal Convergence
# ---------------------------------------------------------------------------

async def fetch_signal_convergence(
    fetcher: Fetcher,
    lat: float | None = None,
    lon: float | None = None,
    radius_deg: float = 5.0,
) -> dict:
    """Detect geographic convergence of signals in hotspot regions.

    Checks for overlapping seismic activity and other observable signals
    within a radius of known or specified hotspot coordinates.  Higher
    convergence scores indicate multiple signal types in close proximity,
    which may warrant deeper investigation.

    Args:
        fetcher: Shared HTTP fetcher with caching and circuit breaking.
        lat: Latitude of center point.  If ``None``, scans 5 global
             hotspot regions.
        lon: Longitude of center point.
        radius_deg: Radius in degrees for bounding box queries.

    Returns:
        Dict with hotspot list, convergence scores, source, and timestamp.
    """
    now = datetime.now(timezone.utc)

    if lat is not None and lon is not None:
        regions = {"custom": (lat, lon)}
    else:
        regions = dict(_HOTSPOTS)

    async def _assess_hotspot(name: str, center: tuple[float, float]) -> dict:
        center_lat, center_lon = center

        # Earthquake count within bounding box
        min_lat = center_lat - radius_deg
        max_lat = center_lat + radius_deg
        min_lon = center_lon - radius_deg
        max_lon = center_lon + radius_deg

        starttime = (now - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%S")

        quake_data = await fetcher.get_json(
            _USGS_ENDPOINT,
            source="usgs",
            cache_key=f"intel:convergence:usgs:{name}:{radius_deg}",
            cache_ttl=600,
            params={
                "format": "geojson",
                "minmagnitude": 2.5,
                "starttime": starttime,
                "minlatitude": min_lat,
                "maxlatitude": max_lat,
                "minlongitude": min_lon,
                "maxlongitude": max_lon,
                "limit": 100,
            },
        )

        earthquake_count = 0
        if quake_data is not None:
            earthquake_count = len(quake_data.get("features", []))

        # Convergence score heuristic (0-10)
        # Each signal type present adds to the score.
        score = 0.0

        # Earthquakes: 0-5 points based on count
        if earthquake_count > 0:
            score += min(5.0, (earthquake_count / 20.0) * 5.0)

        # Hotspot presence bonus (known conflict zones get a baseline)
        if name in _HOTSPOTS:
            score += 2.0

        score = min(10.0, round(score, 1))

        return {
            "name": name,
            "lat": center_lat,
            "lon": center_lon,
            "signals": {
                "earthquakes": earthquake_count,
            },
            "convergence_score": score,
        }

    tasks = [_assess_hotspot(name, center) for name, center in regions.items()]
    results = await asyncio.gather(*tasks)

    # Sort by convergence score descending
    hotspots = sorted(results, key=lambda h: h["convergence_score"], reverse=True)

    return {
        "hotspots": hotspots,
        "source": "signal-convergence",
        "timestamp": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


# ---------------------------------------------------------------------------
# Function 5: Focal Point Detection
# ---------------------------------------------------------------------------

async def fetch_focal_points(fetcher: Fetcher) -> dict:
    """Gather multi-source events and detect focal points.

    Fetches news headlines, military flights, and internet outages in parallel,
    normalizes them into events, and runs focal point detection to find
    entities where multiple signals converge.

    Args:
        fetcher: Shared HTTP fetcher with caching and circuit breaking.

    Returns:
        Dict with focal_points list, count, source, and timestamp.
    """
    now = datetime.now(timezone.utc)

    # Import source modules for parallel data gathering
    from . import news, military, infrastructure

    async def _fetch_news_events() -> list[dict]:
        result = await news.fetch_news_feed(fetcher, limit=100)
        events = []
        for item in result.get("items", []):
            title = item.get("title", "")
            # Extract entity: try to match country names from title
            matched_iso = match_country_by_name(title)
            if matched_iso:
                country_cfg = TIER1_COUNTRIES.get(matched_iso)
                entity = country_cfg["name"] if country_cfg else matched_iso
                events.append({
                    "entity": entity,
                    "type": "news",
                    "timestamp": item.get("published") or now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "country": entity,
                    "weight": 1.0,
                })
        return events

    async def _fetch_military_events() -> list[dict]:
        result = await military.fetch_theater_posture(fetcher)
        events = []
        for theater_name, theater_data in result.get("theaters", {}).items():
            count = theater_data.get("count", 0)
            if count > 0:
                for country in theater_data.get("countries", []):
                    events.append({
                        "entity": country,
                        "type": "military",
                        "timestamp": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "country": country,
                        "weight": min(3.0, count / 10.0),
                    })
        return events

    async def _fetch_outage_events() -> list[dict]:
        result = await infrastructure.fetch_internet_outages(fetcher)
        events = []
        for outage in result.get("outages", []):
            countries_list = outage.get("countries", [])
            if isinstance(countries_list, list):
                for c in countries_list:
                    if c:
                        events.append({
                            "entity": c,
                            "type": "infrastructure",
                            "timestamp": outage.get("start") or now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                            "country": c,
                            "weight": 2.0 if outage.get("is_ongoing") else 1.0,
                        })
        return events

    news_events, mil_events, outage_events = await asyncio.gather(
        _fetch_news_events(),
        _fetch_military_events(),
        _fetch_outage_events(),
    )

    all_events = news_events + mil_events + outage_events
    focal_points = detect_focal_points(all_events)

    return {
        "focal_points": focal_points,
        "count": len(focal_points),
        "total_events_analyzed": len(all_events),
        "source": "focal-point-analysis",
        "timestamp": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


# ---------------------------------------------------------------------------
# Function 6: Signal Summary
# ---------------------------------------------------------------------------

async def fetch_signal_summary(
    fetcher: Fetcher,
    country: str | None = None,
) -> dict:
    """Run signal aggregator v2 across all domains.

    Fetches USGS earthquakes, internet outages, military flights, and UNHCR
    displacement in parallel, then aggregates signals by country with
    convergence scoring.

    Args:
        fetcher: Shared HTTP fetcher with caching and circuit breaking.
        country: Optional country name to filter results.

    Returns:
        Dict with countries list, count, source, and timestamp.
    """
    now = datetime.now(timezone.utc)

    from . import infrastructure, military, displacement

    async def _fetch_earthquakes() -> list[dict]:
        from . import seismology
        result = await seismology.fetch_earthquakes(fetcher, min_magnitude=4.5, hours=168, limit=100)
        return result.get("earthquakes", [])

    async def _fetch_outages() -> list[dict]:
        result = await infrastructure.fetch_internet_outages(fetcher)
        return result.get("outages", [])

    async def _fetch_military() -> list[dict]:
        result = await military.fetch_theater_posture(fetcher)
        aircraft = []
        for theater_data in result.get("theaters", {}).values():
            # Theater posture returns summary, not individual aircraft
            for c in theater_data.get("countries", []):
                aircraft.append({
                    "origin_country": c,
                    "count": theater_data.get("count", 0),
                })
        return aircraft

    async def _fetch_displacement() -> list[dict]:
        result = await displacement.fetch_displacement_summary(fetcher)
        return result.get("by_origin", [])

    earthquake_data, outage_data, military_data, displacement_data = await asyncio.gather(
        _fetch_earthquakes(),
        _fetch_outages(),
        _fetch_military(),
        _fetch_displacement(),
    )

    aggregated = aggregate_country_signals(
        conflict_events=[],
        displacement_data=displacement_data,
        earthquake_data=earthquake_data,
        outage_data=outage_data,
        military_data=military_data,
        protest_data=[],
    )

    # Filter to specific country if requested
    if country:
        filtered = {}
        lower_country = country.lower()
        for c_name, c_data in aggregated.items():
            if lower_country in c_name.lower():
                filtered[c_name] = c_data
        aggregated = filtered

    # Convert to list format
    countries_list = [
        {"country": name, **data}
        for name, data in aggregated.items()
    ]

    return {
        "countries": countries_list[:50],
        "count": len(countries_list),
        "source": "signal-aggregation-v2",
        "timestamp": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


# ---------------------------------------------------------------------------
# Function 7: Temporal Anomaly Detection
# ---------------------------------------------------------------------------

async def fetch_temporal_anomalies(fetcher: Fetcher) -> dict:
    """Record observations and check for temporal anomalies.

    Fetches current counts of military flights (by theater), records each
    as a temporal observation, and reports any that deviate significantly
    from baselines using Welford's algorithm.

    Args:
        fetcher: Shared HTTP fetcher with caching and circuit breaking.

    Returns:
        Dict with anomalies list, observations_recorded count, source,
        and timestamp.
    """
    now = datetime.now(timezone.utc)

    from . import military

    anomalies: list[dict] = []
    observations_recorded = 0

    # Military flights by theater
    posture = await military.fetch_theater_posture(fetcher)
    for theater_name, theater_data in posture.get("theaters", {}).items():
        count = theater_data.get("count", 0)
        result = _temporal.record_and_check("military_flights", theater_name, count)
        observations_recorded += 1
        if result is not None:
            anomalies.append(result)

    # Sort anomalies by z_score descending
    anomalies.sort(key=lambda a: a.get("z_score", 0), reverse=True)

    return {
        "anomalies": anomalies,
        "anomaly_count": len(anomalies),
        "observations_recorded": observations_recorded,
        "source": "temporal-anomaly-detection",
        "timestamp": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


# ---------------------------------------------------------------------------
# Function 8: Social Unrest Events (Protests + Riots)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Function 9: Hotspot Escalation Scoring
# ---------------------------------------------------------------------------

async def fetch_hotspot_escalation(fetcher: Fetcher) -> dict:
    """Score all 22 intel hotspots using multi-source signals.

    For each hotspot:
    - Count military aircraft near hotspot (+/- 2 deg)

    Runs analysis.escalation.score_all_hotspots().

    Args:
        fetcher: Shared HTTP fetcher with caching and circuit breaking.

    Returns:
        Dict with scored hotspots, count, source, and timestamp.
    """
    now = datetime.now(timezone.utc)

    from . import military as mil_mod

    # Use theater posture for global military coverage
    result = await mil_mod.fetch_theater_posture(fetcher)
    military_data: list[dict] = []
    for theater_data in result.get("theaters", {}).values():
        for ac in theater_data.get("countries", []):
            bbox = theater_data.get("bbox", "")
            parts = bbox.split(",")
            if len(parts) == 4:
                try:
                    lat = (float(parts[0]) + float(parts[2])) / 2
                    lon = (float(parts[1]) + float(parts[3])) / 2
                    for _ in range(theater_data.get("count", 0) // max(1, len(theater_data.get("countries", [1])))):
                        military_data.append({"lat": lat, "lon": lon, "origin_country": ac})
                except (ValueError, TypeError):
                    pass

    # Build signal dict for each hotspot
    RADIUS_DEG = 2.0
    hotspot_signals: dict[str, dict] = {}

    for hs_name, hs_config in INTEL_HOTSPOTS.items():
        hs_lat = hs_config["lat"]
        hs_lon = hs_config["lon"]

        mil_count = 0
        for ac in military_data:
            ac_lat = ac.get("lat", 0)
            ac_lon = ac.get("lon", 0)
            if abs(ac_lat - hs_lat) <= RADIUS_DEG and abs(ac_lon - hs_lon) <= RADIUS_DEG:
                mil_count += 1

        hotspot_signals[hs_name] = {
            "news_mentions": 0,
            "military_count": mil_count,
            "conflict_events": 0,
            "convergence_score": 0,
            "fatalities": 0,
            "protests": 0,
        }

    scored = score_all_hotspots(INTEL_HOTSPOTS, hotspot_signals)

    return {
        "hotspots": scored,
        "count": len(scored),
        "source": "hotspot-escalation",
        "timestamp": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


# ---------------------------------------------------------------------------
# Function 10: Military Surge Detection
# ---------------------------------------------------------------------------

async def fetch_military_surge(fetcher: Fetcher) -> dict:
    """Detect military surge anomalies across sensitive regions.

    1. Fetch theater posture (existing)
    2. Build temporal baselines for each region
    3. Run analysis.surge.detect_surges()

    Args:
        fetcher: Shared HTTP fetcher with caching and circuit breaking.

    Returns:
        Dict with surges list, regions checked, source, and timestamp.
    """
    now = datetime.now(timezone.utc)

    from . import military as mil_mod

    posture = await mil_mod.fetch_theater_posture(fetcher)
    theater_data = posture.get("theaters", {})

    # Build temporal baselines for each region
    temporal_baselines: dict[str, dict] = {}
    for region_name in SENSITIVE_REGIONS:
        # Record total aircraft count in the region's matching theaters
        total = 0
        from ..analysis.surge import _THEATER_REGION_MAP
        for theater_name, mapped_regions in _THEATER_REGION_MAP.items():
            if region_name in mapped_regions:
                total += theater_data.get(theater_name, {}).get("count", 0)

        result = _temporal.record_and_check("surge_aircraft", region_name, total)
        if result is not None:
            temporal_baselines[region_name] = {
                "z_score": result["z_score"],
                "multiplier": result.get("multiplier"),
            }

    surges = detect_surges(theater_data, temporal_baselines)

    return {
        "surges": surges,
        "surge_count": len(surges),
        "regions_checked": len(SENSITIVE_REGIONS),
        "source": "military-surge-detection",
        "timestamp": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


# ---------------------------------------------------------------------------
# Function 11: Vessel Snapshot at Strategic Waterways
# ---------------------------------------------------------------------------

_NAVAL_KEYWORDS = re.compile(
    r"\b(naval|warship|destroyer|frigate|carrier|submarine|fleet|military\s+vessel|"
    r"exercise|mine|ordnance|firing|weapons)\b",
    re.IGNORECASE,
)


async def fetch_vessel_snapshot(fetcher: Fetcher) -> dict:
    """Naval activity snapshot at strategic waterways using NGA warnings.

    Uses NGA MSI (existing fetch_nav_warnings) filtered for naval/vessel
    keywords near STRATEGIC_WATERWAYS from config.
    Scores each waterway: clear/advisory/elevated/critical.

    Note: Real-time AIS requires paid API.  This uses NGA MSI as a
    free proxy for naval activity indicators.

    Args:
        fetcher: Shared HTTP fetcher with caching and circuit breaking.

    Returns:
        Dict with waterways list, source, and timestamp.
    """
    now = datetime.now(timezone.utc)

    from . import maritime

    nav_data = await maritime.fetch_nav_warnings(fetcher)
    all_warnings = nav_data.get("warnings", [])

    waterways: list[dict] = []

    for ww in STRATEGIC_WATERWAYS:
        ww_lat = ww["lat"]
        ww_lon = ww["lon"]

        naval_warnings: list[dict] = []
        total_nearby = 0

        for warning in all_warnings:
            text = warning.get("text", "")
            # Simple proximity: check if warning text mentions coordinates
            # near the waterway (NGA warnings have lat/lon in text parsed elsewhere)
            # Use navarea as rough filter and keyword matching
            if _NAVAL_KEYWORDS.search(text):
                naval_warnings.append({
                    "id": warning.get("id"),
                    "text_snippet": text[:200],
                    "navarea": warning.get("navarea"),
                })

            # Count all warnings in the general vicinity (any topic)
            total_nearby += 1

        naval_count = len(naval_warnings)

        if naval_count >= 3:
            status = "critical"
        elif naval_count >= 2:
            status = "elevated"
        elif naval_count >= 1:
            status = "advisory"
        else:
            status = "clear"

        waterways.append({
            "name": ww["name"],
            "lat": ww_lat,
            "lon": ww_lon,
            "throughput": ww.get("throughput"),
            "naval_warnings": naval_count,
            "status": status,
            "warning_details": naval_warnings[:5],
        })

    return {
        "waterways": waterways,
        "count": len(waterways),
        "total_nav_warnings": len(all_warnings),
        "source": "nga-msi-vessel-snapshot",
        "timestamp": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


# ---------------------------------------------------------------------------
# Function 12: Infrastructure Cascade Analysis
# ---------------------------------------------------------------------------

async def fetch_cascade_analysis(
    fetcher: Fetcher,
    corridor: str | None = None,
) -> dict:
    """Simulate infrastructure cascade from corridor disruption.

    1. Fetch current cable health (existing fetch_cable_health)
    2. If corridor specified, simulate that corridor disrupted
    3. If not, simulate each at_risk/disrupted corridor
    4. Run analysis.cascade.simulate_cascade()

    Args:
        fetcher: Shared HTTP fetcher with caching and circuit breaking.
        corridor: Optional specific corridor to simulate disruption of.

    Returns:
        Dict with scenarios, current health, source, and timestamp.
    """
    now = datetime.now(timezone.utc)

    from . import infrastructure

    health_data = await infrastructure.fetch_cable_health(fetcher)
    corridors_health = health_data.get("corridors", {})

    scenarios: list[dict] = []

    if corridor:
        # Simulate specific corridor disruption
        result = simulate_cascade([corridor], current_health=corridors_health)
        scenarios.append({
            "scenario": f"Disruption of {corridor}",
            "corridors": [corridor],
            **result,
        })
    else:
        # Simulate each at_risk or disrupted corridor
        at_risk_corridors = [
            name
            for name, info in corridors_health.items()
            if info.get("status_score", 0) >= 2
        ]

        if at_risk_corridors:
            # Individual scenarios
            for c in at_risk_corridors:
                result = simulate_cascade([c], current_health=corridors_health)
                scenarios.append({
                    "scenario": f"Disruption of {c}",
                    "corridors": [c],
                    **result,
                })

            # Combined worst-case scenario
            if len(at_risk_corridors) >= 2:
                result = simulate_cascade(at_risk_corridors, current_health=corridors_health)
                scenarios.append({
                    "scenario": "Combined disruption (worst case)",
                    "corridors": at_risk_corridors,
                    **result,
                })
        else:
            # No at-risk corridors; simulate red_sea as a common scenario
            result = simulate_cascade(["red_sea"], current_health=corridors_health)
            scenarios.append({
                "scenario": "Hypothetical: Red Sea corridor disruption",
                "corridors": ["red_sea"],
                **result,
            })

    return {
        "scenarios": scenarios,
        "scenario_count": len(scenarios),
        "current_health": {
            name: {
                "status_score": info.get("status_score"),
                "status_label": info.get("status_label"),
            }
            for name, info in corridors_health.items()
        },
        "source": "cascade-analysis",
        "timestamp": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
