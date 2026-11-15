import math
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from marketplace.embeddings import (
    TASK_DOCUMENT,
    TASK_QUERY,
    EmbeddingError,
    GeminiEncoder,
    load_encoder,
)


def fake_embed_content(*, model, content, task_type, output_dimensionality, request_options):
    """Deterministic, unnormalized vectors so tests can check normalization."""
    return {"embedding": [[float(len(text)), 1.0, 0.0] for text in content]}


@patch("google.generativeai.configure")
@patch("google.generativeai.embed_content", side_effect=fake_embed_content)
class GeminiEncoderTests(SimpleTestCase):
    def test_returns_normalized_vectors_in_input_order(self, embed, configure):
        vectors = GeminiEncoder("test-key").encode(["lamp", "microwave oven"])
        self.assertEqual(len(vectors), 2)
        for vector in vectors:
            self.assertAlmostEqual(math.sqrt(sum(value * value for value in vector)), 1.0)
        # Longer text has the larger first component in the fake vectors.
        self.assertGreater(vectors[1][0], vectors[0][0])

    def test_request_uses_rest_dimensions_task_and_timeout(self, embed, configure):
        GeminiEncoder("test-key", dimensions=768, timeout=9).encode(["desk"], task_type=TASK_QUERY)
        configure.assert_called_once_with(api_key="test-key", transport="rest")
        kwargs = embed.call_args.kwargs
        self.assertEqual(kwargs["model"], "models/gemini-embedding-001")
        self.assertEqual(kwargs["content"], ["desk"])
        self.assertEqual(kwargs["task_type"], TASK_QUERY)
        self.assertEqual(kwargs["output_dimensionality"], 768)
        self.assertEqual(kwargs["request_options"], {"timeout": 9, "retry": None})

    def test_only_unseen_texts_reach_the_api(self, embed, configure):
        encoder = GeminiEncoder("test-key")
        encoder.encode(["desk", "chair"])
        encoder.encode(["chair", "desk", "sofa", "sofa"])
        self.assertEqual(embed.call_count, 2)
        self.assertEqual(embed.call_args.kwargs["content"], ["sofa"])
        encoder.encode(["sofa", "desk"])
        self.assertEqual(embed.call_count, 2)

    def test_query_and_document_vectors_are_cached_separately(self, embed, configure):
        encoder = GeminiEncoder("test-key")
        encoder.encode(["desk"], task_type=TASK_DOCUMENT)
        encoder.encode(["desk"], task_type=TASK_QUERY)
        self.assertEqual(embed.call_count, 2)

    def test_cache_evicts_oldest_entries_and_still_returns_all_vectors(self, embed, configure):
        encoder = GeminiEncoder("test-key", max_cached=2)
        vectors = encoder.encode(["a", "bb", "ccc"])
        self.assertEqual(len(vectors), 3)
        self.assertEqual(len(encoder._cache), 2)
        encoder.encode(["a"])
        self.assertEqual(embed.call_args.kwargs["content"], ["a"])

    def test_unnormalized_output_is_available(self, embed, configure):
        vector = GeminiEncoder("test-key").encode(["desk"], normalize_embeddings=False)[0]
        self.assertEqual(vector, [4.0, 1.0, 0.0])

    def test_empty_input_skips_the_api(self, embed, configure):
        self.assertEqual(GeminiEncoder("test-key").encode([]), [])
        embed.assert_not_called()

    def test_missing_key_raises_embedding_error(self, embed, configure):
        with self.assertRaises(EmbeddingError):
            GeminiEncoder("").encode(["desk"])
        embed.assert_not_called()

    def test_api_failure_is_wrapped_and_not_cached(self, embed, configure):
        encoder = GeminiEncoder("test-key")
        embed.side_effect = RuntimeError("429 quota")
        with self.assertRaises(EmbeddingError):
            encoder.encode(["desk"])
        embed.side_effect = fake_embed_content
        self.assertEqual(len(encoder.encode(["desk"])), 1)
        self.assertEqual(embed.call_count, 2)

    def test_count_mismatch_raises_embedding_error(self, embed, configure):
        embed.side_effect = lambda **kwargs: {"embedding": [[1.0, 0.0]]}
        with self.assertRaises(EmbeddingError):
            GeminiEncoder("test-key").encode(["desk", "chair"])


class RecordingEmbed:
    """Fake embed_content that records each request's task type and texts."""

    def __init__(self):
        self.calls = []

    def __call__(self, *, model, content, task_type, output_dimensionality, request_options):
        self.calls.append((task_type, list(content)))
        return {"embedding": [[1.0, 0.0] for _ in content]}


