from io import BytesIO
from io import StringIO
import json
from decimal import Decimal
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import Client, LiveServerTestCase, TestCase
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from marketplace.auth_backend import has_campus_access
from bundles.models import Bundle, BundleItem
from messaging.models import Conversation, Message
from marketplace.charts import listing_inquiry_data
from marketplace.models import ItemCategory, ItemType, Listing, ListingImage, Transaction, User
from marketplace.validation import validate_image_reference


class Assignment3Tests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.buyer, cls.seller, cls.other = [User.objects.create_user(
            username=name, email=f"{name}@illinois.edu", display_name=name,
            email_verified=True, email_verified_at=timezone.now(),
        ) for name in ("a3buyer", "a3seller", "a3other")]
        cls.category = ItemCategory.objects.create(category_name="A3 Furniture")
        cls.kind = ItemType.objects.create(category=cls.category, item_type_name="A3 Desk")
        cls.items = [Listing.objects.create(
            seller=cls.seller, item_type=cls.kind, title=title, listing_price=price,
            condition="GOOD", fulfillment_option="PICKUP", status=status,
        ) for title, price, status in [("Oak Desk", 40, "ACTIVE"),
                                       ("Reading Lamp", 20, "ACTIVE"),
                                       ("Blue Rug", 30, "ACTIVE"),
                                       ("Private Draft", 15, "DRAFT")]]
        cls.purchase = Transaction.objects.create(
            listing=cls.items[0], buyer=cls.buyer, seller=cls.seller,
            agreed_price=40, status="COMPLETED", completed_at=timezone.now(),
        )
        Transaction.objects.create(listing=cls.items[1], buyer=cls.other, seller=cls.seller,
                                   agreed_price=20, status="COMPLETED", completed_at=timezone.now())

    def test_public_api_matches_browse_filters_and_hides_private_fields(self):
        filters = {"q": "oak", "category": self.category.pk, "min_price": 30}
        api = self.client.get(reverse("listing-api"), filters)
        html = self.client.get(reverse("home"), filters)
        self.assertEqual(api.status_code, 200)
        self.assertEqual(api["Content-Type"], "application/json")
        self.assertTrue(html["Content-Type"].startswith("text/html"))
        self.assertEqual([row["id"] for row in api.json()["results"]],
                         [row.pk for row in html.context["listings"]])
        row = api.json()["results"][0]
        self.assertEqual(set(row), {"id", "listing_id", "title", "price", "condition", "category", "url"})
        self.assertEqual(row["category"]["id"], self.category.pk)
        self.assertNotContains(self.client.get(reverse("listing-api")), "Private Draft")

    def test_api_validation_empty_and_read_only(self):
        for filters in ({"category": "invalid"}, {"page": "bad"}, {"page": "0"},
                        {"min_price": 100, "max_price": 5}):
            self.assertEqual(self.client.get(reverse("listing-api"), filters).status_code, 400)
        self.assertEqual(self.client.get(reverse("listing-api"), {"page": 999}).status_code, 404)
        empty = self.client.get(reverse("listing-api"), {"q": "no match at all"}).json()
        self.assertEqual((empty["count"], empty["results"]), (0, []))
        self.assertEqual(self.client.post(reverse("listing-api")).status_code, 405)
        self.assertEqual(self.client.get(reverse("messaging_conversations")).status_code, 401)

    def test_api_pagination_has_stable_bounded_results(self):
        for number in range(22):
            Listing.objects.create(seller=self.seller, item_type=self.kind,
                                   title=f"Extra {number}", listing_price=10, condition="GOOD",
                                   fulfillment_option="PICKUP", status="ACTIVE")
        first = self.client.get(reverse("listing-api")).json()
        second = self.client.get(reverse("listing-api"), {"page": 2}).json()
        self.assertEqual(first["count"], 25)
        self.assertEqual(len(first["results"]), 20)
        self.assertEqual(len(second["results"]), 5)
        self.assertFalse({row["id"] for row in first["results"]} & {row["id"] for row in second["results"]})

    def test_post_search_scoped_validated_and_does_not_write(self):
        self.client.force_login(self.buyer)
        url = reverse("buyer-purchase-history")
        before = Transaction.objects.count()
        response = self.client.post(url, {"q": "Oak"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.wsgi_request.GET.dict(), {})
        self.assertEqual([row["transaction"].pk for row in response.context["history_rows"]], [self.purchase.pk])
        self.assertFalse(self.client.post(url, {"q": "Lamp"}).context["history_rows"])
        self.assertFalse(self.client.post(url, {"q": "x" * 201}).context["history_search_form"].is_valid())
        self.assertEqual(Transaction.objects.count(), before)
        self.assertEqual(len(self.client.get(url).context["history_rows"]), 1)

    def test_post_search_csrf_and_access(self):
        url = reverse("buyer-purchase-history")
        self.assertEqual(self.client.get(url).status_code, 302)
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.buyer)
        page = client.get(url)
        self.assertContains(page, "csrfmiddlewaretoken")
        self.assertEqual(client.post(url, {"q": "Oak"}).status_code, 403)
        token = client.cookies["csrftoken"].value
        self.assertEqual(client.post(url, {"q": "Oak", "csrfmiddlewaretoken": token}).status_code, 200)

    def test_chart_counts_conversations_not_messages_and_scopes_seller(self):
        conversation = Conversation.objects.create(buyer=self.buyer, seller=self.seller, listing=self.items[0])
        for text in ("First question", "Second question"):
            Message.objects.create(conversation=conversation, sender=self.buyer, body_text=text)
        rows = listing_inquiry_data(self.seller)
        self.assertEqual([(r["title"], r["total"], r["unanswered"]) for r in rows], [("Oak Desk", 1, 1)])
        self.assertEqual(listing_inquiry_data(self.other), [])
        Message.objects.filter(conversation=conversation).update(is_read=True)
        self.assertEqual(listing_inquiry_data(self.seller)[0]["answered"], 1)

    def test_vega_profile_chart_specs_use_private_url_backed_json(self):
        data_endpoints = (
            "profile-earned-spent-data",
            "profile-earned-spent-timeline-data",
            "profile-listing-inquiry-data",
        )
        for name in data_endpoints:
            self.assertEqual(self.client.get(reverse(name)).status_code, 403)

        spec_endpoints = (
            "vega-earned-spent-spec",
            "vega-earned-spent-timeline-spec",
            "vega-listing-inquiries-spec",
        )
        for name in spec_endpoints:
            self.assertEqual(self.client.get(reverse(name)).status_code, 302)

        Conversation.objects.create(
            buyer=self.buyer, seller=self.seller, listing=self.items[0]
        )
        self.client.force_login(self.seller)

        financial_data = self.client.get(reverse("profile-earned-spent-data"))
        self.assertEqual(financial_data["Content-Type"], "application/json")
        self.assertEqual(financial_data.json(), [
            {"activity": "Total Spent", "amount": 0.0},
            {"activity": "Total Earned", "amount": 60.0},
        ])

        inquiry_data = self.client.get(reverse("profile-listing-inquiry-data"))
        self.assertEqual(inquiry_data["Content-Type"], "application/json")
        self.assertEqual(inquiry_data.json()[0]["title"], "Oak Desk")

        timeline_data = self.client.get(reverse("profile-earned-spent-timeline-data"))
        self.assertEqual(timeline_data["Content-Type"], "application/json")
        self.assertEqual(
            {row["activity"] for row in timeline_data.json()},
            {"Total Spent", "Total Earned"},
        )
        timeline_totals = {
            row["activity"]: row["amount"] for row in timeline_data.json()
        }
        self.assertEqual(timeline_totals["Total Earned"], 60.0)
        self.assertEqual(timeline_totals["Total Spent"], 0.0)

        financial_spec = self.client.get(reverse("vega-earned-spent-spec")).json()
        timeline_spec = self.client.get(
            reverse("vega-earned-spent-timeline-spec")
        ).json()
        inquiry_spec = self.client.get(reverse("vega-listing-inquiries-spec")).json()
        self.assertEqual(financial_spec["mark"]["type"], "bar")
        self.assertEqual(timeline_spec["mark"]["type"], "line")
        self.assertEqual(inquiry_spec["mark"]["type"], "bar")
        self.assertEqual(inquiry_spec["transform"][0]["fold"], ["answered", "unanswered"])
        self.assertEqual(inquiry_spec["encoding"]["color"]["scale"]["range"], ["#4d8069", "#c75b5b"])
        self.assertEqual(financial_spec["encoding"]["x"]["axis"]["tickMinStep"], 10)
        for spec in (financial_spec, timeline_spec, inquiry_spec):
            self.assertNotIn("values", spec["data"])
        self.assertEqual(timeline_spec["encoding"]["color"]["field"], "activity")
        self.assertIsNotNone(timeline_spec["encoding"]["color"]["legend"])
        for spec in (financial_spec, inquiry_spec):
            self.assertFalse(spec["encoding"]["x"]["axis"]["grid"])
            self.assertFalse(spec["encoding"]["y"]["axis"]["grid"])
        self.assertNotIn("values", financial_spec["data"])
        self.assertNotIn("values", inquiry_spec["data"])
        self.assertTrue(financial_spec["data"]["url"].endswith(
            reverse("profile-earned-spent-data")
        ))
        self.assertTrue(inquiry_spec["data"]["url"].endswith(
            reverse("profile-listing-inquiry-data")
        ))

        page = self.client.get(reverse("seller-listings"))
        self.assertContains(page, 'data-vega-spec="/vega-lite/earned-spent.json"')
        self.assertContains(page, 'data-vega-spec="/vega-lite/earned-spent-timeline.json"')
        self.assertContains(page, 'data-vega-spec="/vega-lite/listing-inquiries.json"')

    def test_png_endpoints_render_from_private_chart_api_data(self):
        png_endpoints = (
            "vega-earned-spent-png",
            "vega-earned-spent-timeline-png",
            "vega-listing-inquiries-png",
        )
        for endpoint in png_endpoints:
            self.assertEqual(self.client.get(reverse(endpoint)).status_code, 302)

        Conversation.objects.create(
            buyer=self.buyer, seller=self.seller, listing=self.items[0]
        )
        self.client.force_login(self.seller)
        data_routes = (
            "profile-earned-spent-data",
            "profile-earned-spent-timeline-data",
            "profile-listing-inquiry-data",
        )
        for endpoint, data_route in zip(png_endpoints, data_routes):
            with patch(
                "marketplace.charts.subprocess.run",
                return_value=SimpleNamespace(stdout=b"\x89PNG\r\n\x1a\nchart"),
            ) as renderer:
                response = self.client.get(reverse(endpoint))
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response["Content-Type"], "image/png")
            self.assertTrue(response.content.startswith(b"\x89PNG\r\n\x1a\n"))
            spec = json.loads(renderer.call_args.kwargs["input"].decode("utf-8"))
            self.assertIn("url", spec["data"])
            self.assertNotIn("values", spec["data"])
            data_url = urlsplit(spec["data"]["url"])
            self.assertTrue(data_url.path.endswith(reverse(data_route)))
            token = parse_qs(data_url.query)["render_token"][0]
            data_response = Client().get(
                f"{reverse(data_route)}?render_token={token}"
            )
            self.assertEqual(data_response.status_code, 200)
            self.assertEqual(data_response["Content-Type"], "application/json")

    def test_seeded_maya_profile_inquiries_and_spending_are_model_backed(self):
        call_command("seed_demo_data", stdout=StringIO(), verbosity=0)
        call_command("seed_bundle_inventory", stdout=StringIO(), verbosity=0)
        maya = User.objects.get(username="maya")

        inquiries = listing_inquiry_data(maya)
        self.assertEqual(len(inquiries), 6)
        self.assertEqual(sum(row["answered"] for row in inquiries), 4)
        self.assertEqual(sum(row["unanswered"] for row in inquiries), 3)
        gray_rug = next(row for row in inquiries if row["title"] == "Gray Rug")
        self.assertEqual(
            (gray_rug["total"], gray_rug["answered"], gray_rug["unanswered"]),
            (2, 1, 1),
        )
        gray_rug_conversations = Conversation.objects.filter(
            seller=maya, listing__title="Gray Rug"
        )
        self.assertEqual(gray_rug_conversations.count(), 2)
        self.assertTrue(gray_rug_conversations.filter(messages__sender=maya).exists())
        self.assertTrue(gray_rug_conversations.filter(
            buyer__username="sam",
            messages__sender__username="sam",
            messages__is_read=False,
        ).exists())
        self.assertTrue(all(
            Conversation.objects.filter(
                seller=maya,
                listing__title=row["title"],
                messages__sender=maya,
            ).exists()
            for row in inquiries
            if row["answered"]
        ))

        purchases = list(
            Transaction.objects.filter(buyer=maya).select_related("listing", "seller")
        )
        self.assertEqual(len(purchases), 3)
        self.assertEqual(
            sum((purchase.agreed_price for purchase in purchases), Decimal("0")),
            Decimal("113.00"),
        )
        for purchase in purchases:
            purchase.full_clean()
            self.assertEqual(purchase.seller_id, purchase.listing.seller_id)

        conversation_count = Conversation.objects.filter(seller=maya).count()
        call_command("seed_bundle_inventory", stdout=StringIO(), verbosity=0)
        self.assertEqual(Conversation.objects.filter(seller=maya).count(), conversation_count)
        self.assertEqual(Transaction.objects.filter(buyer=maya).count(), 3)

        self.client.force_login(maya)
        self.assertTrue(maya.email_verified)
        self.assertIsNotNone(maya.email_verified_at)
        self.assertTrue(maya.email.endswith("@illinois.edu"))
        self.assertTrue(has_campus_access(maya))
        self.assertEqual(self.client.session.get("_auth_user_id"), str(maya.pk))
        spent_response = self.client.get(reverse("profile-earned-spent-data"))
        self.assertTrue(spent_response.wsgi_request.user.is_authenticated)
        self.assertEqual(spent_response.status_code, 200, spent_response.get("Location"))
        spent_data = spent_response.json()
        self.assertEqual(
            {row["activity"]: row["amount"] for row in spent_data}["Total Spent"],
            113.0,
        )
        timeline = self.client.get(
            reverse("profile-earned-spent-timeline-data")
        ).json()
        timeline_totals = {row["activity"]: row["amount"] for row in timeline}
        self.assertEqual(timeline_totals["Total Spent"], 113.0)
        self.assertEqual(timeline_totals["Total Earned"], 18.0)


    def test_uploaded_image_bundle_checkout_and_retry(self):
        ListingImage.objects.create(listing=self.items[2], uploaded_by=self.seller,
                                    image="listing_images/example.png")
        bundle = Bundle.objects.create(buyer=self.buyer, space="LIVING_ROOM")
        for listing in self.items[:3]:
            BundleItem.objects.create(bundle=bundle, listing=listing,
                                      listing_price_snapshot=listing.listing_price)
        self.client.force_login(self.buyer)
        url = reverse("bundle_send_requests", args=[bundle.pk])
        first = self.client.post(url)
        self.assertEqual(first.status_code, 200, first.content)
        self.assertEqual(Conversation.objects.get(listing=self.items[2]).listing_image_snapshot,
                         "/media/listing_images/example.png")
        self.assertEqual(self.client.post(url).status_code, 200)
        self.assertEqual(Message.objects.count(), 3)
        self.client.force_login(self.other)
        self.assertEqual(self.client.post(url).status_code, 404)

    def test_image_reference_rejects_unsafe_schemes(self):
        for value in ("/media/photo.png", "https://example.com/photo.png"):
            validate_image_reference(value)
        for value in ("javascript:alert(1)", "file:///tmp/photo.png", "//example.com/photo.png", "/\\example.com/photo.png"):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                validate_image_reference(value)


