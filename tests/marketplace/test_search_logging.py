from unittest.mock import Mock, patch

import requests
from django.db import DatabaseError
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from google.api_core.exceptions import DeadlineExceeded, TooManyRequests

from marketplace import search_semantic
from marketplace.browse import browse_context
from marketplace.embeddings import GeminiEncoder, _failure_reason
from marketplace.models import AISearchLog, ItemCategory, ItemType, Listing, User

GROQ = {"LOCAL_LLM_ENABLED": True, "LLM_RANKING_BACKEND": "groq",
        "GROQ_API_KEY": "test-key", "GROQ_MODEL": "openai/gpt-oss-20b"}


def groq_ok(ids):
    response = Mock(status_code=200, ok=True, headers={})
    response.json.return_value = {
        "choices": [{"message": {"content": '{"ids":%s}' % ids}}],
        "usage": {"prompt_tokens": 530, "completion_tokens": 70,
                  "completion_tokens_details": {"reasoning_tokens": 50}},
    }
    return response


class SearchFixtures(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.seller = User.objects.create_user(username="log-seller", email="log-seller@example.com")
        kind = ItemType.objects.create(
            category=ItemCategory.objects.create(category_name="Furniture"), item_type_name="Lamp",
        )
        cls.first, cls.second = (
            Listing.objects.create(
                seller=cls.seller, item_type=kind, title=title, description=description,
                listing_price=price, condition=Listing.Condition.GOOD,
                status=Listing.Status.ACTIVE, fulfillment_option=Listing.Fulfillment.PICKUP,
            )
            for title, description, price in (("Oak bedside lamp", "Warm bedroom light", "25.00"),
                                              ("Blue reading lamp", "Light for reading", "18.00"))
        )

    def search(self, query="bedroom lamp", mode="ai", **params):
        return self.client.get(reverse("home"), {"q": query, "search_mode": mode, **params})


@override_settings(**GROQ)
@patch("marketplace.local_llm.requests.post")
@patch("marketplace.browse.retrieve")
class RecordedSearchTests(SearchFixtures):
    def test_ai_search_with_groq_records_stages_tokens_and_filters(self, retrieve, post):
        retrieve.side_effect = lambda query, candidates: [(item, .9) for item in candidates]
        post.return_value = groq_ok(f"[{self.second.pk}]")
        self.search(max_price="30")
        log = AISearchLog.objects.get()
        self.assertEqual((log.mode, log.state, log.query), ("ai", "ai", "bedroom lamp"))
        self.assertEqual(log.filters_used, ["max_price"])
        self.assertEqual((log.candidate_count, log.retrieved_count, log.result_count), (2, 2, 1))
        self.assertEqual((log.llm_model, log.prompt_tokens, log.completion_tokens,
                          log.reasoning_tokens, log.llm_error),
                         ("openai/gpt-oss-20b", 530, 70, 50, ""))
        self.assertIsNotNone(log.llm_ms)
        self.assertIsNotNone(log.embedding_ms)
        self.assertGreaterEqual(log.total_ms, log.embedding_ms)
        self.assertIsNone(log.user)
        self.assertFalse(log.is_simulated)

    def test_rate_limited_ranking_records_the_error_code(self, retrieve, post):
        retrieve.side_effect = lambda query, candidates: [(item, .9) for item in candidates]
        post.return_value = Mock(status_code=429, ok=False, headers={})
        self.search()
        log = AISearchLog.objects.get()
        self.assertEqual((log.state, log.llm_error), ("semantic_fallback_error", "rate_limited"))
        self.assertIsNone(log.prompt_tokens)
        self.assertIsNotNone(log.llm_ms)

    def test_keyword_search_records_mode_and_results_only(self, retrieve, post):
        self.client.force_login(self.seller)
        self.search("lamp", mode="keyword")
        log = AISearchLog.objects.get()
        self.assertEqual((log.mode, log.state, log.result_count, log.user), ("keyword", "", 2, self.seller))
        self.assertEqual((log.llm_model, log.embedding_model, log.candidate_count), ("", "", None))
        retrieve.assert_not_called()

    def test_browsing_without_a_query_records_nothing(self, retrieve, post):
        self.client.get(reverse("home"))
        self.client.get(reverse("home"), {"q": "   ", "search_mode": "ai"})
        self.assertFalse(AISearchLog.objects.exists())

    def test_offline_evaluation_can_skip_recording(self, retrieve, post):
        request = RequestFactory().get("/", {"q": "lamp", "search_mode": "keyword"})
        request.user = self.seller
        browse_context(request, use_local_llm=True, record=False)
        self.assertFalse(AISearchLog.objects.exists())

    def test_logging_failure_never_breaks_search(self, retrieve, post):
        with patch.object(AISearchLog.objects, "create", side_effect=DatabaseError("locked")):
            response = self.search("lamp", mode="keyword")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["listings"]), 2)


def fake_embed(*, model, content, task_type, output_dimensionality, request_options):
    return {"embedding": [[1.0, 0.0] for _ in content]}


@override_settings(EMBEDDING_BACKEND="gemini", GEMINI_API_KEY="test-key", LOCAL_LLM_ENABLED=False)
@patch("google.generativeai.configure")
class GeminiUsageTests(SearchFixtures):
    def setUp(self):
        search_semantic._catalog_vectors.cache_clear()
        self.addCleanup(search_semantic._catalog_vectors.cache_clear)
        encoder = GeminiEncoder("test-key")
        patcher = patch("marketplace.search_semantic._model", return_value=encoder)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_cache_misses_count_toward_usage_and_hits_do_not(self, configure):
        with patch("google.generativeai.embed_content", side_effect=fake_embed):
            self.search("bedroom lamp")
            self.search("bedroom lamp")
        first, second = AISearchLog.objects.order_by("pk")
        # First search embeds the query and both listings; the repeat is fully cached.
        self.assertEqual(first.embedding_texts_sent, 3)
        self.assertGreater(first.embedding_chars, len("bedroom lamp"))
        self.assertEqual((second.embedding_texts_sent, second.embedding_chars), (0, 0))
        self.assertEqual((first.state, first.embedding_model), ("semantic_only", "gemini-embedding-001"))

    def test_gemini_quota_error_is_recorded_as_rate_limited(self, configure):
        with patch("google.generativeai.embed_content", side_effect=TooManyRequests("quota")):
            response = self.search("bedroom lamp")
        log = AISearchLog.objects.get()
        self.assertEqual((log.state, log.embedding_error), ("unavailable", "rate_limited"))
        self.assertEqual(log.embedding_texts_sent, 0)
        self.assertContains(response, "data-ai-search-toast")


class FailureReasonTests(SimpleTestCase):
    def test_classifies_quota_timeouts_and_other_errors(self):
        self.assertEqual(_failure_reason(TooManyRequests("quota")), "rate_limited")
        self.assertEqual(_failure_reason(DeadlineExceeded("slow")), "timeout")
        self.assertEqual(_failure_reason(requests.ReadTimeout("slow")), "timeout")
        self.assertEqual(_failure_reason(ValueError("bad")), "api_error")
