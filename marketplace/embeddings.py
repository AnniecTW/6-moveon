"""Hosted embeddings that stand in for the local MiniLM encoder.

PythonAnywhere's free tier cannot hold torch, so production embeds text with the
Gemini API. ``GeminiEncoder.encode`` keeps the SentenceTransformer call shape
used by listing search and pricing type discovery.
"""

import hashlib
import logging
import math
from collections import OrderedDict
from threading import Lock

logger = logging.getLogger(__name__)

GEMINI_EMBEDDING_MODEL_NAME = "gemini-embedding-001"
# Matryoshka-trained vectors keep most quality when truncated. 768 dimensions
# cut the pure-Python dot products and cache memory to a quarter of 3072.
GEMINI_EMBEDDING_DIMENSIONS = 768
GEMINI_EMBEDDING_TIMEOUT_SECONDS = 15
# Search sends one query per request; documents repeat across requests.
TASK_QUERY = "retrieval_query"
TASK_DOCUMENT = "retrieval_document"
MAX_CACHED_VECTORS = 5000

# Cosine cutoffs differ per model: Gemini scores sit higher overall (an unrelated
# dresser scored 0.53 for "heat up food quickly"), so MiniLM's values would let
# nearly everything through. Gemini stays None until calibrated; lookups then
# fail closed, and search shows its unavailable state instead of noise.
SIMILARITY_THRESHOLDS = {
    "local": {
        # Retrieval favors recall because Llama checks the shortlist.
        "search": 0.30,
        # Stricter when embeddings alone supply the displayed results.
        "fallback": 0.40,
        # Direct semantic mode admits short paraphrases ("heat up food" -> microwave).
        "semantic_only": 0.33,
        # A Llama pick passes the word gate without a shared word at this score.
        # 0.35 also admitted coffee tables for "sit" and curtains for "brighter".
        "gate": 0.40,
        # Pricing type discovery only; not a price-confidence probability.
        "pricing": 0.40,
    },
    "gemini": {
        "search": None,
        "fallback": None,
        "semantic_only": None,
        "gate": None,
        "pricing": None,
    },
}


class EmbeddingError(RuntimeError):
    """The hosted embedding service could not return vectors."""


def similarity_threshold(name):
    """Return the active backend's cosine cutoff for one decision point."""
    from django.conf import settings

    backend = settings.EMBEDDING_BACKEND
    value = SIMILARITY_THRESHOLDS[backend][name]
    if value is None:
        raise EmbeddingError(f"The {backend} '{name}' similarity threshold is not calibrated.")
    return value


def _normalized(vector):
    norm = math.sqrt(sum(value * value for value in vector))
    return [value / norm for value in vector] if norm else list(vector)


class GeminiEncoder:
    """Embed text with Gemini, calling the API only for text it has not seen.

    Vectors are cached per text, so a filter change that alters the candidate
    set re-sends only listings that are new or edited. The cache lives in this
    process and is rebuilt after a web-app reload.
    """

    def __init__(self, api_key, *, model_name=GEMINI_EMBEDDING_MODEL_NAME,
                 dimensions=GEMINI_EMBEDDING_DIMENSIONS,
                 timeout=GEMINI_EMBEDDING_TIMEOUT_SECONDS,
                 max_cached=MAX_CACHED_VECTORS):
        self.api_key = api_key
        self.model_name = model_name
        self.dimensions = dimensions
        self.timeout = timeout
        self.max_cached = max_cached
        self._cache = OrderedDict()
        self._lock = Lock()

    def _cache_key(self, text, task_type):
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        return (self.model_name, self.dimensions, task_type, digest)

    def _embed(self, texts, task_type):
        if not self.api_key:
            raise EmbeddingError("GEMINI_API_KEY is not configured.")
        import google.generativeai as genai

        # REST passes PythonAnywhere's HTTP proxy; the SDK's default gRPC does not.
        genai.configure(api_key=self.api_key, transport="rest")
        try:
            # The SDK splits lists into batch requests of up to 100 texts.
            response = genai.embed_content(
                model=f"models/{self.model_name}",
                content=list(texts),
                task_type=task_type,
                output_dimensionality=self.dimensions,
                request_options={"timeout": self.timeout, "retry": None},
            )
            vectors = response["embedding"]
        except Exception as error:
            raise EmbeddingError("Gemini embedding request failed.") from error
        if len(vectors) != len(texts):
            raise EmbeddingError(
                f"Gemini returned {len(vectors)} embeddings for {len(texts)} texts."
            )
        return [[float(value) for value in vector] for vector in vectors]

    def encode(self, texts, normalize_embeddings=True, task_type=TASK_DOCUMENT):
        """Return one vector per text, in order, as lists of floats."""
        texts = [str(text) for text in texts]
        if not texts:
            return []
        keys = [self._cache_key(text, task_type) for text in texts]
        found = {}
        missing = {}
        with self._lock:
            for key, text in zip(keys, texts):
                if key in self._cache:
                    self._cache.move_to_end(key)
                    found[key] = self._cache[key]
                else:
                    missing.setdefault(key, text)
        if missing:
            vectors = self._embed(list(missing.values()), task_type)
            logger.info("Gemini embedded %s new texts (%s requested).", len(missing), len(texts))
            found.update(zip(missing, vectors))
            with self._lock:
                for key, vector in zip(missing, vectors):
                    self._cache[key] = vector
                while len(self._cache) > self.max_cached:
                    self._cache.popitem(last=False)
        return [_normalized(found[key]) if normalize_embeddings else list(found[key])
                for key in keys]


def load_encoder(backend, *, local_model_name, api_key, gemini_model_name):
    """Build the configured encoder; callers keep one per process."""
    if backend == "gemini":
        return GeminiEncoder(api_key, model_name=gemini_model_name)
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(local_model_name)


def encode_query(encoder, texts):
    """Embed search text; Gemini uses its query task, MiniLM is symmetric."""
    if isinstance(encoder, GeminiEncoder):
        return encoder.encode(texts, normalize_embeddings=True, task_type=TASK_QUERY)
    return encoder.encode(texts, normalize_embeddings=True)
