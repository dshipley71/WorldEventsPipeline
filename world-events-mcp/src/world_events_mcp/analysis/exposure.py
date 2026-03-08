"""Population exposure analysis near active seismic events.

Estimates population at risk by finding major cities within a radius of
active earthquakes. Uses Haversine formula for distance calculation and
a static dataset of ~120 major cities.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from ..utils import haversine_km, safe_fetch

logger = logging.getLogger("world-events-mcp.analysis.exposure")


def _find_exposed_cities(
    events: list[dict],
    cities: list[dict],
    radius_km: float,
) -> list[dict]:
    """Find cities within radius_km of any event. Returns unique cities with nearest event."""
    exposed: dict[str, dict] = {}  # city_name -> info

    for event in events:
        elat = event.get("lat")
        elon = event.get("lon")
        if elat is None or elon is None:
            continue

        for city in cities:
            dist = haversine_km(elat, elon, city["lat"], city["lon"])
            if dist <= radius_km:
                cname = city["name"]
                if cname not in exposed or dist < exposed[cname]["distance_km"]:
                    exposed[cname] = {
                        "city": cname,
                        "country": city["country"],
                        "lat": city["lat"],
                        "lon": city["lon"],
                        "population": city["pop"],
                        "distance_km": round(dist, 1),
                        "nearest_event": event.get("type", "unknown"),
                        "event_detail": event.get("detail", ""),
                    }

    return sorted(exposed.values(), key=lambda c: c["distance_km"])


async def fetch_population_exposure(
    fetcher,
    radius_km: float = 200.0,
    event_types: list[str] | None = None,
) -> dict:
    """Estimate population exposure near active earthquake events.

    Fetches M4.5+ earthquakes from the past 48 hours, then finds major
    cities within radius_km of each event.

    Args:
        fetcher: Shared HTTP fetcher.
        radius_km: Search radius in km (default 200).
        event_types: Accepted for API compatibility; only 'earthquake' is supported.
    """
    from ..config.population import MAJOR_CITIES
    from ..sources import seismology

    eq_data = await safe_fetch(
        seismology.fetch_earthquakes(fetcher, min_magnitude=4.5, hours=48, limit=50),
        "earthquake",
    )

    events: list[dict] = []
    for eq in (eq_data or {}).get("earthquakes", []):
        lat = eq.get("latitude") or eq.get("lat")
        lon = eq.get("longitude") or eq.get("lon")
        if lat is not None and lon is not None:
            events.append({
                "lat": float(lat),
                "lon": float(lon),
                "type": "earthquake",
                "detail": f"M{eq.get('magnitude', '?')} {eq.get('place', '')}",
            })

    exposed_cities = _find_exposed_cities(events, MAJOR_CITIES, radius_km)
    total_exposed_pop = sum(c["population"] for c in exposed_cities)

    by_country: dict[str, int] = {}
    for c in exposed_cities:
        country = c["country"]
        by_country[country] = by_country.get(country, 0) + c["population"]

    return {
        "exposed_cities": exposed_cities,
        "exposed_city_count": len(exposed_cities),
        "total_exposed_population": total_exposed_pop,
        "total_exposed_population_formatted": _format_pop(total_exposed_pop),
        "by_event_type": {"earthquake": _format_pop(total_exposed_pop)} if exposed_cities else {},
        "by_country": {k: _format_pop(v) for k, v in sorted(by_country.items(), key=lambda x: x[1], reverse=True)[:10]},
        "events_analyzed": len(events),
        "radius_km": radius_km,
        "event_types": ["earthquake"],
        "source": "population-exposure-analysis",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def _format_pop(pop: int) -> str:
    if pop >= 1_000_000:
        return f"{pop / 1_000_000:.1f}M"
    elif pop >= 1_000:
        return f"{pop / 1_000:.0f}K"
    return str(pop)
