import csv
import io
import re

from django.test import TestCase
from django.urls import reverse

from .models import ItemCategory, ItemType, Listing, User


class ListingExportTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        seller = User.objects.create_user(
            username="exp_seller", email="exp_seller@illinois.edu", display_name="Sam"
        )
        cls.furniture = ItemCategory.objects.create(category_name="Exp Furniture")
        cls.tech = ItemCategory.objects.create(category_name="Exp Tech")
        desk = ItemType.objects.create(category=cls.furniture, item_type_name="Desk")
        lamp = ItemType.objects.create(category=cls.tech, item_type_name="Lamp")
        for title, kind, price, status in [
            ("Oak Desk", desk, 40, "ACTIVE"),
            ("=HYPERLINK(1)", desk, 20, "ACTIVE"),
            ("Desk Lamp", lamp, 10, "ACTIVE"),
            ("Draft Chair", desk, 99, "DRAFT"),
        ]:
            Listing.objects.create(
                seller=seller, item_type=kind, title=title, listing_price=price,
                condition="GOOD", fulfillment_option="PICKUP", status=status,
            )

    def test_csv_download(self):
        response = self.client.get(reverse("listing-export-csv"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/csv")
        self.assertRegex(
            response["Content-Disposition"],
            r'^attachment; filename="listings_\d{4}-\d{2}-\d{2}_\d{2}-\d{2}\.csv"$',
        )
        rows = list(csv.reader(io.StringIO(response.content.decode())))
        self.assertEqual(rows[0][:4], ["id", "listing_id", "title", "category"])
        self.assertEqual(len(rows), 4)  # header + 3 active, draft excluded
        titles = [row[2] for row in rows[1:]]
        self.assertIn("'=HYPERLINK(1)", titles)  # formula neutralised
        self.assertNotIn("Draft Chair", titles)

    def test_json_download_has_metadata_and_honors_filters(self):
        response = self.client.get(
            reverse("listing-export-json"), {"category": self.furniture.pk}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/json")
        self.assertRegex(
            response["Content-Disposition"],
            r'^attachment; filename="listings_\d{4}-\d{2}-\d{2}_\d{2}-\d{2}\.json"$',
        )
        self.assertIn('\n  "record_count"', response.content.decode())  # indented
        payload = response.json()
        self.assertIn("generated_at", payload)
        self.assertEqual(payload["record_count"], 2)
        self.assertEqual(len(payload["listings"]), 2)

    def test_invalid_filters_rejected(self):
        self.assertEqual(
            self.client.get(reverse("listing-export-csv"), {"min_price": "abc"}).status_code, 400
        )
        self.assertEqual(
            self.client.get(reverse("listing-export-json"), {"min_price": "abc"}).status_code, 400
        )

    def test_report_page(self):
        response = self.client.get(reverse("listing-report"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Total listings: 3")
        self.assertContains(response, "Exp Furniture")
        self.assertContains(response, reverse("listing-export-csv"))
        self.assertContains(response, reverse("listing-export-json"))
        self.assertTrue(re.search(r"Good</th>\s*<td>3</td>", response.content.decode()))

    def test_report_empty_state(self):
        response = self.client.get(reverse("listing-report"), {"q": "zzzz-nothing"})
        self.assertContains(response, "Total listings: 0")
        self.assertContains(response, "No listings to summarize yet.", count=2)
