import math
from unittest.mock import patch

from django.test import SimpleTestCase

from marketplace.embeddings import (
    TASK_DOCUMENT,
    TASK_QUERY,
    EmbeddingError,
    GeminiEncoder,
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
