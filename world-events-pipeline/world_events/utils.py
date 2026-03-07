"""
world_events/utils.py

Pure utility helpers — no agent or model dependencies, safe to import anywhere.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from world_events.models import Article


# ── Datetime ──────────────────────────────────────────────────────────────────

def parse_iso_datetime(value: str) -> Optional[datetime]:
    """Parse an ISO 8601 string and normalise to a naive UTC datetime."""
    try:
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is not None:
            dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt
    except Exception:
        return None


def published_str(a: Article) -> str:
    """ISO string for an article's published datetime; 'unknown' if absent."""
    if a.published is None:
        return "unknown"
    return a.published.replace(tzinfo=timezone.utc).isoformat()


# ── MCP content helpers ───────────────────────────────────────────────────────

def extract_text_content(content_list: Any) -> str:
    """Flatten an MCP content list to a single string."""
    if not content_list:
        return ""
    parts: List[str] = []
    for c in content_list:
        text = getattr(c, "text", None)
        parts.append(text if isinstance(text, str) else str(c))
    return "\n".join(parts)


def load_json_from_content(content_list: Any) -> Any:
    """Decode JSON from an MCP content list; None on failure."""
    raw = extract_text_content(content_list).strip()
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


# ── Article helpers ───────────────────────────────────────────────────────────

def safe_domain_from_url(url: str) -> str:
    try:
        netloc = urlparse(url).netloc.strip()
        return netloc or "unknown"
    except Exception:
        return "unknown"


def article_domain_lang(a: Article) -> Tuple[str, str]:
    raw = a.raw or {}
    domain = str(
        raw.get("domain")
        or raw.get("sourceDomain")
        or safe_domain_from_url(a.link)
        or "unknown"
    )
    lang = str(
        raw.get("language")
        or raw.get("lang")
        or raw.get("sourceLang")
        or "unknown"
    )
    return domain, lang


def best_available_content(a: Article) -> str:
    """Best-effort article content without crawling."""
    raw = a.raw or {}
    for key in ("content", "content_text", "fulltext", "description", "summary", "snippet"):
        val = raw.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return (a.summary or "").strip()


# ── String helpers ────────────────────────────────────────────────────────────

def truncate(s: str, max_len: int) -> str:
    s = (s or "").strip()
    return s if len(s) <= max_len else s[: max_len - 3] + "..."


def safe_llm_text(resp: Any) -> str:
    try:
        msg = (resp or {}).get("message") or {}
        content = msg.get("content") or ""
        return str(content).strip()
    except Exception:
        return ""


def extract_json_object(text: str) -> Optional[Dict[str, Any]]:
    if not text:
        return None
    m = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None
