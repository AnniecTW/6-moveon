from unittest.mock import Mock, patch

import requests
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from marketplace.local_llm import (
    GROQ_CHAT_URL, GROQ_MAX_COMPLETION_TOKENS, GROQ_TIMEOUT_SECONDS,
    RankingServiceError, _generate_response,
)
from marketplace.models import ItemCategory, ItemType, Listing, User

MESSAGES = [{"role": "system", "content": "Return JSON."}, {"role": "user", "content": "{}"}]
GROQ_SETTINGS = {"LLM_RANKING_BACKEND": "groq", "GROQ_API_KEY": "test-key",
                 "GROQ_MODEL": "openai/gpt-oss-20b"}


def groq_response(content='{"ids":[1]}', status=200, headers=None, payload=None):
    response = Mock(status_code=status, ok=200 <= status < 300, headers=headers or {})
    response.json.return_value = payload if payload is not None else {
        "choices": [{"message": {"content": content, "reasoning": "short thought"}}],
        "usage": {"prompt_tokens": 530, "completion_tokens": 70, "total_tokens": 600,
                  "completion_tokens_details": {"reasoning_tokens": 50}},
    }
    return response


@override_settings(**GROQ_SETTINGS)
@patch("marketplace.local_llm.requests.post")
class GroqGenerationTests(SimpleTestCase):
    def test_sends_json_request_and_records_usage(self, post):
        post.return_value = groq_response()
        metrics = {}
        self.assertEqual(_generate_response(MESSAGES, metrics), '{"ids":[1]}')
        url = post.call_args.args[0]
        kwargs = post.call_args.kwargs
        self.assertEqual(url, GROQ_CHAT_URL)
        self.assertEqual(kwargs["headers"], {"Authorization": "Bearer test-key"})
        self.assertEqual(kwargs["timeout"], GROQ_TIMEOUT_SECONDS)
        self.assertEqual(kwargs["json"], {
            "model": "openai/gpt-oss-20b", "messages": MESSAGES, "temperature": 0,
            "max_completion_tokens": GROQ_MAX_COMPLETION_TOKENS,
            "response_format": {"type": "json_object"}, "reasoning_effort": "low",
        })
        self.assertEqual(metrics["backend"], "groq")
        self.assertEqual(metrics["model"], "openai/gpt-oss-20b")
        self.assertEqual((metrics["prompt_tokens"], metrics["completion_tokens"],
                          metrics["reasoning_tokens"]), (530, 70, 50))
        self.assertIn("seconds", metrics)
        self.assertNotIn("error", metrics)

    @override_settings(GROQ_MODEL="qwen/qwen3.8-27b")
    def test_reasoning_effort_is_only_sent_to_gpt_oss(self, post):
        post.return_value = groq_response()
        _generate_response(MESSAGES, {})
        self.assertNotIn("reasoning_effort", post.call_args.kwargs["json"])

    @override_settings(GROQ_API_KEY="")
    def test_missing_key_fails_without_a_request(self, post):
        metrics = {}
        with self.assertRaises(RankingServiceError):
            _generate_response(MESSAGES, metrics)
        post.assert_not_called()
        self.assertEqual(metrics["error"], "not_configured")

    def test_failures_become_ranking_errors_with_reason_codes(self, post):
        cases = [
            ("rate_limited", {"return_value": groq_response(status=429, headers={"retry-after": "7"})}),
            ("http_503", {"return_value": groq_response(status=503)}),
            ("timeout", {"side_effect": requests.Timeout("slow")}),
            ("network", {"side_effect": requests.ConnectionError("down")}),
            ("bad_response", {"return_value": groq_response(payload={"choices": []})}),
        ]
        for reason, behavior in cases:
            with self.subTest(reason=reason):
                post.reset_mock(return_value=True, side_effect=True)
                post.configure_mock(**behavior)
                metrics = {}
                with self.assertRaises(RankingServiceError) as raised:
                    _generate_response(MESSAGES, metrics)
                self.assertEqual(raised.exception.reason, reason)
                self.assertEqual(metrics["error"], reason)
                # The wait still counts as LLM time for the stage breakdown.
                self.assertIn("seconds", metrics)
                if reason == "rate_limited":
                    self.assertEqual(raised.exception.retry_after, "7")


@override_settings(LOCAL_LLM_ENABLED=True, **GROQ_SETTINGS)
@patch("marketplace.local_llm.requests.post")
@patch("marketplace.browse.retrieve")
class GroqSearchViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        seller = User.objects.create_user(username="groq-seller", email="groq-seller@example.com")
        kind = ItemType.objects.create(
            category=ItemCategory.objects.create(category_name="Furniture"), item_type_name="Lamp",
        )
        cls.first, cls.second = (
            Listing.objects.create(
                seller=seller, item_type=kind, title=title, description=description,
                listing_price=price, condition=Listing.Condition.GOOD,
                status=Listing.Status.ACTIVE, fulfillment_option=Listing.Fulfillment.PICKUP,
            )
            for title, description, price in (("Oak bedside lamp", "Warm bedroom light", "25.00"),
                                              ("Blue reading lamp", "Light for reading", "18.00"))
        )

    def _search(self):
        return self.client.get(reverse("home"), {"q": "bedroom lamp", "search_mode": "ai"})

    def test_groq_ranking_orders_results_and_exposes_metrics(self, retrieve, post):
        retrieve.side_effect = lambda query, candidates: [(item, .9) for item in candidates]
        post.return_value = groq_response(f'{{"ids":[{self.second.pk},{self.first.pk}]}}')
        response = self._search()
        self.assertEqual([item.pk for item in response.context["listings"]],
                         [self.second.pk, self.first.pk])
        self.assertEqual(response.context["ai_search_state"], "ai")
        self.assertContains(response, "Ranked by AI.")
        metrics = response.context["ai_llm_metrics"]
        self.assertEqual((metrics["backend"], metrics["prompt_tokens"]), ("groq", 530))

    def test_rate_limit_falls_back_to_semantic_matches_with_alert(self, retrieve, post):
        retrieve.side_effect = lambda query, candidates: [(item, .9) for item in candidates]
        post.return_value = groq_response(status=429)
        response = self._search()
        self.assertEqual(response.context["ai_search_state"], "semantic_fallback_error")
        self.assertEqual(len(response.context["listings"]), 2)
        self.assertEqual(response.context["ai_llm_metrics"]["error"], "rate_limited")
        self.assertContains(response, "data-ai-search-toast")

    def test_keyword_search_never_calls_groq(self, retrieve, post):
        response = self.client.get(reverse("home"), {"q": "lamp", "search_mode": "keyword"})
        self.assertIsNone(response.context["ai_llm_metrics"])
        post.assert_not_called()
        retrieve.assert_not_called()
