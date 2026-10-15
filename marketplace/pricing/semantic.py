"""Semantic item-type discovery. Pricing remains in ``initial.recommend``."""

from collections import defaultdict
from functools import lru_cache
from threading import Lock

from .initial import MIN_TYPE_ONLY, Observation, SOURCE_PATH, load_source, normalize

MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
MAX_CANDIDATES = 5
# Discovery only; this score is not a price-confidence probability.
MIN_SIMILARITY = 0.40


_model_instance = None
_model_lock = Lock()


def _model():
    """Load once even when warmup and a request arrive together."""
    global _model_instance
    if _model_instance is None:
        with _model_lock:
            if _model_instance is None:
                from sentence_transformers import SentenceTransformer

                _model_instance = SentenceTransformer(MODEL_NAME)
    return _model_instance


@lru_cache(maxsize=2)
def _document_vectors(texts: tuple[str, ...]):
    """Encode the small, stable type catalog once per process and content."""
    return _model().encode(list(texts), normalize_embeddings=True)


@lru_cache(maxsize=2)
def _source_for_version(size: int, modified_ns: int):
    return load_source()


def suggestion_source():
    """Reuse parsed source rows until the CSV changes on disk."""
    stamp = SOURCE_PATH.stat()
    return _source_for_version(stamp.st_size, stamp.st_mtime_ns)


def suggest_types(records: list[Observation], types, *, title: str,
                  category: str, item_type: str, model=None) -> list[dict]:
    """Rank database item types backed by source observations, up to five.

    The caller supplies database ItemType objects. Suggestions never create
    historical observations or alter the seller's confirmed category/type.
    """
    query = " ".join(part for part in (title.strip(), item_type.strip(), category.strip()) if part)
    if len(query) < 3:
        return []
    groups = defaultdict(list)
    for record in records:
        groups[(record.category, record.item_type)].append(record)
    eligible = []
    texts = []
    for kind in types:
        key = (normalize(kind.category.category_name), normalize(kind.item_type_name))
        group = groups.get(key)
        if not group:
            continue
        # Representative titles add real product language to the type label.
        examples = sorted({record.name for record in group if record.name})[:8]
        eligible.append((kind, group, examples))
        texts.append(f"{kind.item_type_name}. {kind.category.category_name}. " + ". ".join(examples))
    if not eligible:
        return []
    if model is None:
        document_vectors = _document_vectors(tuple(texts))
        query_vector = _model().encode([query], normalize_embeddings=True)[0]
    else:
        # Test injection keeps the encoder independent of process-global cache.
        vectors = model.encode([query, *texts], normalize_embeddings=True)
        query_vector, document_vectors = vectors[0], vectors[1:]
    matches = []
    for (kind, group, examples), vector in zip(eligible, document_vectors):
        score = float(sum(float(a) * float(b) for a, b in zip(query_vector, vector)))
        if score >= MIN_SIMILARITY:
            matches.append({
                "item_type_id": kind.pk,
                "category_id": kind.category_id,
                "category": kind.category.category_name,
                "item_type": kind.item_type_name,
                "observation_count": len(group),
                "may_support_price": True,
                "limited_evidence": len(group) < MIN_TYPE_ONLY,
                "example_title": examples[0] if examples else "",
                "similarity": round(score, 4),
            })
    matches.sort(key=lambda match: (-match["similarity"], -match["observation_count"], match["item_type_id"]))
    return matches[:MAX_CANDIDATES]
