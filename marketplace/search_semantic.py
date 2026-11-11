"""Semantic retrieval over listings already made eligible by the browse filters."""

import logging
from functools import lru_cache
from time import perf_counter

from .pricing.semantic import _model

logger = logging.getLogger(__name__)

MAX_RERANK_CANDIDATES = 8
# Retrieval favors recall because Llama checks the shortlist. A stricter score
# is required when embeddings alone must supply the displayed results.
MIN_SEARCH_SIMILARITY = 0.30
MIN_FALLBACK_SIMILARITY = 0.40


class SemanticSearchError(RuntimeError):
    """The embedding model could not rank eligible listings."""


def listing_document(candidate):
    """Keep retrieval text focused on the fields that describe the item."""
    return ". ".join(
        str(candidate.get(field) or "").strip()[:limit]
        for field, limit in (("title", 200), ("category", 200), ("description", 500))
        if candidate.get(field)
    )


@lru_cache(maxsize=2)
def _catalog_vectors(documents):
    """Reuse vectors until the eligible listing content or filters change."""
    return _model().encode(list(documents), normalize_embeddings=True)


def retrieve(query, candidates, *, model=None, limit=MAX_RERANK_CANDIDATES):
    """Return relevant candidates and their cosine scores, highest first.

    Normalized vectors make the dot product cosine similarity. This function
    never widens the caller's structured-filtered candidate set.
    """
    if not candidates:
        return []
    started = perf_counter()
    try:
        encoder = model or _model()
        documents = tuple(listing_document(item) for item in candidates)
        query_vector = encoder.encode([query[:200]], normalize_embeddings=True)[0]
        vectors = (encoder.encode(list(documents), normalize_embeddings=True)
                   if model is not None else _catalog_vectors(documents))
        scored = []
        for candidate, vector in zip(candidates, vectors):
            similarity = float(sum(float(a) * float(b) for a, b in zip(query_vector, vector)))
            if similarity >= MIN_SEARCH_SIMILARITY:
                scored.append((candidate, similarity))
    except Exception as error:
        logger.exception("Semantic listing retrieval failed.")
        raise SemanticSearchError("Semantic listing retrieval is unavailable.") from error
    scored.sort(key=lambda row: (-row[1], row[0]["pk"]))
    logger.info("Semantic listing retrieval scored %s candidates in %.2fs; kept %s",
                len(candidates), perf_counter() - started, len(scored))
    return scored[:limit]
