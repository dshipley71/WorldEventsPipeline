"""
tests/test_models_and_utils.py

Unit tests for data models and utility helpers.
Run with:  pytest tests/ -v
"""

import sys
from datetime import datetime, timezone
from pathlib import Path

# Make the package importable without installation
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from world_events.config import PipelineParameters
from world_events.models import Article, PipelineState, Spike, TimelinePoint
from world_events.utils import (
    article_domain_lang,
    best_available_content,
    extract_json_object,
    parse_iso_datetime,
    published_str,
    safe_domain_from_url,
    truncate,
)


# ── PipelineParameters ─────────────────────────────────────────────────────────

class TestPipelineParameters:
    def test_defaults(self):
        p = PipelineParameters()
        assert p.timespan == "14d"
        assert p.spike_threshold == 2.0
        assert p.llm_enabled is True
        assert p.cross_source_content_mode == "llm_summary"

    def test_override(self):
        p = PipelineParameters(timespan="7d", gdelt_limit=50)
        assert p.timespan == "7d"
        assert p.gdelt_limit == 50


# ── PipelineState ──────────────────────────────────────────────────────────────

class TestPipelineState:
    def test_defaults(self):
        state = PipelineState(query="test query")
        assert state.query == "test query"
        assert state.gdelt_articles == []
        assert state.rss_articles == []
        assert state.spikes == []
        assert state.timeline == []
        assert state.output_json is None

    def test_spike_storage(self):
        state = PipelineState(query="q")
        state.spikes = [Spike(date=datetime(2025, 1, 1), raw_volume=100.0, zscore=3.5)]
        assert len(state.spikes) == 1
        assert state.spikes[0].zscore == 3.5


# ── parse_iso_datetime ─────────────────────────────────────────────────────────

class TestParseIsoDatetime:
    def test_z_suffix(self):
        dt = parse_iso_datetime("2025-01-15T12:00:00Z")
        assert dt is not None
        assert dt.year == 2025
        assert dt.month == 1
        assert dt.day == 15
        assert dt.tzinfo is None  # normalised to naive UTC

    def test_plus_offset(self):
        dt = parse_iso_datetime("2025-03-01T08:00:00+05:30")
        assert dt is not None
        assert dt.tzinfo is None

    def test_invalid(self):
        assert parse_iso_datetime("not-a-date") is None

    def test_empty(self):
        assert parse_iso_datetime("") is None


# ── truncate ───────────────────────────────────────────────────────────────────

class TestTruncate:
    def test_short(self):
        assert truncate("hello", 10) == "hello"

    def test_exact(self):
        assert truncate("hello", 5) == "hello"

    def test_long(self):
        result = truncate("hello world", 8)
        assert len(result) == 8
        assert result.endswith("...")

    def test_empty(self):
        assert truncate("", 10) == ""


# ── safe_domain_from_url ──────────────────────────────────────────────────────

class TestSafeDomain:
    def test_standard(self):
        assert safe_domain_from_url("https://www.bbc.com/news/article") == "www.bbc.com"

    def test_no_scheme(self):
        # urlparse without scheme may return empty netloc; should not raise
        result = safe_domain_from_url("bbc.com/news")
        assert isinstance(result, str)

    def test_empty(self):
        assert safe_domain_from_url("") == "unknown"


# ── article_domain_lang ────────────────────────────────────────────────────────

class TestArticleDomainLang:
    def test_from_raw(self):
        a = Article(
            source="gdelt",
            title="Test",
            link="https://example.com/article",
            raw={"domain": "example.com", "language": "English"},
        )
        domain, lang = article_domain_lang(a)
        assert domain == "example.com"
        assert lang == "English"

    def test_fallback_to_url(self):
        a = Article(
            source="gdelt",
            title="Test",
            link="https://reuters.com/article",
        )
        domain, lang = article_domain_lang(a)
        assert "reuters.com" in domain
        assert lang == "unknown"


# ── best_available_content ────────────────────────────────────────────────────

class TestBestAvailableContent:
    def test_prefers_content(self):
        a = Article(
            source="rss",
            title="T",
            link="",
            summary="summary text",
            raw={"content": "full content here"},
        )
        assert best_available_content(a) == "full content here"

    def test_falls_back_to_summary(self):
        a = Article(source="rss", title="T", link="", summary="my summary")
        assert best_available_content(a) == "my summary"

    def test_empty(self):
        a = Article(source="rss", title="T", link="")
        assert best_available_content(a) == ""


# ── extract_json_object ────────────────────────────────────────────────────────

class TestExtractJsonObject:
    def test_plain_json(self):
        obj = extract_json_object('{"key": "value"}')
        assert obj == {"key": "value"}

    def test_embedded(self):
        obj = extract_json_object('Some text {"review": "ok", "sources_used": []} more text')
        assert obj is not None
        assert obj["review"] == "ok"

    def test_invalid(self):
        assert extract_json_object("no json here") is None

    def test_empty(self):
        assert extract_json_object("") is None


# ── published_str ─────────────────────────────────────────────────────────────

class TestPublishedStr:
    def test_with_date(self):
        a = Article(
            source="gdelt",
            title="T",
            link="",
            published=datetime(2025, 6, 1, 12, 0, 0),
        )
        result = published_str(a)
        assert "2025-06-01" in result

    def test_without_date(self):
        a = Article(source="gdelt", title="T", link="")
        assert published_str(a) == "unknown"
