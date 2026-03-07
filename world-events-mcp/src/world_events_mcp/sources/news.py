"""RSS news aggregation, keyword trending, and GDELT search for world-events-mcp.

Provides multi-category RSS feed aggregation from 20+ high-quality intelligence
and news sources, keyword spike detection from recent headlines, and full-text
search via the GDELT 2.0 Doc API. No API keys required.
"""

import asyncio
import logging
import re
import string
from datetime import datetime, timezone

from ..fetcher import Fetcher

try:
    import feedparser
except ImportError:
    feedparser = None  # type: ignore[assignment]

logger = logging.getLogger("world-events-mcp.sources.news")


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_RSS_FEEDS: dict[str, list[tuple[str, str]]] = {
    "geopolitics": [
        ("BBC World", "https://feeds.bbci.co.uk/news/world/rss.xml"),
        ("Al Jazeera", "https://www.aljazeera.com/xml/rss/all.xml"),
        ("AP Top News", "https://feeds.apnews.com/rss/apf-topnews"),
        ("Reuters World", "https://news.google.com/rss/search?q=source:Reuters&hl=en-US&gl=US&ceid=US:en"),
        ("The Guardian World", "https://www.theguardian.com/world/rss"),
        ("DW News", "https://rss.dw.com/xml/rss-en-all"),
        ("France24", "https://www.france24.com/en/rss"),
        ("NPR World", "https://feeds.npr.org/1004/rss.xml"),
        ("VOA News", "https://feeds.voanews.com/rss/english/top_stories.rss"),
    ],
    "security": [
        ("BleepingComputer", "https://www.bleepingcomputer.com/feed/"),
        ("Krebs on Security", "https://krebsonsecurity.com/feed/"),
        ("The Hacker News", "https://feeds.feedburner.com/TheHackersNews"),
        ("Schneier on Security", "https://www.schneier.com/feed/atom/"),
        ("Dark Reading", "https://www.darkreading.com/rss.xml"),
        ("CISA Alerts", "https://www.cisa.gov/cybersecurity-advisories/all.xml"),
        ("The Record", "https://therecord.media/feed"),
        ("Security Week", "https://www.securityweek.com/feed/"),
    ],
    "technology": [
        ("Ars Technica", "https://feeds.arstechnica.com/arstechnica/index"),
        ("TechCrunch", "https://techcrunch.com/feed/"),
        ("The Verge", "https://www.theverge.com/rss/index.xml"),
        ("Wired", "https://www.wired.com/feed/rss"),
        ("MIT Tech Review", "https://www.technologyreview.com/feed/"),
        ("The Register", "https://www.theregister.com/headlines.atom"),
    ],
    "finance": [
        ("CNBC", "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100003114"),
        ("MarketWatch", "https://feeds.content.dowjones.io/public/rss/mw_topstories"),
        ("FT World", "https://news.google.com/rss/search?q=site:ft.com&hl=en-US&gl=US&ceid=US:en"),
        ("Bloomberg Markets", "https://news.google.com/rss/search?q=bloomberg+markets+finance&hl=en-US&gl=US&ceid=US:en"),
        ("WSJ World News", "https://feeds.a.dj.com/rss/RSSWorldNews.xml"),        ("Zero Hedge", "https://feeds.feedburner.com/zerohedge/feed"),
    ],
    "military": [
        ("Defense One", "https://www.defenseone.com/rss/all/"),
        ("War on the Rocks", "https://warontherocks.com/feed/"),
        ("The War Zone", "https://www.twz.com/feed"),
        ("Breaking Defense", "https://breakingdefense.com/feed/"),
        ("Military Times", "https://www.militarytimes.com/arc/outboundfeeds/rss/?outputType=xml"),
        ("USNI News", "https://news.usni.org/feed"),
    ],
    "science": [
        ("Nature", "https://www.nature.com/nature.rss"),
        ("Science", "https://www.science.org/action/showFeed?type=etoc&feed=rss&jc=science"),
        ("Phys.org", "https://phys.org/rss-feed/"),
        ("New Scientist", "https://www.newscientist.com/feed/home/"),
        ("Scientific American", "https://rss.sciam.com/ScientificAmerican-Global"),
        ("SpaceNews", "https://spacenews.com/feed/"),
    ],
    "think_tanks": [
        ("RAND", "https://www.rand.org/blog.xml"),
        ("Brookings", "https://www.brookings.edu/feed/"),
        ("Carnegie", "https://carnegieendowment.org/rss/solr.xml"),
        ("CFR", "https://www.cfr.org/rss/all"),
        ("CSIS", "https://www.csis.org/rss/all"),
        ("Atlantic Council", "https://www.atlanticcouncil.org/feed/"),
        ("Chatham House", "https://www.chathamhouse.org/rss/all"),
    ],
    "middle_east": [
        ("Middle East Eye", "https://www.middleeasteye.net/rss"),
        ("The National UAE", "https://www.thenationalnews.com/arc/outboundfeeds/rss/?outputType=xml"),
        ("Times of Israel", "https://www.timesofisrael.com/feed/"),
        ("Iran Intl", "https://www.iranintl.com/en/feed"),
    ],
    "asia_pacific": [
        ("SCMP", "https://www.scmp.com/rss/91/feed"),
        ("Nikkei Asia", "https://asia.nikkei.com/rss/feed/nar"),
        ("The Diplomat", "https://thediplomat.com/feed/"),
        ("Channel News Asia", "https://www.channelnewsasia.com/api/v1/rss-outbound-feed?_format=xml"),
        ("Lowy Interpreter", "https://www.lowyinstitute.org/the-interpreter/rss.xml"),
    ],
    "africa": [
        ("allAfrica", "https://allafrica.com/tools/headlines/rdf/latest/headlines.rdf"),
        ("The Africa Report", "https://www.theafricareport.com/feed/"),
        ("African Arguments", "https://africanarguments.org/feed/"),
        ("ISS Africa", "https://issafrica.org/iss-today/feed"),
        ("Daily Maverick", "https://www.dailymaverick.co.za/article/feed/"),
    ],
    "latin_america": [
        ("MercoPress", "https://en.mercopress.com/rss"),
        ("Dialogo Americas", "https://dialogo-americas.com/feed/"),
        ("Americas Quarterly", "https://www.americasquarterly.org/feed/"),
        ("Buenos Aires Times", "https://www.batimes.com.ar/feed"),
        ("Tico Times", "https://ticotimes.net/feed"),
        ("InSight Crime", "https://insightcrime.org/feed/"),
        ("Brazil Reports", "https://brazilian.report/feed/"),
        ("Mexico News Daily", "https://mexiconewsdaily.com/feed/"),
    ],
    "multilingual": [
        ("BBC Mundo", "https://feeds.bbci.co.uk/mundo/rss.xml"),
        ("DW Español", "https://rss.dw.com/xml/rss-es-all"),
        ("DW Deutsch", "https://rss.dw.com/xml/rss-de-all"),        ("France24 Français", "https://www.france24.com/fr/rss"),
        ("RFI Français", "https://www.rfi.fr/fr/rss"),
        ("UN News Español", "https://news.un.org/feed/subscribe/es/news/all/rss.xml"),
        ("UN News Français", "https://news.un.org/feed/subscribe/fr/news/all/rss.xml"),
    ],
    "energy": [
        ("Oil Price", "https://oilprice.com/rss/main"),
        ("Rigzone", "https://www.rigzone.com/news/rss/rigzone_latest.aspx"),
        ("Utility Dive", "https://www.utilitydive.com/feeds/news/"),
        ("Carbon Brief", "https://www.carbonbrief.org/feed/"),
        ("CleanTechnica", "https://cleantechnica.com/feed/"),
    ],
    "government": [
        ("State Dept", "https://www.state.gov/rss-feed/press-releases/feed/"),
        ("DoD News", "https://www.defense.gov/DesktopModules/ArticleCS/RSS.ashx?ContentType=1&Site=945&max=10"),
        ("UN News", "https://news.un.org/feed/subscribe/en/news/all/rss.xml"),
        ("White House", "https://www.whitehouse.gov/feed/"),
    ],
    "crisis": [
        ("ReliefWeb", "https://reliefweb.int/updates/rss.xml"),
        ("ICG", "https://www.crisisgroup.org/rss.xml"),
        ("Amnesty Intl", "https://www.amnesty.org/en/feed/"),
        ("HRW", "https://www.hrw.org/rss/news_releases"),
    ],
    "europe": [
        ("EurActiv", "https://www.euractiv.com/feed/"),
        ("Politico EU", "https://www.politico.eu/feed/"),
        ("EU Observer", "https://euobserver.com/rss"),
        ("DW Europe", "https://rss.dw.com/rss/en/eu/rss-en-eu"),
    ],
    "south_asia": [
        ("NDTV", "https://feeds.feedburner.com/ndtvnews-top-stories"),
        ("Dawn Pakistan", "https://www.dawn.com/feeds/home"),
        ("Scroll India", "https://scroll.in/feed"),
    ],
    "health": [
        ("STAT News", "https://www.statnews.com/feed/"),
        ("WHO News", "https://www.who.int/rss-feeds/news-english.xml"),
        ("Medical Xpress", "https://medicalxpress.com/rss-feed/"),
        ("The Lancet", "https://www.thelancet.com/rssfeed/lancet_current.xml"),
    ],
    "central_asia": [
        ("Eurasianet", "https://eurasianet.org/feed"),
        ("The Astana Times", "https://astanatimes.com/feed/"),
        ("Radio Free Europe", "https://www.rferl.org/api/zyrttemnuq"),
    ],
    "arctic": [
        ("The Barents Observer", "https://thebarentsobserver.com/en/rss.xml"),
        ("Arctic Today", "https://www.arctictoday.com/feed/"),
        ("High North News", "https://www.highnorthnews.com/en/rss.xml"),
    ],
    "maritime": [
        ("Maritime Executive", "https://maritime-executive.com/feed"),
        ("gCaptain", "https://gcaptain.com/feed/"),
        ("Lloyd's List", "https://lloydslist.maritimeintelligence.informa.com/rss/all"),
    ],
    "space": [
        ("SpaceRef", "https://spaceref.com/feed/"),
        ("NASASpaceFlight", "https://www.nasaspaceflight.com/feed/"),
        ("Space.com", "https://www.space.com/feeds/all"),
    ],
    "nuclear": [
        ("World Nuclear News", "https://world-nuclear-news.org/rss"),
        ("Arms Control Assn", "https://www.armscontrol.org/rss/all"),
        ("Nuclear Threat Initiative", "https://www.nti.org/feed/"),
    ],
    "climate": [
        ("Climate Home News", "https://www.climatechangenews.com/feed/"),
        ("InsideClimate News", "https://insideclimatenews.org/feed/"),
        ("E&E News", "https://www.eenews.net/feed/"),
    ],
}

