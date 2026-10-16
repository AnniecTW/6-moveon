"""The profile's visible navigation and Vega links resolve for a campus user."""

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from marketplace.models import User


class ProfileLinkTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="profile-links", email="profile-links@illinois.edu",
            password="Campus-password-2026", display_name="Profile Links",
            email_verified=True, email_verified_at=timezone.now(),
        )
        self.client.force_login(self.user)

    def test_profile_navigation_and_chart_links(self):
        pages = (
            "seller-listings", "seller-settings", "buyer-pickups",
            "buyer-bundles", "buyer-purchase-history", "buyer-watchlist",
        )
        for name in pages:
            with self.subTest(name=name):
                response = self.client.get(reverse(name))
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, f'href="{reverse("seller-settings")}" data-dashboard-route')
                self.assertContains(response, reverse("a4-charts"))
        self.assertEqual(self.client.get(reverse("a4-charts")).status_code, 200)
        for name in (
            "vega-earned-spent-spec", "vega-earned-spent-timeline-spec",
            "vega-listing-inquiries-spec", "profile-earned-spent-data",
            "profile-earned-spent-timeline-data", "profile-listing-inquiry-data",
        ):
            with self.subTest(name=name):
                self.assertEqual(self.client.get(reverse(name)).status_code, 200)
        self.assertEqual(
            self.client.get(reverse("listing-inquiry-chart")).get("Content-Type"),
            "image/png",
        )

    def test_dashboard_tab_request_returns_chart_targets(self):
        response = self.client.get(
            reverse("buyer-pickups"), HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertContains(response, 'data-vega-spec="/vega-lite/earned-spent.json"')
        self.assertContains(response, 'data-vega-spec="/vega-lite/listing-inquiries.json"')
