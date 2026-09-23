from decimal import Decimal
from io import StringIO
from django.core.management import call_command
from django.test import TestCase, SimpleTestCase
from django.urls import reverse
from messaging.models import Conversation
from .featured import discount_percent, featured_bundles, DEMO_USERNAME
from .models import Listing, User


class DiscountTests(SimpleTestCase):
    def test_discount_edge_cases(self):
        self.assertIsNone(discount_percent(None, Decimal("10")))
        self.assertIsNone(discount_percent(Decimal("0"), Decimal("0")))
        self.assertIsNone(discount_percent(Decimal("10"), Decimal("12")))
        self.assertEqual(
            discount_percent(Decimal("100"), Decimal("0")), Decimal("100.0")
        )
        self.assertEqual(
            discount_percent(Decimal("140"), Decimal("95")), Decimal("32.1")
        )


class FeaturedTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_featured_bundles", stdout=StringIO())

    def test_three_items_per_scene_and_totals_match_database(self):
        scenes = featured_bundles()
        self.assertEqual(len(scenes), 2)
        living = scenes[0]
        self.assertEqual(len(living["items"]), 3)
        self.assertEqual(living["total"], Decimal("147"))
        self.assertEqual(living["saved"], Decimal("66"))
        self.assertEqual(living["discount"], Decimal("31.0"))
        self.assertEqual(scenes[1]["total"], Decimal("127"))
        self.assertEqual(scenes[1]["saved"], Decimal("65"))

    def test_seed_covers_delivery_and_both_fulfillment(self):
        self.assertEqual(
            Listing.objects.get(title="Coffee Table").fulfillment_option,
            Listing.Fulfillment.DELIVERY,
        )
        self.assertEqual(
            Listing.objects.get(title="Rocking Chair").fulfillment_option,
            Listing.Fulfillment.BOTH,
        )

    def test_price_edits_are_reflected_in_scene_and_listing(self):
        item = Listing.objects.get(title="Rocking Chair")
        item.listing_price = Decimal("90")
        item.save()
        response = self.client.get(reverse("home"))
        self.assertEqual(
            response.context["featured_bundles"][0]["total"], Decimal("142")
        )
        self.assertContains(response, "$90.00")

    def test_unavailable_item_removes_incomplete_bundle(self):
        item = Listing.objects.get(title="Rocking Chair")
        item.status = Listing.Status.SOLD
        item.save()
        self.assertEqual(len(featured_bundles()), 1)

    def test_seed_is_idempotent_and_preserves_user_edits(self):
        item = Listing.objects.get(title="Rocking Chair")
        item.listing_price = Decimal("88")
        item.save()
        call_command("seed_featured_bundles", stdout=StringIO())
        item.refresh_from_db()
        self.assertEqual(item.listing_price, Decimal("88"))
        self.assertEqual(
            Listing.objects.filter(seller__username=DEMO_USERNAME).count(), 6
        )

    def test_popular_uses_inquiries_instead_of_alphabetical_order(self):
        chair = Listing.objects.get(title="Rocking Chair")
        buyer = User.objects.create_user(username="buyer", email="buyer@example.com")
        Conversation.objects.create(listing=chair, seller=chair.seller, buyer=buyer)
        response = self.client.get(reverse("home"), {"sort": "popular"})
        self.assertEqual(response.context["listings"][0].pk, chair.pk)

    def test_scene_listing_links_and_ui_options(self):
        response = self.client.get(reverse("home"))
        self.assertContains(response, "Browse Listings")
        self.assertContains(response, "Select at least three items")
        self.assertContains(response, "Bundle price")
        self.assertContains(response, "Overall discount")
        self.assertContains(response, "data-hotspot", count=6)
        self.assertNotContains(response, 'value="EITHER"')
        self.assertNotContains(response, "Name: A to Z")
        for item in response.context["listings"]:
            self.assertContains(response, f'id="listing-{item.pk}"')
            self.assertTrue(item.display_image_url.startswith("/static/"))
