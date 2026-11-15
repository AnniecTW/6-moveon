from datetime import timedelta
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from marketplace.ai_analytics import Report, load_rows
from marketplace.models import AISearchLog, User

DASHBOARD = "/analytics/ai-search/"


def seed(**options):
    call_command("seed_ai_search_logs", stdout=StringIO(), **options)


class SeedSearchLogsTests(TestCase):
    def test_inserts_only_simulated_rows_inside_the_window(self):
        seed(days=14, searches=300)
        logs = AISearchLog.objects.all()
        self.assertEqual(logs.count(), 300)
        self.assertFalse(logs.filter(is_simulated=False).exists())
        oldest = logs.order_by("created_at").first().created_at
        self.assertGreaterEqual(oldest, timezone.now() - timedelta(days=14))
        self.assertLessEqual(logs.order_by("-created_at").first().created_at, timezone.now())

    def test_same_seed_gives_the_same_history(self):
        seed(searches=120, seed=7)
        first = list(AISearchLog.objects.order_by("created_at", "query").values_list("query", "state"))
        seed(searches=120, seed=7, replace=True)
        second = list(AISearchLog.objects.order_by("created_at", "query").values_list("query", "state"))
        self.assertEqual(first, second)

    def test_replace_keeps_real_logs(self):
        AISearchLog.objects.create(mode="keyword", query="real lamp", total_ms=9)
        seed(searches=50)
        seed(searches=50, replace=True)
        self.assertEqual(AISearchLog.objects.filter(is_simulated=True).count(), 50)
        self.assertTrue(AISearchLog.objects.filter(query="real lamp", is_simulated=False).exists())

    def test_history_exercises_every_dashboard_question(self):
        seed()
        rows = load_rows(AISearchLog.objects.all())
        report = Report(rows, days=30).build()
        kpis = report["kpis"]
        self.assertTrue(0.6 < kpis["ai_share"] < 0.85)
        # The class demo pushes Groq near or past its 8K tokens/minute free-tier limit.
        self.assertGreater(kpis["peak_tpm"], 5_000)
        states = {row["state"] for row in rows if row["mode"] == "ai"}
        self.assertTrue({"ai", "semantic_fallback_error", "no_results"} <= states)
        self.assertIn("rate_limited", {code for _, code, *_ in report["tables"]["errors"]})
        self.assertTrue(report["tables"]["zero_result_queries"])
        self.assertTrue(all(report["charts"].values()))
        stage_groups = {row[0] for row in report["charts"]["stages"]["table"]["rows"]}
        self.assertEqual(stage_groups, {"Cache hit", "Cache miss"})
        # Failed LLM calls carry their wait, so "other" stays small server overhead.
        failed = [row for row in rows if row["llm_error"]]
        self.assertTrue(failed and all(row["llm_ms"] for row in failed))
        other_ms = [row[4] for row in report["charts"]["stages"]["table"]["rows"]]
        self.assertTrue(all(value < 100 for value in other_ms))

    def test_one_day_window_never_writes_future_rows(self):
        seed(days=1, searches=120)
        self.assertEqual(AISearchLog.objects.count(), 120)
        self.assertFalse(AISearchLog.objects.filter(created_at__gt=timezone.now()).exists())

    def test_rejects_non_positive_sizes(self):
        with self.assertRaises(CommandError):
            seed(days=0)


class ReviewerAccountTests(TestCase):
    def create(self, password="uiuc-test-pass", **options):
        with patch.dict("os.environ", {"REVIEWER_TEST_PASSWORD": password}):
            call_command("ensure_reviewer_account", password_env="REVIEWER_TEST_PASSWORD",
                         stdout=StringIO(), **options)
        return User.objects.get(username=options.get("username", "mohitg2"))

    def test_creates_a_verified_staff_account_that_is_not_superuser(self):
        user = self.create()
        self.assertTrue(user.is_staff and user.is_active)
        self.assertFalse(user.is_superuser)
        self.assertTrue(user.email_verified)
        self.assertIsNotNone(user.email_verified_at)
        self.assertEqual(user.account_status, User.AccountStatus.ACTIVE)
        self.assertEqual(user.email, "mohitg2@reviewer.moveon.invalid")
        self.assertTrue(user.check_password("uiuc-test-pass"))

    def test_rerunning_updates_the_password_without_duplicates(self):
        self.create(password="first-pass")
        user = self.create(password="second-pass")
        self.assertEqual(User.objects.filter(username="mohitg2").count(), 1)
        self.assertTrue(user.check_password("second-pass"))

    def test_reviewer_signs_in_and_lands_on_the_dashboard(self):
        self.create(password="uiuc-test-pass")
        redirect = self.client.get(DASHBOARD)
        self.assertEqual(redirect.status_code, 302)
        self.assertTrue(redirect["Location"].startswith(reverse("admin:login")))
        self.assertEqual(self.client.get(redirect["Location"]).status_code, 200)
        response = self.client.post(reverse("admin:login"), {
            "username": "mohitg2", "password": "uiuc-test-pass", "next": DASHBOARD,
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], DASHBOARD)
        self.assertEqual(self.client.get(DASHBOARD).status_code, 200)
        # A non-campus reviewer still cannot use student-only pages.
        self.assertEqual(self.client.get(reverse("a4-charts")).status_code, 302)

    def test_missing_environment_password_fails(self):
        with patch.dict("os.environ", {}, clear=True), self.assertRaises(CommandError):
            call_command("ensure_reviewer_account", password_env="REVIEWER_TEST_PASSWORD", stdout=StringIO())
        self.assertFalse(User.objects.filter(username="mohitg2").exists())

    def test_prompted_passwords_must_match(self):
        with patch("marketplace.management.commands.ensure_reviewer_account.getpass",
                   side_effect=["one-password", "another-password"]), self.assertRaises(CommandError):
            call_command("ensure_reviewer_account", stdout=StringIO())
        with patch("marketplace.management.commands.ensure_reviewer_account.getpass",
                   side_effect=["same-password", "same-password"]):
            call_command("ensure_reviewer_account", stdout=StringIO())
        self.assertTrue(User.objects.get(username="mohitg2").check_password("same-password"))