@patch("google.generativeai.configure")
class EmbeddingBackendTests(SimpleTestCase):
    def test_gemini_backend_builds_gemini_encoder_from_settings(self, configure):
        from marketplace.pricing import semantic

        with override_settings(EMBEDDING_BACKEND="gemini", GEMINI_API_KEY="test-key",
                               GEMINI_EMBEDDING_MODEL="gemini-embedding-test"), \
                patch.object(semantic, "_model_instance", None):
            encoder = semantic._model()
            self.assertIsInstance(encoder, GeminiEncoder)
            self.assertEqual(encoder.api_key, "test-key")
            self.assertEqual(encoder.model_name, "gemini-embedding-test")
            self.assertIs(semantic._model(), encoder)

    @patch("sentence_transformers.SentenceTransformer")
    def test_local_backend_keeps_minilm(self, sentence_transformer, configure):
        encoder = load_encoder("local", local_model_name="minilm", api_key="",
                               gemini_model_name="unused")
        sentence_transformer.assert_called_once_with("minilm")
        self.assertIs(encoder, sentence_transformer.return_value)

    def test_listing_search_embeds_query_and_listings_with_their_task_types(self, configure):
        from marketplace.search_semantic import retrieve

        fake = RecordingEmbed()
        candidates = [{"pk": 1, "title": "Microwave", "category": "Kitchen", "description": ""}]
        with patch("google.generativeai.embed_content", side_effect=fake):
            result = retrieve("heat up food", candidates, model=GeminiEncoder("test-key"))
        self.assertEqual(len(result), 1)
        self.assertEqual(fake.calls, [
            (TASK_QUERY, ["heat up food"]),
            (TASK_DOCUMENT, ["Microwave. Kitchen"]),
        ])

    def test_pricing_suggestions_embed_title_as_query(self, configure):
        from marketplace.pricing import semantic
        from marketplace.pricing.initial import Observation

        category = SimpleNamespace(pk=1, category_name="Furniture")
        kind = SimpleNamespace(pk=1, category=category, category_id=1, item_type_name="Bookshelf")
        rows = [Observation("1", datetime(2023, 6, 1, tzinfo=timezone.utc), Decimal("35"),
                            "furniture", "bookshelf", "GOOD", "", "wooden bookcase", "sample")]
        fake = RecordingEmbed()
        semantic._document_vectors.cache_clear()
        try:
            with patch("google.generativeai.embed_content", side_effect=fake), \
                    patch.object(semantic, "_model", return_value=GeminiEncoder("test-key")):
                result = semantic.suggest_types(rows, [kind], title="Bookcase",
                                                category="Furniture", item_type="")
        finally:
            semantic._document_vectors.cache_clear()
        self.assertEqual(result[0]["item_type"], "Bookshelf")
        self.assertEqual(sorted(task for task, _ in fake.calls), [TASK_DOCUMENT, TASK_QUERY])
        self.assertIn((TASK_QUERY, ["Bookcase Furniture"]), fake.calls)

    @override_settings(EMBEDDING_BACKEND="gemini")
    @patch.dict("os.environ", {"MOVEON_PRELOAD_PRICING": "1"})
    def test_startup_preload_skips_the_hosted_backend(self, configure):
        from django.apps import apps

        with patch("marketplace.pricing.semantic._model") as model:
            apps.get_app_config("marketplace").ready()
        model.assert_not_called()


GEMINI_TEST_THRESHOLDS = {
    "search": 0.60, "fallback": 0.70, "semantic_only": 0.65, "gate": 0.70, "pricing": 0.70,
}


class SimilarityThresholdTests(SimpleTestCase):
    def test_local_backend_keeps_the_a9_minilm_values(self):
        from marketplace.embeddings import similarity_threshold

        with override_settings(EMBEDDING_BACKEND="local"):
            self.assertEqual(
                {name: similarity_threshold(name)
                 for name in ("search", "fallback", "semantic_only", "gate", "pricing")},
                {"search": 0.30, "fallback": 0.40, "semantic_only": 0.33, "gate": 0.40, "pricing": 0.40},
            )

    @override_settings(EMBEDDING_BACKEND="gemini")
    def test_uncalibrated_gemini_fails_closed_as_search_unavailable(self):
        from marketplace.search_semantic import SemanticSearchError, retrieve

        encoder = SimpleNamespace(encode=lambda texts, **kwargs: [[1.0, 0.0] for _ in texts])
        with patch.dict("marketplace.embeddings.SIMILARITY_THRESHOLDS",
                        {"gemini": dict.fromkeys(GEMINI_TEST_THRESHOLDS)}):
            with self.assertRaises(SemanticSearchError):
                retrieve("desk", [{"pk": 1, "title": "Desk"}], model=encoder)

    @override_settings(EMBEDDING_BACKEND="gemini")
    def test_search_and_gate_use_the_active_backend_values(self):
        from marketplace.local_llm import gate_listing_ids
        from marketplace.search_semantic import retrieve

        # Query vector [1, 0]; listing cosines are 0.65 and 0.5.
        vectors = {"desk": [1.0, 0.0], "Lamp": [0.65, 0.76], "Rug": [0.5, 0.866]}
        encoder = SimpleNamespace(encode=lambda texts, **kwargs: [vectors[t] for t in texts])
        candidates = [{"pk": 1, "title": "Lamp"}, {"pk": 2, "title": "Rug"}]
        catalog = [{"id": 1, "title": "Lamp", "category": "", "description": ""}]
        with patch.dict("marketplace.embeddings.SIMILARITY_THRESHOLDS",
                        {"gemini": GEMINI_TEST_THRESHOLDS}):
            kept = retrieve("desk", candidates, model=encoder)
            # 0.65 clears Gemini's 0.60 search bar but not its 0.70 gate.
            gated = gate_listing_ids("desk", [1], catalog, {1: 0.65})
        self.assertEqual([item["pk"] for item, _ in kept], [1])
        self.assertEqual(gated, [])

    @override_settings(EMBEDDING_BACKEND="gemini")
    def test_word_gate_without_scores_needs_no_threshold(self):
        from marketplace.local_llm import gate_listing_ids

        catalog = [{"id": 1, "title": "Desk lamp", "category": "", "description": ""}]
        with patch.dict("marketplace.embeddings.SIMILARITY_THRESHOLDS",
                        {"gemini": dict.fromkeys(GEMINI_TEST_THRESHOLDS)}):
            self.assertEqual(gate_listing_ids("desk", [1], catalog), [1])
