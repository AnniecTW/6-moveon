from datetime import timedelta

from django.contrib.admin.sites import site
from django.test import RequestFactory, TestCase
from django.utils import timezone

from marketplace.models import AISearchLog, User


class AISearchLogModelTests(TestCase):
    def test_defaults_describe_a_keyword_search(self):
        log = AISearchLog.objects.create(mode=AISearchLog.Mode.KEYWORD, query="desk lamp", total_ms=12)
        self.assertEqual(log.filters_used, [])
        self.assertEqual(log.state, "")
        self.assertFalse(log.is_simulated)
        self.assertIsNone(log.user)
        self.assertLess(abs(timezone.now() - log.created_at), timedelta(seconds=5))
        self.assertEqual(str(log), "Keyword search 'desk lamp' (keyword)")

    def test_simulated_history_keeps_its_timestamp_and_newest_sorts_first(self):
        old = AISearchLog.objects.create(mode="ai", query="old", total_ms=900, state="ai",
                                         is_simulated=True,
                                         created_at=timezone.now() - timedelta(days=10))
        new = AISearchLog.objects.create(mode="ai", query="new", total_ms=400, state="semantic_only")
        self.assertEqual(list(AISearchLog.objects.all()), [new, old])
        self.assertTrue(AISearchLog.objects.get(pk=old.pk).is_simulated)

    def test_deleting_a_user_keeps_their_search_history(self):
        user = User.objects.create_user(username="searcher", email="searcher@example.com")
        log = AISearchLog.objects.create(user=user, mode="ai", query="sofa", total_ms=500)
        user.delete()
        log.refresh_from_db()
        self.assertIsNone(log.user)


class AISearchLogAdminTests(TestCase):
    def test_admin_is_read_only(self):
        admin = site._registry[AISearchLog]
        request = RequestFactory().get("/admin/")
        request.user = User.objects.create_superuser(
            username="admin", email="admin@example.com", password="admin-pass-123",
        )
        self.assertFalse(admin.has_add_permission(request))
        self.assertFalse(admin.has_change_permission(request))
        self.assertTrue(admin.has_view_permission(request))
