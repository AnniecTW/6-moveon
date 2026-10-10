from io import StringIO
from decimal import Decimal

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db.models import Sum
from django.test import TestCase, tag
from django.urls import reverse

from marketplace.models import EmailVerification, ItemCategory, ItemType, Listing, Transaction, User


class PublicListingsApiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.demo = User.objects.create_user(
            username="maya", email="maya@example.invalid", display_name="Maya"
        )
        category = ItemCategory.objects.create(category_name="Demo Furniture")
        cls.kind = ItemType.objects.create(category=category, item_type_name="Chair")

    @tag("a4")
    def test_public_listings_api_is_readable_by_the_vega_editor(self):
        Listing.objects.create(
            seller=self.demo, item_type=self.kind, title="Public chair", listing_price="12.50",
            condition="GOOD", fulfillment_option="PICKUP", status="ACTIVE",
        )
        response = self.client.get(reverse("listing-api"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/json")
        self.assertEqual(response["Access-Control-Allow-Origin"], "*")
        row = response.json()["results"][0]
        self.assertEqual(row["price"], "12.50")
        self.assertEqual(row["category"]["name"], "Demo Furniture")
        self.assertNotIn("email", str(response.json()))
        # Protected messaging API stays closed and sends no CORS header.
        protected = self.client.get("/api/messaging/conversations/")
        self.assertIn(protected.status_code, (401, 403))
        self.assertNotIn("Access-Control-Allow-Origin", protected)


@tag("a4")
class A4SeedTests(TestCase):
    def test_seed_refuses_to_modify_a_database_with_non_demo_accounts(self):
        user = User.objects.create_user(username="existing", email="existing@illinois.edu")
        with self.assertRaises(CommandError):
            call_command("seed_a4_data", stdout=StringIO())
        user.refresh_from_db()
        self.assertEqual(user.email, "existing@illinois.edu")
        self.assertEqual(User.objects.count(), 1)
        self.assertEqual(Listing.objects.count(), 0)

    def test_seed_is_repeatable_and_contains_only_nonlogin_demo_identities(self):
        call_command("seed_a4_data", stdout=StringIO())
        counts = (User.objects.count(), Listing.objects.count(), Transaction.objects.count())
        self.assertGreaterEqual(counts[1], 8)
        self.assertGreaterEqual(counts[2], 4)
        self.assertTrue(all(user.email.endswith("@example.invalid") and
                            not user.has_usable_password() and
                            not user.is_staff and not user.is_superuser and
                            not user.email_verified and not user.google_subject
                            for user in User.objects.all()))
        self.assertEqual(EmailVerification.objects.count(), 0)
        call_command("seed_a4_data", stdout=StringIO())
        self.assertEqual(counts, (User.objects.count(), Listing.objects.count(),
                                  Transaction.objects.count()))
        maya = User.objects.get(username="maya")
        self.assertEqual(Transaction.objects.filter(buyer=maya).exclude(
            status=Transaction.Status.CANCELLED,
        ).aggregate(total=Sum("agreed_price"))["total"], Decimal("113"))
        self.assertEqual(Transaction.objects.filter(
            seller=maya, status=Transaction.Status.COMPLETED,
        ).aggregate(total=Sum("agreed_price"))["total"], Decimal("18"))
        self.assertEqual(self.client.get(reverse("profile-earned-spent-data")).status_code, 401)
