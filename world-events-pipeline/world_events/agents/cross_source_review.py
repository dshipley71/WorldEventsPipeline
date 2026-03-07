"""
world_events/agents/cross_source_review.py

CrossSourceReviewAgent — synthesises GDELT + RSS sources into a cited,
structured intelligence review using an Ollama LLM.

Key design decisions:
  - Static source caps (MAX_GDELT_SOURCES=16, MAX_RSS_SOURCES=8) — not
    inflated during spike conditions to avoid context overflow.
  - Conservative token estimator (3 chars/token) for multilingual content.
  - 80 K TOKEN_BUDGET with headroom for model output.
  - 2-pass narrowing via a lightweight title manifest when the first prompt
    exceeds context.
  - Prefers ``llm_summary`` content; falls back to raw snippet.
  - Injects MCPEnrichmentAgent context block for statistical grounding.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

from world_events.agents.base import BaseAgent
from world_events.llm import get_ollama_client
from world_events.logging_utils import log
from world_events.utils import (
    article_domain_lang,
    best_available_content,
    extract_json_object,
    published_str,
    safe_llm_text,
    truncate,
)

if TYPE_CHECKING:
    from mcp import ClientSession
    from world_events.models import Article, PipelineState, Spike

# ── Layout constants ───────────────────────────────────────────────────────────
MAX_GDELT_SOURCES = 16
MAX_RSS_SOURCES = 8
TOTAL_SOURCES_HARD_CAP = 24
PER_SOURCE_CONTENT_CHARS = 420
PER_SOURCE_TITLE_CHARS = 180
TOKEN_BUDGET = 80_000  # reserved headroom for model output + prompt overhead


def _estimate_tokens(text: str) -> int:
    """3 chars/token — more accurate than 4 for multilingual + URL-heavy text."""
    return max(1, len(text) // 3)


def _within_any_window(
    pub: Optional[Any], windows: List[Tuple[Any, Any]]
) -> bool:
    if pub is None:
        return False
    return any(ws <= pub <= we for ws, we in windows)


def _build_windows(state: "PipelineState") -> List[Tuple[Any, Any]]:
    return [
        (
            s.date - timedelta(days=state.params.window_days),
            s.date + timedelta(days=state.params.window_days),
        )
        for s in state.spikes
    ]


def _content_for_review(a: "Article", state: "PipelineState") -> str:
    mode = (state.params.cross_source_content_mode or "llm_summary").strip().lower()
    if mode == "content":
        return best_available_content(a)
    llm_sum = str((a.raw or {}).get("llm_summary") or "").strip()
    if len(llm_sum) >= state.params.min_llm_summary_chars:
        return llm_sum
    return best_available_content(a)


def _build_enrichment_block(state: "PipelineState") -> str:
    lines: List[str] = []

    if state.mcp_keyword_spikes:
        kw_parts: List[str] = []
        for s in state.mcp_keyword_spikes[:12]:
            kw = str(s.get("keyword") or "")
            z = s.get("z_score")
            ratio = s.get("ratio")
            if z is not None:
                kw_parts.append(f"{kw}(z={z:.1f})")
            elif ratio is not None:
                kw_parts.append(f"{kw}(ratio={ratio:.1f}x)")
            else:
                kw_parts.append(kw)
        lines.append(
            "KEYWORD SPIKES (statistically above baseline): " + ", ".join(kw_parts)
        )

    if state.mcp_entities:
        entity_parts: List[str] = []
        countries = state.mcp_entities.get("countries") or []
        leaders = state.mcp_entities.get("leaders") or []
        orgs = state.mcp_entities.get("organizations") or []
        cves = state.mcp_entities.get("cves") or []
        apts = state.mcp_entities.get("apt_groups") or []
        if countries:
            entity_parts.append(
                "Countries: " + ", ".join(c.get("name") or c.get("iso3") or "" for c in countries[:8])
            )
        if leaders:
            entity_parts.append(
                "Leaders: " + ", ".join(l.get("name") or "" for l in leaders[:6])
            )
        if orgs:
            entity_parts.append(
                "Organizations: " + ", ".join(o.get("name") or "" for o in orgs[:6])
            )
        if cves:
            entity_parts.append("CVEs: " + ", ".join(cves[:5]))
        if apts:
            entity_parts.append("APTs: " + ", ".join(apts[:4]))
        if entity_parts:
            lines.append("ENTITIES EXTRACTED FROM ARTICLES: " + " | ".join(entity_parts))

    if state.mcp_news_clusters:
        cluster_parts: List[str] = []
        for c in state.mcp_news_clusters[:4]:
            size = c.get("size", "?")
            kws = c.get("keywords") or []
            headline = truncate(c.get("headline") or "", 80)
            cluster_parts.append(
                f"[{size} articles, kw={kws[:4]}, lead={headline!r}]"
            )
        lines.append(
            "NEWS TOPIC CLUSTERS (from RSS, by Jaccard similarity): "
            + "; ".join(cluster_parts)
        )

    if not lines:
        return ""
    return (
        "\nENRICHMENT CONTEXT (from MCP statistical analysis — use as supporting evidence):\n"
        + "\n".join(lines)
        + "\n"
    )


class CrossSourceReviewAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__("CrossSourceReviewAgent")

    async def run(self, session: "ClientSession", state: "PipelineState") -> None:  # noqa: ARG002
        client_model = get_ollama_client(state)
        if client_model is None:
            log("CrossSourceReviewAgent: LLM unavailable — skipping")
            state.cross_source_review = None
            state.cross_source_review_sources = []
            return

        client, model = client_model

        gdelt_all = state.gdelt_articles[:]
        rss_all = state.rss_articles[:]

        if not gdelt_all and not rss_all:
            state.cross_source_review = "No articles available from GDELT or RSS to review."
            state.cross_source_review_sources = []
            log("CrossSourceReviewAgent: no articles available")
            return

        windows = _build_windows(state)

        # ── Source selection ──────────────────────────────────────────────────
        if state.spikes and windows:
            gdelt_sel = [a for a in gdelt_all if _within_any_window(a.published, windows)]
            rss_sel = [a for a in rss_all if _within_any_window(a.published, windows)]
            if len(gdelt_sel) < 6:
                gdelt_sel += [a for a in gdelt_all if a not in gdelt_sel][
                    : max(0, MAX_GDELT_SOURCES - len(gdelt_sel))
                ]
            if len(rss_sel) < 3:
                rss_sel += [a for a in rss_all if a not in rss_sel][
                    : max(0, MAX_RSS_SOURCES - len(rss_sel))
                ]
        else:
            gdelt_sel = gdelt_all[:MAX_GDELT_SOURCES]
            rss_sel = rss_all[:MAX_RSS_SOURCES]

        combined = (gdelt_sel + rss_sel)[:TOTAL_SOURCES_HARD_CAP]

        # ── Build source cards ────────────────────────────────────────────────
        sources: List[Dict[str, Any]] = []
        cards: List[str] = []
        for sid, a in enumerate(combined, start=1):
            domain, lang = article_domain_lang(a)
            content = truncate(_content_for_review(a, state), PER_SOURCE_CONTENT_CHARS)
            title = truncate(a.title, PER_SOURCE_TITLE_CHARS)
            src_id = f"S{sid:03d}"
            sources.append(
                {
                    "source_id": src_id,
                    "domain": domain,
                    "title": a.title,
                    "published": published_str(a),
                    "link": a.link,
                    "page_number": 1,
                }
            )
            cards.append(
                f"{src_id} | {a.source.upper()} | {domain} | lang={lang} | "
                f"published={published_str(a)}\n"
                f"TITLE: {title}\n"
                f"CONTENT: {content}\n"
                f"LINK: {a.link}\n"
            )

        spike_block = (
            "None"
            if not state.spikes
            else "\n".join(
                f"{s.date.strftime('%Y-%m-%d')} raw={s.raw_volume:.0f} z={s.zscore:.2f}"
                for s in state.spikes[:10]
            )
        )

        instructions = (
            "You are conducting a cross-source review for an intelligence workflow.\n"
            "STRICT RULES:\n"
            "1) Use ONLY the SOURCE CARDS and ENRICHMENT CONTEXT below. Do NOT use external knowledge.\n"
            "2) Do NOT speculate. If the sources do not explain causes, say so explicitly.\n"
            "3) Every key claim must cite at least one source_id in brackets, e.g., [S001].\n"
            "4) If spikes are None OR the cards do not define trends, provide a detailed summary\n"
            "   of the sources and explicitly state that no spikes and/or trends exist.\n\n"
            'OUTPUT FORMAT:\nReturn JSON only: {"review": "...", "sources_used": ["S001", ...]}\n'
        )

        header = (
            f"QUERY: {state.query}\n"
            f"TIMESPAN: {state.params.timespan}\n"
            f"SPIKES (if any):\n{spike_block}\n"
            f"SOURCE_COUNT: {len(cards)}\n"
            f"CROSS_SOURCE_CONTENT_MODE: {state.params.cross_source_content_mode}\n"
            f"{_build_enrichment_block(state)}"
        )

        base_text = instructions + "\n" + header + "\nSOURCE CARDS:\n"

        # ── Token-budget gate ─────────────────────────────────────────────────
        used_tokens = _estimate_tokens(base_text)
        kept_cards: List[str] = []
        kept_sources: List[Dict[str, Any]] = []
        for i, card in enumerate(cards):
            t = _estimate_tokens(card)
            if used_tokens + t > TOKEN_BUDGET:
                log(
                    f"CrossSourceReviewAgent: token budget reached at card "
                    f"{i + 1}/{len(cards)} est_tokens={used_tokens}"
                )
                break
            used_tokens += t
            kept_cards.append(card)
            kept_sources.append(sources[i])

        prompt = base_text + "\n---\n".join(kept_cards)
        log(
            f"CrossSourceReviewAgent: calling LLM model={model} "
            f"sources_in={len(cards)} sources_sent={len(kept_cards)} "
            f"est_tokens={used_tokens}"
        )

        # ── First-pass LLM call ───────────────────────────────────────────────
        text: str = ""
        try:
            resp = await asyncio.wait_for(
                asyncio.to_thread(
                    client.chat,
                    model,
                    messages=[{"role": "user", "content": prompt}],
                    options={"num_predict": 1500},
                    stream=False,
                ),
                timeout=state.params.llm_timeout_seconds,
            )
            text = safe_llm_text(resp)

        except asyncio.TimeoutError:
            log(
                f"CrossSourceReviewAgent: LLM timed out after "
                f"{state.params.llm_timeout_seconds}s"
            )
            self._store_failed(state, kept_sources, "(Cross-source review failed: LLM timeout)")
            return

        except Exception as exc:
            msg = str(exc).lower()
            if "prompt too long" not in msg and "context length" not in msg:
                log(f"CrossSourceReviewAgent: LLM error: {exc}")
                self._store_failed(state, kept_sources, f"(Cross-source review failed: {exc})")
                return

            # ── 2-pass narrowing ──────────────────────────────────────────────
            log("CrossSourceReviewAgent: prompt too long → 2-pass narrowing")
            kept_cards, kept_sources, text = await self._two_pass_narrow(
                client, model, state, kept_cards, kept_sources, spike_block, base_text
            )
            if text is None:
                return  # _store_failed already called

        # ── Parse and store response ──────────────────────────────────────────
        self._parse_and_store(state, text, kept_sources)

    # ── helpers ───────────────────────────────────────────────────────────────

    def _store_failed(
        self,
        state: "PipelineState",
        sources: List[Dict[str, Any]],
        msg: str,
    ) -> None:
        state.cross_source_review = msg
        state.cross_source_review_sources = [
            {k: s[k] for k in ["domain", "title", "published", "link", "page_number"]}
            for s in sources
        ]

    def _parse_and_store(
        self,
        state: "PipelineState",
        text: str,
        kept_sources: List[Dict[str, Any]],
    ) -> None:
        obj = extract_json_object(text)
        if not isinstance(obj, dict) or "review" not in obj:
            state.cross_source_review = text.strip() or "(empty cross-source review)"
            state.cross_source_review_sources = [
                {k: s[k] for k in ["domain", "title", "published", "link", "page_number"]}
                for s in kept_sources
            ]
            log("CrossSourceReviewAgent: non-JSON response — stored raw review")
            return

        review = str(obj.get("review") or "").strip()
        used_ids_raw = obj.get("sources_used") or []
        used_set = {str(x).strip() for x in used_ids_raw if str(x).strip()}
        used_sources = [
            {k: s[k] for k in ["domain", "title", "published", "link", "page_number"]}
            for s in kept_sources
            if s.get("source_id") in used_set
        ]
        if not used_sources:
            used_sources = [
                {k: s[k] for k in ["domain", "title", "published", "link", "page_number"]}
                for s in kept_sources
            ]
        state.cross_source_review = review or "(empty cross-source review)"
        state.cross_source_review_sources = used_sources
        log(
            f"CrossSourceReviewAgent: stored review "
            f"sources_used={len(state.cross_source_review_sources)}"
        )

    async def _two_pass_narrow(
        self,
        client: Any,
        model: str,
        state: "PipelineState",
        kept_cards: List[str],
        kept_sources: List[Dict[str, Any]],
        spike_block: str,
        base_text: str,
    ) -> Tuple[List[str], List[Dict[str, Any]], Optional[str]]:
        """
        Lightweight title manifest → selector call → narrowed full prompt.
        Returns (narrowed_cards, narrowed_sources, review_text) or
        (kept_cards, kept_sources, None) on failure after storing error state.
        """
        selector_instructions = (
            "Select the minimal set of source_id values needed to answer the query.\n"
            "Rules:\n"
            "- Use ONLY the provided source manifest.\n"
            "- Prefer sources directly relevant to the query and spike dates.\n"
            "- If no spikes/trends exist, select sources that best summarise coverage.\n"
            "- Return at most 12 source IDs.\n"
            'Return JSON only: {"sources_used": ["S001", ...]}\n'
        )
        manifest_lines = [
            f"{s['source_id']} | {s['domain']} | {s['published'][:10]} | {s['title'][:120]}"
            for s in kept_sources
        ]
        selector_prompt = (
            selector_instructions
            + f"\nQUERY: {state.query}\nSPIKES:\n{spike_block}\n\n"
            + f"SOURCE MANIFEST ({len(kept_sources)} sources — titles/dates only):\n"
            + "\n".join(manifest_lines)
        )

        used_set: set = set()
        try:
            sel_resp = await asyncio.wait_for(
                asyncio.to_thread(
                    client.chat,
                    model,
                    messages=[{"role": "user", "content": selector_prompt}],
                    options={"num_predict": 200},
                    stream=False,
                ),
                timeout=state.params.llm_timeout_seconds,
            )
            sel_text = safe_llm_text(sel_resp)
            sel_obj = extract_json_object(sel_text) or {}
            used_ids = sel_obj.get("sources_used") or []
            if isinstance(used_ids, list):
                used_set = {str(x).strip() for x in used_ids if str(x).strip()}
        except asyncio.TimeoutError:
            log("CrossSourceReviewAgent: selector timed out — falling back to first 10")
        except Exception as exc2:
            log(f"CrossSourceReviewAgent: selector failed: {exc2}")

        if not used_set:
            used_set = {s["source_id"] for s in kept_sources[:10]}

        narrowed_cards = [
            card for src, card in zip(kept_sources, kept_cards)
            if src["source_id"] in used_set
        ][:14]
        narrowed_sources = [s for s in kept_sources if s["source_id"] in used_set][:14]
        narrowed_prompt = base_text + "\n---\n".join(narrowed_cards)

        try:
            resp2 = await asyncio.wait_for(
                asyncio.to_thread(
                    client.chat,
                    model,
                    messages=[{"role": "user", "content": narrowed_prompt}],
                    options={"num_predict": 1500},
                    stream=False,
                ),
                timeout=state.params.llm_timeout_seconds,
            )
            text = safe_llm_text(resp2)
            return narrowed_cards, narrowed_sources, text
        except asyncio.TimeoutError:
            log(
                f"CrossSourceReviewAgent: narrowed prompt timed out after "
                f"{state.params.llm_timeout_seconds}s"
            )
            self._store_failed(
                state, narrowed_sources,
                "(Cross-source review failed: timeout on narrowed prompt)"
            )
        except Exception as exc3:
            log(f"CrossSourceReviewAgent: narrowed prompt still failed: {exc3}")
            self._store_failed(
                state, narrowed_sources,
                f"(Cross-source review failed after narrowing: {exc3})"
            )
        return kept_cards, kept_sources, None