# Source tier classification for propaganda/reliability scoring
SOURCE_TIERS: dict[str, str] = {
    "AP Top News": "wire",
    "Reuters World": "wire",
    "BBC World": "major",
    "Al Jazeera": "major",
    "The Guardian World": "major",
    "DW News": "major",
    "France24": "major",
    "CNBC": "major",
    "FT World": "major",
    "Bloomberg": "major",
    "WSJ Markets": "major",
    "Nature": "major",
    "Science": "major",
    "Defense One": "specialty",
    "Breaking Defense": "specialty",
    "USNI News": "specialty",
    "War on the Rocks": "specialty",
    "The War Zone": "specialty",
    "Military Times": "specialty",
    "RAND": "think_tank",
    "Brookings": "think_tank",
    "Carnegie": "think_tank",
    "ICG": "think_tank",
    "BleepingComputer": "specialty",
    "Krebs on Security": "specialty",
    "The Hacker News": "specialty",
    "CISA Alerts": "government",
    "State Dept": "government",
    "DoD News": "government",
    "UN News": "government",
    "ReliefWeb": "intl_org",
    "Lowy Interpreter": "think_tank",
    "Dialogo Americas": "specialty",
    "InSight Crime": "specialty",
    "Brazil Reports": "specialty",
    "Mexico News Daily": "specialty",
    "BBC Mundo": "major",
    "DW Español": "major",
    "DW Deutsch": "major",
    "France24 Français": "major",
    "RFI Français": "major",
    "UN News Español": "government",
    "UN News Français": "government",
    "Nikkei Asia": "major",
    "The National UAE": "major",
    "Zero Hedge": "aggregator",
    # Phase 15 additions
    "NPR World": "major",
    "VOA News": "government",
    "The Record": "specialty",
    "Security Week": "specialty",
    "Scientific American": "major",
    "SpaceNews": "specialty",
    "CFR": "think_tank",
    "CSIS": "think_tank",
    "Atlantic Council": "think_tank",
    "Chatham House": "think_tank",
    "The Africa Report": "specialty",
    "African Arguments": "specialty",
    "ISS Africa": "think_tank",
    "Daily Maverick": "major",
    "Carbon Brief": "specialty",
    "CleanTechnica": "specialty",
    "EurActiv": "specialty",
    "Politico EU": "major",
    "EU Observer": "specialty",
    "DW Europe": "major",
    "NDTV": "major",
    "Dawn Pakistan": "major",
    "Scroll India": "specialty",
    "STAT News": "specialty",
    "WHO News": "intl_org",
    "Medical Xpress": "specialty",
    "Amnesty Intl": "intl_org",
    "HRW": "intl_org",
    "The Register": "specialty",
    "White House": "government",
    # Phase 16 additions
    "The Lancet": "major",
    "Eurasianet": "specialty",
    "The Astana Times": "specialty",
    "Radio Free Europe": "government",
    "The Barents Observer": "specialty",
    "Arctic Today": "specialty",
    "High North News": "specialty",
    "Maritime Executive": "specialty",
    "gCaptain": "specialty",
    "Lloyd's List": "specialty",
    "SpaceRef": "specialty",
    "NASASpaceFlight": "specialty",
    "Space.com": "major",
    "World Nuclear News": "specialty",
    "Arms Control Assn": "think_tank",
    "Nuclear Threat Initiative": "think_tank",
    "Climate Home News": "specialty",
    "InsideClimate News": "specialty",
    "E&E News": "specialty",
}

