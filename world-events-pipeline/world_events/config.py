"""
world_events/config.py

PipelineParameters — all tunable knobs for the World-Events pipeline.
Edit this file (or override at runtime) to change behaviour without
touching agent logic.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class PipelineParameters:
    # ── GDELT query settings ──────────────────────────────────────────────
    timespan: str = "14d"
    gdelt_limit: int = 100           # max articles per artlist call
    use_mcp_for_gdelt: bool = True   # False → direct GDELT HTTP only

    # ── GDELT rate-limiting / retries ─────────────────────────────────────
    gdelt_min_interval_seconds: float = 6.0
    gdelt_max_retries: int = 3

    # ── Spike detection ───────────────────────────────────────────────────
    spike_threshold: float = 2.0     # z-score threshold
    window_days: int = 1             # article correlation window around spike

    # ── RSS feed settings ─────────────────────────────────────────────────
    rss_limit: int = 100
    category: Optional[str] = "geopolitics"

    # ── MiniLM semantic RSS ranking ───────────────────────────────────────
    semantic_rss_enabled: bool = True
    semantic_min_score: float = 0.35
    semantic_top_k: int = 20
    semantic_debug_top_n: Optional[int] = None  # None → no debug output

    # ── MiniLM GDELT re-rank (GDELTReRankAgent) ───────────────────────────
    gdelt_rerank_enabled: bool = True
    gdelt_rerank_top_k: int = 50
    gdelt_rerank_debug_top_n: int = 0

    # ── LLM (Ollama Cloud) ────────────────────────────────────────────────
    llm_enabled: bool = True
    llm_host: str = "https://ollama.com"
    llm_model: str = "gemma3:27b"
    # Must cover MAX_GDELT_SOURCES (16) + buffer to avoid summary/selection gaps
    llm_max_articles: int = 24
    # Per-call timeout; increase for slow hosts or very large models
    llm_timeout_seconds: int = 120

    # ── Cross-source review ───────────────────────────────────────────────
    # Minimum LLM summary length before falling back to raw snippet
    min_llm_summary_chars: int = 80
    # "llm_summary" | "content"
    cross_source_content_mode: str = "llm_summary"

    # ── MCP enrichment (MCPEnrichmentAgent) ──────────────────────────────
    mcp_enrichment_enabled: bool = True
    # Max chars of GDELT article text sent to NER tool
    mcp_enrichment_entity_text_limit: int = 3_000
