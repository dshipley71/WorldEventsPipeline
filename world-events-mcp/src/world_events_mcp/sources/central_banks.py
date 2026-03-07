"""Central bank policy rates — curated static dataset.

Returns the most recently known policy rates for 15 major central banks.
No API key required.  Data is curated and updated periodically in code.
"""

import logging
from datetime import datetime, timezone

from ..fetcher import Fetcher

logger = logging.getLogger("world-events-mcp.sources.central_banks")


# ---------------------------------------------------------------------------
# Curated policy rates (updated periodically)
# ---------------------------------------------------------------------------

_CURATED_RATES: list[dict] = [
    {"bank": "Federal Reserve", "country": "USA", "currency": "USD",
     "label": "Federal Funds Rate", "rate": 4.50, "as_of": "2025-01-29",
     "notes": "Fed funds target rate (upper bound)"},
    {"bank": "European Central Bank", "country": "EUR", "currency": "EUR",
     "label": "ECB Deposit Facility Rate", "rate": 2.75, "as_of": "2025-01-30",
     "notes": "Deposit facility rate"},
    {"bank": "Bank of England", "country": "GBR", "currency": "GBP",
     "label": "BoE Bank Rate", "rate": 4.50, "as_of": "2025-02-06",
     "notes": "Bank rate"},
    {"bank": "Bank of Japan", "country": "JPN", "currency": "JPY",
     "label": "BoJ Policy Rate", "rate": 0.50, "as_of": "2025-01-24",
     "notes": "Short-term policy rate target"},
    {"bank": "People's Bank of China", "country": "CHN", "currency": "CNY",
     "label": "PBoC LPR 1Y", "rate": 3.10, "as_of": "2025-01-20",
     "notes": "1-year Loan Prime Rate"},
    {"bank": "Reserve Bank of India", "country": "IND", "currency": "INR",
     "label": "RBI Repo Rate", "rate": 6.50, "as_of": "2025-02-07",
     "notes": "Policy repo rate"},
    {"bank": "Reserve Bank of Australia", "country": "AUS", "currency": "AUD",
     "label": "RBA Cash Rate", "rate": 4.35, "as_of": "2024-11-05",
     "notes": "Cash rate target"},
    {"bank": "Bank of Canada", "country": "CAN", "currency": "CAD",
     "label": "BoC Overnight Rate", "rate": 3.25, "as_of": "2024-12-11",
     "notes": "Target for the overnight rate"},
    {"bank": "Swiss National Bank", "country": "CHE", "currency": "CHF",
     "label": "SNB Policy Rate", "rate": 0.50, "as_of": "2024-12-12",
     "notes": "SNB policy rate"},
    {"bank": "Central Bank of Brazil", "country": "BRA", "currency": "BRL",
     "label": "BCB SELIC", "rate": 13.25, "as_of": "2025-01-29",
     "notes": "SELIC target rate"},
    {"bank": "Bank of Korea", "country": "KOR", "currency": "KRW",
     "label": "BoK Base Rate", "rate": 3.00, "as_of": "2025-01-16",
     "notes": "Base rate"},
    {"bank": "Central Bank of Turkey", "country": "TUR", "currency": "TRY",
     "label": "CBRT Policy Rate", "rate": 45.00, "as_of": "2025-01-23",
     "notes": "1-week repo rate"},
    {"bank": "South African Reserve Bank", "country": "ZAF", "currency": "ZAR",
     "label": "SARB Repo Rate", "rate": 7.75, "as_of": "2024-11-21",
     "notes": "Repurchase rate"},
    {"bank": "Banco de México", "country": "MEX", "currency": "MXN",
     "label": "Banxico Target Rate", "rate": 10.00, "as_of": "2025-02-06",
     "notes": "Overnight interbank rate target"},
    {"bank": "Bank Indonesia", "country": "IDN", "currency": "IDR",
     "label": "BI Rate", "rate": 5.75, "as_of": "2025-01-15",
     "notes": "BI-Rate"},
]


async def fetch_central_bank_rates(fetcher: Fetcher) -> dict:
    """Return policy rates for 15 major central banks from curated data.

    No API key required.  The ``fetcher`` argument is accepted for interface
    consistency but is not used by this function.

    Returns::

        {"rates": [{bank, country, currency, rate, as_of, source, notes}],
         "count": int, "source": "curated", "timestamp": "<iso>"}
    """
    rates = [
        {**entry, "source": "curated"}
        for entry in _CURATED_RATES
    ]
    # Sort by rate descending (most hawkish first)
    rates.sort(key=lambda r: r.get("rate", 0), reverse=True)

    return {
        "rates": rates,
        "count": len(rates),
        "source": "curated",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
