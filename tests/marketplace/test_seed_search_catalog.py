from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from marketplace.management.commands.seed_search_catalog import (
    DEMO_EMAIL, DEMO_USERNAME, load_catalog,
)
from marketplace.models import ItemCategory, ItemType, Listing, User

CATALOG_SIZE = len(load_catalog())


def run(**options):
    out = StringIO()
    call_command("seed_search_catalog", stdout=out, **options)
    return out.getvalue()


class SeedSearchCatalogTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username="real-seller", email="real@illinois.edu")
        self.kind = ItemType.objects.create(
            category=ItemCategory.objects.create(category_name="furniture"), item_type_name="chair",
        )
        self.real = Listing.objects.create(
            seller=self.owner, item_type=self.kind, title="Real chair", listing_price="10.00",
            condition=Listing.Condition.GOOD, status=Listing.Status.ACTIVE,
            fulfillment_option=Listing.Fulfillment.PICKUP,
        )

    def test_adds_the_catalogue_once_beside_existing_listings(self):
        run()
        demo = Listing.objects.filter(seller__username=DEMO_USERNAME)
        self.assertEqual(demo.count(), CATALOG_SIZE)
        self.assertFalse(demo.exclude(status=Listing.Status.ACTIVE).exists())
        run()
        self.assertEqual(Listing.objects.count(), CATALOG_SIZE + 1)
        self.real.refresh_from_db()
        self.assertEqual(self.real.title, "Real chair")

    def test_keeps_evaluated_text_and_reuses_existing_taxonomy(self):
        run()
        rocking = Listing.objects.get(listing_id="2c196ab0-26af-5140-8421-548f2444fa12")
        self.assertEqual(rocking.title, "Rocking Chair")
        self.assertTrue(rocking.description.startswith("Classic wooden rocking chair"))
        self.assertEqual(rocking.item_type, self.kind)
        self.assertEqual(ItemCategory.objects.filter(category_name__iexact="Furniture").count(), 1)

    def test_demo_seller_cannot_sign_in(self):
        run()
        seller = User.objects.get(username=DEMO_USERNAME)
        self.assertFalse(seller.is_active)
        self.assertFalse(seller.has_usable_password())
        self.assertFalse(seller.is_staff or seller.is_superuser or seller.email_verified)

    def test_refuses_a_real_account_with_the_demo_username(self):
        User.objects.create_user(username=DEMO_USERNAME, email=DEMO_EMAIL, password="x-123-secret")
        with self.assertRaises(CommandError):
            run()
        self.assertEqual(Listing.objects.count(), 1)

    def test_remove_deletes_only_the_catalogue_and_seller(self):
        run()
        output = run(remove=True)
        self.assertIn(f"Removed {CATALOG_SIZE}", output)
        self.assertEqual(list(Listing.objects.all()), [self.real])
        self.assertFalse(User.objects.filter(username=DEMO_USERNAME).exists())
        self.assertIn("No demo catalogue", run(remove=True))
