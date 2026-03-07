"""
world_events/models.py

Core data models shared across agents.  No heavy imports here — only stdlib.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from world_events.config import PipelineParameters

if TYPE_CHECKING:
    # Avoid circular import; rate_limiter imports nothing from models.
    from world_events.rate_limiter import AsyncRateLimiter


@dataclass
class TimelinePoint:
    date: datetime
    volume_intensity: Optional[float] = None
    raw_volume: Optional[float] = None
    tone: Optional[float] = None


@dataclass
class Spike:
    date: datetime
    raw_volume: float
    zscore: float


@dataclass
class Article:
    source: str                           # "gdelt" | "rss"
    title: str
    link: str
    published: Optional[datetime] = None
    summary: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PipelineState:
    query: str
    params: PipelineParameters = field(default_factory=PipelineParameters)

    # ── Timeline / spike data ─────────────────────────────────────────────
    timeline: List[TimelinePoint] = field(default_factory=list)
    spikes: List[Spike] = field(default_factory=list)

    # ── Article collections ───────────────────────────────────────────────
    gdelt_articles: List[Article] = field(default_factory=list)
    rss_articles: List[Article] = field(default_factory=list)

    # ── LLM outputs ───────────────────────────────────────────────────────
    analysis_summary: Optional[str] = None
    risk_assessment: Optional[str] = None
    cross_source_review: Optional[str] = None
    cross_source_review_sources: List[Dict[str, Any]] = field(default_factory=list)

    # ── Plot artifacts ────────────────────────────────────────────────────
    plot_png_path: Optional[str] = None
    plot_png_base64: Optional[str] = None
    plot_data: Dict[str, Any] = field(default_factory=dict)

    # ── MCP enrichment (MCPEnrichmentAgent) ──────────────────────────────
    mcp_keyword_spikes: List[Dict[str, Any]] = field(default_factory=list)
    mcp_news_clusters: List[Dict[str, Any]] = field(default_factory=list)
    mcp_entities: Dict[str, Any] = field(default_factory=dict)

    # ── Runtime internals ─────────────────────────────────────────────────
    # Typed as Any to avoid a circular import with rate_limiter at module load
    gdelt_limiter: Optional[Any] = None
    # Set by StructuredOutputAgent; printed by orchestrator after stdout restore
    output_json: Optional[str] = None
