"""Cross-encoder reranker for Brain retrieval.

After RRF fusion produces an initial ranking, a cross-encoder scores each
(query, chunk) pair for relevance. This is significantly more accurate than
bi-encoder (embedding) similarity because the cross-encoder sees both texts
simultaneously.

The reranker is optional. If sentence-transformers is not installed, retrieval
falls back to RRF-only ordering.

Recommended model for production:
  cross-encoder/ms-marco-MiniLM-L-6-v2  — fast, good quality, ~22M params
  cross-encoder/ms-marco-MiniLM-L-12-v2 — slightly better, ~33M params

For enterprise deployments with GPU, consider:
  cross-encoder/ms-marco-electra-base    — best quality, slower
"""
from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)

# Lazy-loaded model cache
_model: Any | None = None
_model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"


def _get_model() -> Any | None:
    """Lazy-load the cross-encoder model. Returns None if dependencies missing."""
    global _model
    if _model is not None:
        return _model
    try:
        from sentence_transformers import CrossEncoder
        _model = CrossEncoder(_model_name)
        log.info("loaded cross-encoder model: %s", _model_name)
        return _model
    except ImportError:
        log.warning(
            "sentence-transformers not installed; cross-encoder reranking disabled. "
            "Install with: pip install sentence-transformers"
        )
        return None
    except Exception as e:
        log.exception("failed to load cross-encoder model: %s", e)
        return None


def rerank(query: str, passages: list[str], top_k: int | None = None) -> list[tuple[int, float]]:
    """Rerank passages by relevance to query.

    Returns a list of (original_index, score) sorted by score descending.
    If the model is unavailable, returns identity ordering with uniform scores.
    """
    model = _get_model()
    if model is None or not passages:
        # Fallback: preserve original order with dummy scores
        return [(i, 0.0) for i in range(len(passages))]

    pairs = [(query, p) for p in passages]
    scores = model.predict(pairs, show_progress_bar=False)
    indexed = list(enumerate(scores))
    indexed.sort(key=lambda x: x[1], reverse=True)

    if top_k:
        indexed = indexed[:top_k]

    return indexed
