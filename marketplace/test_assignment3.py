from io import BytesIO

from django.core.exceptions import ValidationError
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from bundles.models import Bundle, BundleItem
from messaging.models import Conversation, Message
from .charts import listing_inquiry_data
from .models import ItemCategory, ItemType, Listing, ListingImage, Transaction, User
from .validation import validate_image_reference


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

    def test_png_endpoint_real_image_empty_populated_and_private(self):
        url = reverse("listing-inquiry-chart")
        self.assertEqual(self.client.get(url).status_code, 302)
        self.client.force_login(self.seller)
        for populated in (False, True):
            if populated:
                Conversation.objects.create(buyer=self.buyer, seller=self.seller, listing=self.items[0])
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response["Content-Type"], "image/png")
            self.assertIn("no-store", response["Cache-Control"])
            self.assertTrue(response.content.startswith(b"\x89PNG\r\n\x1a\n"))
            with Image.open(BytesIO(response.content)) as image:
                self.assertEqual(image.format, "PNG")
                self.assertEqual(image.width, 1200)
                image.verify()
        page = self.client.get(reverse("seller-listings"))
        self.assertContains(page, f'src="{url}"')

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