_STOPWORDS: set[str] = {
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "shall",
    "should", "may", "might", "must", "can", "could", "in", "on", "at",
    "to", "for", "of", "and", "or", "but", "nor", "not", "no", "so",
    "yet", "both", "either", "neither", "with", "from", "by", "as",
    "into", "through", "during", "before", "after", "above", "below",
    "between", "under", "over", "about", "against", "out", "off", "up",
    "down", "then", "once", "here", "there", "when", "where", "why",
    "how", "all", "each", "every", "any", "few", "more", "most", "some",
    "such", "only", "own", "same", "than", "too", "very", "just", "also",
    "now", "it", "its", "he", "she", "they", "them", "their", "his",
    "her", "we", "you", "your", "our", "my", "me", "him", "us",
    "that", "this", "these", "those", "which", "who", "whom", "what",
    "if", "while", "because", "until", "although", "since", "whether",
    "new", "says", "said", "one", "two", "first", "last", "many",
    "much", "get", "got", "back", "even", "still", "well", "way",
    "s", "t", "re", "ve", "d", "ll", "m",
}

_GDELT_DOC_URL = "https://api.gdeltproject.org/api/v2/doc/doc"

# Regex to strip punctuation from words
_PUNCT_RE = re.compile(f"[{re.escape(string.punctuation)}]")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_published(entry: dict) -> str | None:
    """Parse an RSS entry's published date to ISO 8601 UTC string.

    feedparser stores the parsed time struct in ``published_parsed`` as a
    UTC time.struct_time.  We use ``calendar.timegm()`` (not ``time.mktime()``)
    to convert it, because mktime() assumes the struct is in *local* time and
    would produce incorrect results on any server not running in UTC.

    Falls back to the raw ``published`` string if parsing fails.
    """
    import calendar

    parsed_tuple = entry.get("published_parsed")
    if parsed_tuple is not None:
        try:
            epoch = calendar.timegm(parsed_tuple[:9])
            dt = datetime.fromtimestamp(epoch, tz=timezone.utc)
            return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        except (ValueError, TypeError, OverflowError):
            pass

    # Fallback: try updated_parsed
    updated_tuple = entry.get("updated_parsed")
    if updated_tuple is not None:
        try:
            import calendar as _cal
            epoch = _cal.timegm(updated_tuple[:9])
            dt = datetime.fromtimestamp(epoch, tz=timezone.utc)
            return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        except (ValueError, TypeError, OverflowError):
            pass

    # Last resort: return raw string or None
    return entry.get("published") or entry.get("updated")