class VegaPngLiveServerTests(LiveServerTestCase):
    def setUp(self):
        now = timezone.now()
        self.seller = User.objects.create_user(
            username="png-seller",
            email="png-seller@illinois.edu",
            display_name="PNG Seller",
            email_verified=True,
            email_verified_at=now,
        )
        category = ItemCategory.objects.create(category_name="PNG Furniture")
        item_type = ItemType.objects.create(
            category=category, item_type_name="PNG Desk"
        )
        Listing.objects.create(
            seller=self.seller,
            item_type=item_type,
            title="PNG test listing",
            listing_price=20,
            condition=Listing.Condition.GOOD,
            fulfillment_option=Listing.Fulfillment.PICKUP,
            status=Listing.Status.ACTIVE,
        )
        self.client.force_login(self.seller)
        self.http_host = urlsplit(self.live_server_url).netloc

    def test_png_exports_fetch_signed_data_from_local_api(self):
        endpoints = (
            "vega-earned-spent-png",
            "vega-earned-spent-timeline-png",
            "vega-listing-inquiries-png",
        )
        for endpoint in endpoints:
            response = self.client.get(
                reverse(endpoint), HTTP_HOST=self.http_host
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response["Content-Type"], "image/png")
            with Image.open(BytesIO(response.content)) as image:
                self.assertEqual(image.format, "PNG")
                image.verify()
