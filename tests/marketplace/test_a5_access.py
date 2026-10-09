"""Fixed A5 access policy, independent of obsolete assignment switches."""

from unittest.mock import patch

from django.core import signing
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from marketplace.models import ItemCategory, ItemType, Listing, User


class A5AccessTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.student = User.objects.create_user(
            username="access-student", email="access-student@illinois.edu",
            display_name="Student", email_verified=True,
            email_verified_at=timezone.now(),
        )
        cls.other = User.objects.create_user(
            username="access-other", email="access-other@illinois.edu",
            display_name="Other", email_verified=True,
            email_verified_at=timezone.now(),
        )
        cls.unverified = User.objects.create_user(
            username="access-unverified", email="access-unverified@illinois.edu",
            display_name="Unverified",
        )
        category = ItemCategory.objects.create(category_name="Access Furniture")
        kind = ItemType.objects.create(category=category, item_type_name="Access Desk")
        cls.active, cls.draft = [Listing.objects.create(
            seller=cls.other, item_type=kind, title=title, listing_price=20,
            condition="GOOD", fulfillment_option="PICKUP", status=status,
        ) for title, status in (("Public Desk", "ACTIVE"), ("Other Draft", "DRAFT"))]

    def test_browse_details_and_listing_api_remain_public_and_clean(self):
        for route in ("home", "listing-list-url", "listing-api-demo"):
            self.assertEqual(self.client.get(reverse(route)).status_code, 200)
        self.assertEqual(self.client.get(self.active.get_absolute_url()).status_code, 200)
        response = self.client.get(reverse("listing-api"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual([row["id"] for row in response.json()["results"]], [self.active.pk])
        self.assertEqual(set(response.json()["results"][0]), {
            "id", "listing_id", "title", "price", "condition", "category", "url",
        })

    def test_private_json_returns_401_or_403_before_business_logic(self):
        routes = (
            "listing-currency-api", "listing-export-json",
            "profile-earned-spent-data", "profile-earned-spent-timeline-data",
            "profile-listing-inquiry-data", "vega-earned-spent-spec",
            "vega-earned-spent-timeline-spec", "vega-listing-inquiries-spec",
            "messaging_conversations",
        )
        with patch("marketplace.api.requests.get") as exchange:
            for user, status, code in (
                (None, 401, "login_required"),
                (self.unverified, 403, "campus_access_required"),
            ):
                if user:
                    self.client.force_login(user)
                for route in routes:
                    with self.subTest(route=route, user=user):
                        response = self.client.get(reverse(route))
                        self.assertEqual(response.status_code, status)
                        self.assertEqual(response.json()["code"], code)
                upload = self.client.post(reverse("listing_image_upload"), {
                    "url": "https://example.invalid/access.png",
                })
                self.assertEqual(upload.status_code, status)
                self.assertEqual(upload.json()["code"], code)
            exchange.assert_not_called()

    def test_private_pages_redirect_and_verified_users_keep_features(self):
        routes = ("a4-charts", "listing-report", "listing-export-csv",
                  "messages", "listing-create-url", "seller-listings")
        for route in routes:
            response = self.client.get(reverse(route))
            self.assertEqual(response.status_code, 302, route)
            self.assertTrue(response["Location"].startswith("/account/?next="))
        self.client.force_login(self.student)
        for route in routes:
            self.assertEqual(self.client.get(reverse(route)).status_code, 200, route)
        self.assertEqual(self.client.get(reverse("listing-currency-api")).status_code, 200)
        self.assertEqual(self.client.get(reverse("listing-export-json")).status_code, 200)

    def test_protected_navigation_and_currency_are_hidden_until_campus_access(self):
        protected_urls = [reverse(route) for route in (
            "listing-create-url", "messages", "seller-listings", "a4-charts", "listing-report",
        )] + [reverse("bundles:select_space")]
        for user in (None, self.unverified, self.student):
            if user:
                self.client.force_login(user)
            response = self.client.get(reverse("home"))
            for url in protected_urls:
                assertion = self.assertContains if user == self.student else self.assertNotContains
                assertion(response, f'href="{url}"')
            assertion(response, "data-currency-api=")
            assertion(response, "data-currency-select")
        self.client.logout()
        self.assertContains(self.client.get(reverse("home")), 'href="/account/"')
        self.assertNotContains(self.client.get(self.active.get_absolute_url()), "Message Seller")

    @override_settings(A4_ASSIGNMENT_MODE=True)
    def test_obsolete_mode_cannot_disable_accounts_or_expose_private_features(self):
        self.assertEqual(self.client.get(reverse("account")).status_code, 200)
        self.assertEqual(self.client.get(reverse("account"), {"mode": "signup"}).status_code, 200)
        self.assertEqual(self.client.get(reverse("a4-charts")).status_code, 302)
        self.assertEqual(self.client.get(reverse("profile-earned-spent-data")).status_code, 401)

    def test_old_render_tokens_do_not_authorize_anonymous_chart_requests(self):
        token = signing.dumps({"user_id": self.student.pk}, salt="profile-chart-render")
        response = self.client.get(reverse("profile-earned-spent-data"), {"render_token": token})
        self.assertEqual(response.status_code, 401)

    def test_other_students_cannot_edit_preview_or_publish_another_sellers_listing(self):
        self.client.force_login(self.student)
        for route in ("listing-update-url", "listing-preview-url"):
            self.assertEqual(self.client.get(reverse(route, args=[self.draft.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse("listing-publish-url", args=[self.draft.pk])).status_code, 404)
        self.draft.refresh_from_db()
        self.assertEqual(self.draft.status, Listing.Status.DRAFT)

    def test_revoked_or_suspended_sessions_lose_private_json_access(self):
        self.client.force_login(self.student)
        for changes, expected in (({"email_verified_at": None}, 403), ({"account_status": "SUSPENDED"}, 401)):
            state = {"email_verified_at": timezone.now(), "account_status": "ACTIVE", **changes}
            User.objects.filter(pk=self.student.pk).update(**state)
            self.assertEqual(self.client.get(reverse("profile-earned-spent-data")).status_code, expected)
            self.assertNotContains(self.client.get(reverse("home")), 'href="/charts/"')
