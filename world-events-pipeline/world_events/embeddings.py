"""
world_events/embeddings.py

MiniLM embedding model (lazy-loaded) and semantic ranking helpers.

Requires:  pip install sentence-transformers numpy
"""

from __future__ import annotations

from typing import TYPE_CHECKING, List, Optional

from world_events.logging_utils import log

if TYPE_CHECKING:
    from world_events.models import Article, PipelineState

# Module-level cache so the model is only loaded once per process
_EMBED_MODEL = None


def get_embedding_model():
    """
    Load ``all-MiniLM-L6-v2`` on first call (downloads weights automatically).
    Subsequent calls return the cached instance.
    """
    global _EMBED_MODEL
    if _EMBED_MODEL is None:
        try:
            from sentence_transformers import SentenceTransformer  # type: ignore
        except ImportError as e:
            raise RuntimeError(
                "Missing dependency: sentence-transformers. "
                "Install with: pip install sentence-transformers"
            ) from e

        model_name = "sentence-transformers/all-MiniLM-L6-v2"
        log(f"Loading MiniLM model ({model_name})… (first run will download weights)")
        _EMBED_MODEL = SentenceTransformer(model_name)
        log("MiniLM model loaded.")
    return _EMBED_MODEL


# ── Semantic RSS ranking ───────────────────────────────────────────────────────

def semantic_rank_rss(
    state: "PipelineState",
    rss_articles: List["Article"],
    gdelt_articles: List["Article"],
) -> List["Article"]:
    """
    Rank *rss_articles* by cosine similarity to:
      - the user query                  (weight 0.65)
      - a GDELT context document        (weight 0.35)

    Returns at most ``params.semantic_top_k`` articles above
    ``params.semantic_min_score``.
    """
    if not rss_articles:
        return []

    try:
        import numpy as np  # type: ignore
    except ImportError as e:
        raise RuntimeError("Missing dependency: numpy. Install with: pip install numpy") from e

    model = get_embedding_model()

    def doc(a: "Article") -> str:
        return f"{a.title} {a.summary or ''}".strip()

    rss_docs = [doc(a) for a in rss_articles]
    gdelt_docs = [doc(a) for a in gdelt_articles[:50]] if gdelt_articles else []
    gdelt_context = " ".join(gdelt_docs).strip()

    log(f"Embedding RSS articles: n={len(rss_docs)}")
    rss_emb = model.encode(rss_docs, normalize_embeddings=True)

    log("Embedding query…")
    q_emb = model.encode([state.query], normalize_embeddings=True)[0]

    g_emb: Optional[object] = None
    if gdelt_context:
        log("Embedding GDELT context…")
        g_emb = model.encode([gdelt_context], normalize_embeddings=True)[0]

    sim_q = rss_emb @ q_emb
    sim_g = (rss_emb @ g_emb) if g_emb is not None else np.zeros_like(sim_q)
    scores = (0.65 * sim_q) + (0.35 * sim_g)
    ranked_idx = np.argsort(-scores)

    if state.params.semantic_debug_top_n:
        log(f"MiniLM similarity debug (top {state.params.semantic_debug_top_n}):")
        for idx in ranked_idx[: state.params.semantic_debug_top_n]:
            a = rss_articles[int(idx)]
            log(
                f"  score={float(scores[idx]):.3f} "
                f"q_sim={float(sim_q[idx]):.3f} "
                f"g_sim={float(sim_g[idx]):.3f} "
                f"title={a.title[:140]}"
            )

    kept: List["Article"] = []
    for idx in ranked_idx:
        if float(scores[idx]) < state.params.semantic_min_score:
            break
        kept.append(rss_articles[int(idx)])
        if len(kept) >= state.params.semantic_top_k:
            break

    log(
        f"MiniLM selected RSS articles: {len(kept)} "
        f"(min_score={state.params.semantic_min_score} "
        f"top_k={state.params.semantic_top_k})"
    )
    for a in kept[:10]:
        log(f"RSS_SELECTED: {a.title} | {a.link}")

    return kept


# ── Semantic GDELT re-ranking ─────────────────────────────────────────────────

def semantic_rerank_gdelt(
    state: "PipelineState",
    articles: List["Article"],
) -> List["Article"]:
    """
    Re-rank *articles* (GDELT) by cosine similarity to the user query.
    Returns at most ``params.gdelt_rerank_top_k`` articles.
    """
    if not articles:
        return articles

    try:
        import numpy as np  # type: ignore
    except ImportError as e:
        raise RuntimeError("Missing dependency: numpy. Install with: pip install numpy") from e

    model = get_embedding_model()

    def doc(a: "Article") -> str:
        return f"{a.title} {a.summary or ''}".strip()

    docs = [doc(a) for a in articles]
    log(f"GDELTReRank: embedding {len(docs)} articles")

    art_emb = model.encode(docs, normalize_embeddings=True)
    q_emb = model.encode([state.query], normalize_embeddings=True)[0]
    scores = art_emb @ q_emb
    ranked_idx = np.argsort(-scores)

    if state.params.gdelt_rerank_debug_top_n > 0:
        log(f"GDELTReRank debug top {state.params.gdelt_rerank_debug_top_n}:")
        for idx in ranked_idx[: state.params.gdelt_rerank_debug_top_n]:
            a = articles[int(idx)]
            log(f"  score={float(scores[idx]):.3f} title={a.title[:120]}")

    top_k = min(state.params.gdelt_rerank_top_k, len(articles))
    return [articles[int(i)] for i in ranked_idx[:top_k]]