def _truncate(text: str | None, max_len: int = 200) -> str:
    """Truncate text to max_len characters, appending '...' if trimmed."""
    if not text:
        return ""
    if len(text) <= max_len:
        return text
    return text[:max_len] + "..."


# ---------------------------------------------------------------------------
# Function 1: RSS News Feed Aggregation
# ---------------------------------------------------------------------------

async def fetch_news_feed(
    fetcher: Fetcher,
    category: str | None = None,
    limit: int = 50,
) -> dict:
    """Aggregate news from 20+ RSS feeds across intelligence/news categories.

    Uses ``feedparser`` to parse RSS/Atom feeds fetched via the shared HTTP
    fetcher. Feeds within each category are fetched in parallel.

    Args:
        fetcher: Shared HTTP fetcher with caching and circuit breaking.
        category: Optional category key (geopolitics, security, technology,
                  finance, military, science). If None, fetches all categories.
        limit: Maximum number of items to return.

    Returns:
        Dict with items list, count, categories fetched, source, and timestamp.
    """
    if feedparser is None:
        return {
            "error": "feedparser not installed — run: pip install feedparser",
            "items": [],
            "count": 0,
        }

    now = datetime.now(timezone.utc)

    # Determine which categories to fetch
    if category is not None:
        if category not in _RSS_FEEDS:
            return {
                "items": [],
                "count": 0,
                "categories_fetched": [],
                "error": f"Unknown category '{category}'. Valid: {list(_RSS_FEEDS.keys())}",
                "source": "rss-aggregator",
                "timestamp": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
        categories_to_fetch = {category: _RSS_FEEDS[category]}
    else:
        categories_to_fetch = dict(_RSS_FEEDS)

    all_items: list[dict] = []

    async def _fetch_single_feed(
        feed_name: str,
        url: str,
        cat: str,
    ) -> list[dict]:
        """Fetch and parse a single RSS feed, returning extracted items."""
        safe_name = feed_name.lower().replace(" ", "_")
        xml_text = await fetcher.get_xml(
            url,
            source=f"rss:{safe_name}",
            cache_key=f"news:rss:{safe_name}",
            cache_ttl=300,
            timeout=8.0,
        )

        if xml_text is None:
            logger.debug("No data from RSS feed %s (%s)", feed_name, url)
            return []

        parsed = feedparser.parse(xml_text)
        items: list[dict] = []

        for entry in parsed.get("entries", []):
            published = _parse_published(entry)
            summary_raw = entry.get("summary") or entry.get("description") or ""
            items.append({
                "title": entry.get("title", ""),
                "link": entry.get("link", ""),
                "published": published,
                "summary": _truncate(summary_raw, 200),
                "feed_name": feed_name,
                "category": cat,
                "source_tier": SOURCE_TIERS.get(feed_name, "unknown"),
            })

        return items

    async def _safe_fetch(feed_name: str, url: str, cat: str) -> list[dict]:
        """Wrap single feed fetch with a hard timeout."""
        try:
            return await asyncio.wait_for(
                _fetch_single_feed(feed_name, url, cat), timeout=12.0,
            )
        except asyncio.TimeoutError:
            logger.debug("RSS feed %s timed out", feed_name)
            return []

    # Fetch ALL feeds across ALL categories in one parallel batch
    all_tasks = [
        _safe_fetch(feed_name, url, cat)
        for cat, feeds in categories_to_fetch.items()
        for feed_name, url in feeds
    ]
    results = await asyncio.gather(*all_tasks)
    for items in results:
        all_items.extend(items)

    # Sort by published date descending (entries without dates go last)
    all_items.sort(
        key=lambda item: item.get("published") or "",
        reverse=True,
    )

    # Apply limit
    all_items = all_items[:limit]

    return {
        "items": all_items,
        "count": len(all_items),
        "categories_fetched": list(categories_to_fetch.keys()),
        "source": "rss-aggregator",
        "timestamp": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


# ---------------------------------------------------------------------------
# Function 2: Keyword Trending / Spike Detection
# ---------------------------------------------------------------------------

async def fetch_trending_keywords(
    fetcher: Fetcher,
    hours: int = 6,
    min_count: int = 3,
) -> dict:
    """Detect trending keywords from recent news headlines.

    Fetches up to 200 recent news items via ``fetch_news_feed``, extracts
    words from titles, removes stopwords and short tokens, and returns the
    most frequently occurring keywords sorted by count.

    Args:
        fetcher: Shared HTTP fetcher with caching and circuit breaking.
        hours: Not used for time-windowing (RSS feeds are inherently recent),
               but kept for API symmetry with other source functions.
        min_count: Minimum occurrences for a keyword to be included.

    Returns:
        Dict with keywords list (word + count), total items analyzed,
        source, and timestamp.
    """
    now = datetime.now(timezone.utc)

    # Fetch a broad set of recent items
    feed_data = await fetch_news_feed(fetcher, limit=200)
    items = feed_data.get("items", [])

    # Count word frequencies across all titles
    word_counts: dict[str, int] = {}
    for item in items:
        title = item.get("title") or ""
        # Lowercase, strip punctuation, split into words
        cleaned = _PUNCT_RE.sub(" ", title.lower())
        words = cleaned.split()
        for word in words:
            word = word.strip()
            if len(word) < 3:
                continue
            if word in _STOPWORDS:
                continue
            word_counts[word] = word_counts.get(word, 0) + 1

    # Filter by min_count and sort descending
    keywords = [
        {"word": word, "count": count}
        for word, count in word_counts.items()
        if count >= min_count
    ]
    keywords.sort(key=lambda k: k["count"], reverse=True)

    # Return top 50
    keywords = keywords[:50]

    return {
        "keywords": keywords,
        "total_items_analyzed": len(items),
        "source": "keyword-analysis",
        "timestamp": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


# ---------------------------------------------------------------------------
# Function 3: GDELT 2.0 Doc API Search
# ---------------------------------------------------------------------------

async def fetch_gdelt_search(
    fetcher: Fetcher,
    query: str = "conflict",
    mode: str = "artlist",
    limit: int = 75,
    timespan: str | None = None,
    sort: str | None = None,
    startdatetime: str | None = None,
    enddatetime: str | None = None,
    sourcelang: str | None = None,
    sourcecountry: str | None = None,
    theme: str | None = None,
    timelinesmooth: int | None = None,
) -> dict:
    """Search the GDELT 2.0 Doc API for articles, timelines, and tone analysis.

    No API key required. Supports all GDELT DOC 2.0 JSON-compatible modes:
    artlist, timelinevol, timelinevolraw, timelinevolinfo, timelinetone,
    timelinesourcecountry, timelinelang, and tonechart.

    Query operators (embed directly in `query` string):
      - Phrase:          "north korea"
      - Boolean OR:      (iran OR iraq OR syria)
      - Exclude:         conflict -sport
      - Domain filter:   domain:reuters.com
      - Exact domain:    domainis:bbc.co.uk
      - Proximity:       near20:"missile launch"
      - Repeat:          repeat3:"sanctions"
      - Tone filter:     tone<-5  or  tone>3
      - Theme:           theme:TERROR  (or use the `theme` param)
      - Source country:  sourcecountry:RS  (or use `sourcecountry` param)
      - Source language: sourcelang:zh  (or use `sourcelang` param)

    Args:
        fetcher:          Shared HTTP fetcher with caching and circuit breaking.
        query:            Search query string. Supports all GDELT query operators.
        mode:             Output mode. One of:
                            artlist              – list of matching articles (default)
                            timelinevol          – coverage % of global news by time step
                            timelinevolraw       – raw article counts by time step
                            timelinevolinfo      – timelinevol + top-10 articles per spike
                            timelinetone         – average tone of coverage by time step
                            timelinesourcecountry– coverage volume broken down by country
                            timelinelang         – coverage volume broken down by language
                            tonechart            – emotional histogram (tone distribution)
        limit:            Max records for artlist mode (default 75, max 250).
        timespan:         Relative time window: e.g. "15min", "6h", "7d", "2w", "3m".
                          Omit to use the GDELT default (~3 months).
                          Mutually exclusive with startdatetime/enddatetime.
        sort:             Article sort order for artlist mode. Options:
                            DateDesc  – newest first (recommended for monitoring)
                            DateAsc   – oldest first
                            ToneDesc  – most positive first
                            ToneAsc   – most negative first (useful for threat monitoring)
                            HybridRel – relevance + source popularity (default)
        startdatetime:    Precise search start in YYYYMMDDHHMMSS format (UTC).
                          Must be within the last 3 months.
        enddatetime:      Precise search end in YYYYMMDDHHMMSS format (UTC).
                          Must be within the last 3 months.
        sourcelang:       ISO 639 language code to restrict source articles
                          (e.g. "zh", "ru", "ar", "es", "fr"). Equivalent to
                          embedding "sourcelang:X" in the query.
        sourcecountry:    FIPS-2 country code to restrict source outlets
                          (e.g. "RS", "CN", "IR", "US"). Equivalent to
                          embedding "sourcecountry:X" in the query.
        theme:            GDELT GKG theme code for broad topic matching
                          (e.g. "TERROR", "MILITARY", "WMD", "ELECTION_FRAUD",
                          "PROTEST", "SANCTION", "CYBER_ATTACK"). Equivalent to
                          embedding "theme:X" in the query.
        timelinesmooth:   Moving-window smoothing steps for timeline modes (1–30).
                          Reduces noise in high-resolution timelines. Peaks shift
                          slightly right at higher values.

    Returns:
        Dict with articles/timeline data, count, query info, source, and timestamp.
        For timelinevolinfo mode, also includes per-step top articles.
        For tonechart mode, returns tone distribution bins.
    """
    now = datetime.now(timezone.utc)

    # --- Validate mode ---
    _ARTLIST_MODES = {"artlist"}
    _TIMELINE_MODES = {
        "timelinevol", "timelinevolraw", "timelinevolinfo",
        "timelinetone", "timelinesourcecountry", "timelinelang",
    }
    _TONECHART_MODES = {"tonechart"}
    _ALL_MODES = _ARTLIST_MODES | _TIMELINE_MODES | _TONECHART_MODES
    mode_lower = mode.lower()
    if mode_lower not in _ALL_MODES:
        logger.warning("Unknown GDELT mode '%s', falling back to artlist", mode)
        mode_lower = "artlist"

    # --- Validate and clamp limit ---
    limit = max(1, min(int(limit), 250))

    # --- Build convenience operator injections into query ---
    query_parts = [query.strip()]
    if sourcelang:
        query_parts.append(f"sourcelang:{sourcelang.strip()}")
    if sourcecountry:
        query_parts.append(f"sourcecountry:{sourcecountry.strip()}")
    if theme:
        query_parts.append(f"theme:{theme.strip().upper()}")
    effective_query = " ".join(query_parts)

    # --- Build API params ---
    params: dict = {
        "query": effective_query,
        "mode": mode_lower,
        "format": "json",
    }

    # maxrecords applies only to artlist (GDELT docs: ignored in all other modes)
    if mode_lower in _ARTLIST_MODES:
        params["maxrecords"] = limit

    # Time window: prefer precise datetime range over relative timespan
    if startdatetime:
        params["startdatetime"] = startdatetime
        if enddatetime:
            params["enddatetime"] = enddatetime
    elif enddatetime:
        params["enddatetime"] = enddatetime
    elif timespan:
        # timespan only meaningful for artlist + timeline modes
        if mode_lower in (_ARTLIST_MODES | _TIMELINE_MODES):
            params["timespan"] = timespan

    # Sort applies to artlist only
    if sort and mode_lower in _ARTLIST_MODES:
        params["sort"] = sort

    # Smoothing applies to timeline modes only (1-30 steps)
    if timelinesmooth is not None and mode_lower in _TIMELINE_MODES:
        params["TIMELINESMOOTH"] = max(1, min(int(timelinesmooth), 30))

    # --- Cache key: include all differentiating params ---
    safe_query = re.sub(r"[^a-zA-Z0-9_-]", "_", effective_query)[:64]
    safe_ts = re.sub(r"[^a-zA-Z0-9]", "_", timespan or startdatetime or "default")[:20]
    cache_key = f"news:gdelt:{safe_query}:{mode_lower}:{safe_ts}:{limit}:{sort or 'def'}"

    data = await fetcher.get_json(
        _GDELT_DOC_URL,
        source="gdelt",
        cache_key=cache_key,
        cache_ttl=600,
        params=params,
    )

    # --- Build meta block shared across all response types ---
    meta = {
        "query": effective_query,
        "mode": mode_lower,
        "timespan": timespan,
        "startdatetime": startdatetime,
        "enddatetime": enddatetime,
        "source": "gdelt",
        "timestamp": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

    if data is None:
        logger.warning("GDELT API returned no data for query=%s mode=%s", effective_query, mode_lower)
        empty: dict = {"count": 0, **meta}
        if mode_lower in _ARTLIST_MODES:
            empty["articles"] = []
        elif mode_lower in _TIMELINE_MODES:
            empty["timeline"] = []
        else:
            empty["tone_bins"] = []
        return empty

    # --- artlist mode ---
    if mode_lower in _ARTLIST_MODES:
        articles = []
        for article in data.get("articles", []):
            articles.append({
                "title": article.get("title"),
                "url": article.get("url"),
                "seendate": article.get("seendate"),
                "socialimage": article.get("socialimage"),
                "domain": article.get("domain"),
                "language": article.get("language"),
                "sourcecountry": article.get("sourcecountry"),
            })
        return {"articles": articles, "count": len(articles), **meta}

    # --- timelinevolinfo: timeline + per-step top articles ---
    if mode_lower == "timelinevolinfo":
        timeline = data.get("timeline", [])
        # GDELT embeds top articles per step as {"date":..., "value":..., "topartlist":[...]}
        steps = []
        if isinstance(timeline, list) and timeline:
            series = timeline[0] if isinstance(timeline[0], dict) else {}
            for step in series.get("data", []):
                entry = {
                    "date": step.get("date"),
                    "value": step.get("value"),
                }
                top = step.get("topartlist", [])
                if top:
                    entry["top_articles"] = [
                        {
                            "title": a.get("title"),
                            "url": a.get("url"),
                            "domain": a.get("domain"),
                            "seendate": a.get("seendate"),
                        }
                        for a in top[:10]
                    ]
                steps.append(entry)
        return {"timeline": steps, "count": len(steps), **meta}

    # --- tonechart mode: tone distribution bins ---
    if mode_lower in _TONECHART_MODES:
        tone_data = data.get("tonechart", data.get("tones", []))
        bins = []
        if isinstance(tone_data, list):
            for b in tone_data:
                bins.append({
                    "bin": b.get("bin") or b.get("tone"),
                    "count": b.get("count") or b.get("topcontent", 0),
                })
        return {"tone_bins": bins, "count": len(bins), **meta}

    # --- timelinesourcecountry / timelinelang: multi-series timelines ---
    if mode_lower in {"timelinesourcecountry", "timelinelang"}:
        raw = data.get("timeline", [])
        series_out = []
        if isinstance(raw, list):
            for series in raw:
                if isinstance(series, dict):
                    series_out.append({
                        "series": series.get("series", ""),
                        "data": series.get("data", []),
                    })
        return {"timeline": series_out, "series_count": len(series_out), **meta}

    # --- timelinevol / timelinevolraw / timelinetone: standard single-series ---
    raw = data.get("timeline", [])
    # GDELT wraps the series in a list; extract the first (and usually only) series
    if isinstance(raw, list) and raw and isinstance(raw[0], dict):
        timeline_data = raw[0].get("data", raw)
    else:
        timeline_data = raw if isinstance(raw, list) else []
    return {
        "timeline": timeline_data,
        "count": len(timeline_data) if isinstance(timeline_data, list) else 0,
        **meta,
    }
