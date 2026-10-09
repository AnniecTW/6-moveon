"""Private charts relay authorized data without another website worker."""

import json
from hashlib import sha256
from io import BytesIO
from unittest.mock import patch

from django.http import HttpResponse, JsonResponse
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from marketplace.charts import _render_png
from marketplace.models import ItemCategory, ItemType, Listing, Transaction, User
from messaging.models import Conversation


class A5PrivateChartTests(TestCase):
    endpoints = (
        ("vega-earned-spent-png", "profile-earned-spent-data"),
        ("vega-earned-spent-timeline-png", "profile-earned-spent-timeline-data"),
        ("vega-listing-inquiries-png", "profile-listing-inquiry-data"),
    )

    @classmethod
    def setUpTestData(cls):
        cls.owner, cls.other, cls.buyer = [User.objects.create_user(
            username=name, email=f"{name}@illinois.edu", display_name=name,
            email_verified=True, email_verified_at=timezone.now(),
        ) for name in ("chart-owner", "chart-other", "chart-buyer")]
        cls.unverified = User.objects.create_user(
            username="chart-unverified", email="chart-unverified@illinois.edu",
        )
        category = ItemCategory.objects.create(category_name="Private Chart Furniture")
        kind = ItemType.objects.create(category=category, item_type_name="Chart Chair")
        cls.sales = []
        for seller, price, title in ((cls.owner, 18, "Owner Sale"), (cls.other, 80, "Other Sale")):
            listing = Listing.objects.create(
                seller=seller, item_type=kind, title=title, listing_price=price,
                condition="GOOD", fulfillment_option="PICKUP", status="ACTIVE",
            )
            cls.sales.append(Transaction.objects.create(
                listing=listing, seller=seller, buyer=cls.buyer, agreed_price=price,
                status="COMPLETED", completed_at=timezone.now(),
            ))
            Conversation.objects.create(seller=seller, buyer=cls.buyer, listing=listing)

    def test_no_private_png_renders_before_campus_authorization(self):
        with patch("marketplace.charts._render_spec_png") as renderer:
            for user in (None, self.unverified):
                if user:
                    self.client.force_login(user)
                for png, _ in self.endpoints:
                    self.assertEqual(self.client.get(reverse(png)).status_code, 302)
            renderer.assert_not_called()

    def test_each_snapshot_contains_only_current_user_data(self):
        snapshots = []
        for user in (self.owner, self.other):
            self.client.force_login(user)
            for png, data_route in self.endpoints:
                expected = self.client.get(reverse(data_route)).json()
                earned = 18.0 if user == self.owner else 80.0
                if data_route == "profile-earned-spent-data":
                    self.assertEqual(expected, [
                        {"activity": "Total Spent", "amount": 0.0},
                        {"activity": "Total Earned", "amount": earned},
                    ])
                elif data_route == "profile-earned-spent-timeline-data":
                    self.assertEqual(expected[-1]["amount"], earned)
                    self.assertEqual(expected[-1]["activity"], "Total Earned")
                else:
                    title = "Owner Sale" if user == self.owner else "Other Sale"
                    self.assertEqual([(row["title"], row["total"]) for row in expected], [(title, 1)])

                def inspect_snapshot(spec, payload, data_path, expected=expected, data_route=data_route):
                    self.assertEqual(data_path, reverse(data_route))
                    self.assertEqual(json.loads(payload), expected)
                    self.assertNotIn("values", spec["data"])
                    snapshots.append(payload)
                    return HttpResponse(b"png", content_type="image/png")

                with patch("marketplace.charts._render_spec_png", side_effect=inspect_snapshot):
                    response = self.client.get(reverse(png), {"user_id": self.buyer.pk})
                self.assertEqual(response.status_code, 200)
        self.assertEqual(len(snapshots), 6)

    def test_renderer_failure_returns_the_controlled_response(self):
        self.client.force_login(self.owner)
        def fail_render(spec, payload, data_path):
            return JsonResponse({"error": "Chart rendering failed."}, status=502)

        with patch("marketplace.charts._render_spec_png", side_effect=fail_render):
            response = self.client.get(reverse("vega-earned-spent-png"))
        self.assertEqual(response.status_code, 502)

    def test_failed_spec_or_data_response_is_returned_without_rendering(self):
        self.client.force_login(self.owner)
        request = self.client.get(reverse("profile-earned-spent-data")).wsgi_request
        with patch("marketplace.charts._render_spec_png") as renderer:
            denied = JsonResponse({"error": "Denied"}, status=403)
            response = _render_png(request, lambda request: denied, "profile-earned-spent-data")
            self.assertEqual(response.status_code, 403)
            with patch("marketplace.charts.resolve") as resolver:
                resolver.return_value.func.return_value = denied
                valid = lambda request: JsonResponse({"data": {"url": "unused"}})
                self.assertEqual(_render_png(request, valid, "profile-earned-spent-data").status_code, 403)
            renderer.assert_not_called()

    def test_three_real_pngs_render_owner_data_without_a_website_server_under_uwsgi(self):
        self.client.force_login(self.owner)
        with patch("marketplace.charts.sys.executable", "/usr/local/bin/uwsgi"):
            for png, _ in self.endpoints:
                with self.subTest(png=png):
                    # Django's HTTP client has no live website worker listening.
                    response = self.client.get(reverse(png))
                    self.assertEqual(response.status_code, 200, response.content)
                    self.assertEqual(response["Content-Type"], "image/png")
                    self.assertIn("no-store", response["Cache-Control"])
                    with Image.open(BytesIO(response.content)) as image:
                        self.assertEqual(image.format, "PNG")
                        self.assertGreater(image.width, 100)
                        self.assertGreater(image.height, 100)
                        image.verify()

    def test_real_png_does_not_start_a_relay_server_or_thread_in_django(self):
        self.client.force_login(self.owner)
        with patch("marketplace.charts.ThreadingHTTPServer", create=True) as server, \
                patch("marketplace.charts.Thread", create=True) as thread, \
                patch("marketplace.png_renderer.HTTPServer") as helper_server, \
                patch("marketplace.png_renderer.Thread") as helper_thread:
            server.side_effect = AssertionError("Django started a relay server")
            thread.side_effect = AssertionError("Django started a relay thread")
            helper_server.side_effect = AssertionError("Django started a helper relay server")
            helper_thread.side_effect = AssertionError("Django started a helper relay thread")
            response = self.client.get(reverse("vega-earned-spent-png"))
        self.assertEqual(response.status_code, 200, response.content)
        server.assert_not_called()
        thread.assert_not_called()
        helper_server.assert_not_called()
        helper_thread.assert_not_called()
        with Image.open(BytesIO(response.content)) as image:
            image.verify()

    def test_private_png_changes_only_when_current_user_activity_changes(self):
        self.client.force_login(self.owner)
        url = reverse("vega-earned-spent-png")
        before = self.client.get(url)
        self.assertEqual(before.status_code, 200)
        Transaction.objects.filter(pk=self.sales[1].pk).update(agreed_price=800)
        other_changed = self.client.get(url)
        self.assertEqual(other_changed.status_code, 200)
        self.assertEqual(sha256(before.content).digest(), sha256(other_changed.content).digest())
        Transaction.objects.filter(pk=self.sales[0].pk).update(agreed_price=180)
        owner_changed = self.client.get(url)
        self.assertEqual(owner_changed.status_code, 200)
        self.assertNotEqual(sha256(before.content).digest(), sha256(owner_changed.content).digest())

    def test_three_real_pngs_render_when_current_user_has_no_activity_or_listings(self):
        empty = User.objects.create_user(
            username="chart-empty", email="chart-empty@illinois.edu",
            display_name="Empty", email_verified=True,
            email_verified_at=timezone.now(),
        )
        self.client.force_login(empty)
        for png, data_route in self.endpoints:
            data = self.client.get(reverse(data_route)).json()
            if data_route == "profile-earned-spent-data":
                self.assertEqual([row["amount"] for row in data], [0.0, 0.0])
            else:
                self.assertEqual(data, [])
            response = self.client.get(reverse(png))
            self.assertEqual(response.status_code, 200, response.content)
            with Image.open(BytesIO(response.content)) as image:
                self.assertEqual(image.format, "PNG")
                image.verify()
