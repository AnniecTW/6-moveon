"""Sentence-embedding similarity for local AI search candidate retrieval.

Keyword matching misses intent phrasing such as "something to sit on" (no listing
says "sit"). Embeddings rank sofas and chairs first for that query, so the local
model sees them. Scores are cosine similarities in [-1, 1]; they rank well but are
only a loose relevance signal on their own.
"""

import logging
from threading import Lock

from .pricing.semantic import sentence_encoder

logger = logging.getLogger(__name__)
MAX_CACHED_LISTING_VECTORS = 5000
_vector_cache = {}
_vector_cache_lock = Lock()


def listing_similarities(query, texts):
    """Return the query's similarity to each text, or None if embeddings fail.

    Listing vectors are cached by text, so an edited listing is simply
    re-encoded. None tells the caller to fall back to keyword candidates.
    """
    if not texts:
        return []
    try:
        encoder = sentence_encoder()
        with _vector_cache_lock:
            vectors = {text: _vector_cache.get(text) for text in texts}
        missing = [text for text, vector in vectors.items() if vector is None]
        if missing:
            encoded = encoder.encode(missing, normalize_embeddings=True)
            vectors.update(zip(missing, encoded))
            with _vector_cache_lock:
                if len(_vector_cache) + len(missing) > MAX_CACHED_LISTING_VECTORS:
                    _vector_cache.clear()
                _vector_cache.update(zip(missing, encoded))
        query_vector = encoder.encode([query], normalize_embeddings=True)[0]
        return [float(vectors[text] @ query_vector) for text in texts]
    except Exception:
        logger.exception("Listing embedding search is unavailable; using keyword candidates.")
        return None
