import json
from datetime import timedelta

from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone

from marketplace.ai_analytics import Report, percentile, search_cost
from marketplace.models import AISearchLog, User

URL = "/analytics/ai-search/"


def ai_row(**overrides):
    row = dict(
        created_at=timezone.now(), mode="ai", query="storage for books", filters_used=[], state="ai",
        result_count=3, candidate_count=42, retrieved_count=4, total_ms=600, embedding_ms=200, llm_ms=350,
        embedding_model="gemini-embedding-001", embedding_texts_sent=1, embedding_chars=40,
        embedding_error="", llm_model="openai/gpt-oss-20b", prompt_tokens=400, completion_tokens=60,
        reasoning_tokens=30, llm_error="",
    )
    row.update(overrides)
    return row


class AnalyticsMathTests(SimpleTestCase):
    def test_percentile_interpolates(self):
        self.assertEqual(percentile([1, 2, 3, 4], 50), 2.5)
        self.assertEqual(percentile([5], 95), 5)
        self.assertAlmostEqual(percentile(list(range(1, 101)), 95), 95.05)

    def test_search_cost_prices_llm_tokens_and_estimated_embedding_tokens(self):
        cost = search_cost(ai_row(prompt_tokens=1_000_000, completion_tokens=1_000_000,
                                  embedding_chars=4_000_000))
        self.assertAlmostEqual(cost["llm_input"], 0.075)
        self.assertAlmostEqual(cost["llm_output"], 0.30)
        self.assertAlmostEqual(cost["embedding"], 0.15)

    def test_local_models_and_keyword_searches_cost_nothing(self):
        local = ai_row(llm_model="meta-llama/Llama-3.2-3B-Instruct", embedding_model="all-MiniLM-L6-v2")
        self.assertEqual(sum(search_cost(local).values()), 0)

    def test_report_answers_every_question_with_consistent_numbers(self):
        rows = [ai_row(total_ms=ms) for ms in (400, 500, 600, 700)] + [
            ai_row(state="semantic_fallback_error", llm_error="rate_limited", llm_ms=None,
                   prompt_tokens=None, completion_tokens=None, total_ms=900),
            ai_row(state="unavailable", embedding_error="rate_limited", result_count=0,
                   query="snowboard", total_ms=300, llm_ms=None, prompt_tokens=None,
                   completion_tokens=None, embedding_texts_sent=0),
            ai_row(embedding_texts_sent=43, embedding_chars=3200, embedding_ms=1300, total_ms=1700),
            ai_row(mode="keyword", state="", query="lamp", filters_used=["max_price"], total_ms=8,
                   embedding_model="", llm_model="", prompt_tokens=None, completion_tokens=None),
        ]
        report = Report(rows, days=30).build()
        kpis = report["kpis"]
        self.assertEqual((kpis["searches"], kpis["ai_searches"]), (8, 7))
        self.assertAlmostEqual(kpis["degraded_rate"], 2 / 7)
        self.assertEqual(kpis["peak_tpm"], 460 * 5)
        self.assertEqual(set(report["charts"]), {"latency", "stages", "outcomes", "modes", "query_length",
                                                 "filters", "cost_daily", "tokens", "projection"})
        self.assertTrue(all(chart for chart in report["charts"].values()))
        self.assertEqual(report["tables"]["errors"],
                         [["LLM ranking (Groq)", "rate_limited", 1, "14.3%"],
                          ["Embedding (Gemini)", "rate_limited", 1, "14.3%"]])
        self.assertEqual(report["tables"]["zero_result_queries"], [["snowboard", 1]])
        groups = {row[0] for row in report["charts"]["stages"]["table"]["rows"]}
        self.assertEqual(groups, {"Cache hit", "Cache miss"})
        # Every spec must be JSON for json_script and declare Vega-Lite v5.
        for chart in report["charts"].values():
            self.assertIn("vega-lite/v5", json.loads(json.dumps(chart["spec"]))["$schema"])

    def test_keyword_only_data_skips_ai_charts_without_failing(self):
        report = Report([ai_row(mode="keyword", state="")], days=7).build()
        self.assertIsNone(report["charts"]["latency"])
        self.assertIsNone(report["kpis"]["p50_s"])
        self.assertIsNotNone(report["charts"]["modes"])


class AnalyticsPageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        verified = {"email_verified": True, "email_verified_at": timezone.now()}
        cls.staff = User.objects.create_user(username="reviewer", email="reviewer@example.com",
                                             password="test-password", is_staff=True, **verified)
        # A campus shopper passes the campus middleware but is not staff.
        cls.shopper = User.objects.create_user(username="shopper", email="shopper@illinois.edu",
                                               password="test-password", **verified)

    def log(self, **fields):
        defaults = {"mode": "ai", "query": "storage for books", "state": "ai", "result_count": 3,
                    "total_ms": 600, "embedding_ms": 200, "llm_ms": 350,
                    "embedding_model": "gemini-embedding-001", "embedding_texts_sent": 1,
                    "embedding_chars": 40, "llm_model": "openai/gpt-oss-20b", "prompt_tokens": 400,
                    "completion_tokens": 60, "retrieved_count": 4, "candidate_count": 42}
        return AISearchLog.objects.create(**{**defaults, **fields})

    def test_url_is_stable(self):
        self.assertEqual(reverse("ai-search-analytics"), URL)

    def test_anonymous_visitors_are_sent_to_sign_in(self):
        response = self.client.get(URL)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/account/", response["Location"])
        self.assertIn("next=", response["Location"])

    def test_signed_in_non_staff_are_forbidden(self):
        self.client.force_login(self.shopper)
        self.assertEqual(self.client.get(URL).status_code, 403)

    def test_staff_exemption_does_not_open_other_campus_pages(self):
        # The reviewer has no campus email; only the analytics page skips the campus check.
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(URL).status_code, 200)
        self.assertEqual(self.client.get(reverse("a4-charts")).status_code, 302)

    def test_inactive_staff_cannot_use_the_exemption(self):
        User.objects.filter(pk=self.staff.pk).update(is_active=False)
        self.client.force_login(self.staff)
        self.assertNotEqual(self.client.get(URL).status_code, 200)

    def test_staff_see_empty_state_without_logs(self):
        self.client.force_login(self.staff)
        response = self.client.get(URL)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No searches in this range")

    def test_staff_see_every_question_and_embedded_specs(self):
        self.log()
        self.log(mode="keyword", state="", query="lamp")
        self.client.force_login(self.staff)
        response = self.client.get(URL)
        self.assertEqual(response.status_code, 200)
        for code in ("P1", "P2", "P3", "U1", "U2", "U3", "C1", "C2", "C3"):
            self.assertContains(response, f'id="question-{code}"')
        self.assertContains(response, 'id="spec-p1" type="application/json"')
        self.assertContains(response, 'data-vega-spec-id="spec-u3-b"')
        self.assertContains(response, "2 real searches, 0 simulated")
        self.assertContains(response, "vega-charts.js?v=ai-analytics-1")

    def test_time_range_and_source_filters(self):
        self.log(query="recent real")
        self.log(query="old real", created_at=timezone.now() - timedelta(days=20))
        self.log(query="simulated", is_simulated=True)
        self.client.force_login(self.staff)
        week = self.client.get(URL, {"range": "7"}).context["report"]["kpis"]
        self.assertEqual(week["searches"], 2)
        month_real = self.client.get(URL, {"range": "30", "source": "real"}).context["report"]["kpis"]
        self.assertEqual(month_real["searches"], 2)
        simulated = self.client.get(URL, {"source": "simulated"}).context["report"]["kpis"]
        self.assertEqual(simulated["searches"], 1)
        fallback = self.client.get(URL, {"range": "bogus", "source": "bogus"})
        self.assertEqual((fallback.context["range_key"], fallback.context["source_key"]), ("30", "all"))

    def test_header_links_to_dashboard_for_staff_only(self):
        self.client.force_login(self.staff)
        self.assertContains(self.client.get(reverse("home")), URL)
        self.client.force_login(self.shopper)
        self.assertNotContains(self.client.get(reverse("home")), URL)
