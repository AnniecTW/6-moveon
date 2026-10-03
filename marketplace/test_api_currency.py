from unittest.mock import patch

import requests
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import ItemCategory, ItemType, Listing, User


class CurrencyApiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        seller = User.objects.create_user(
            username="currency-seller",
            email="currency-seller@illinois.edu",
            display_name="Currency Seller",
            email_verified=True,
            email_verified_at=timezone.now(),
        )
        category = ItemCategory.objects.create(category_name="Currency Furniture")
        item_type = ItemType.objects.create(
            category=category, item_type_name="Currency Desk"
        )
        cls.listing = Listing.objects.create(
            seller=seller,
            item_type=item_type,
            title="Oak Currency Desk",
            listing_price=40,
            condition=Listing.Condition.GOOD,
            fulfillment_option=Listing.Fulfillment.PICKUP,
            status=Listing.Status.ACTIVE,
        )

    def test_converts_filtered_public_listings(self):
        with patch("marketplace.api.requests.get") as get_rate:
            get_rate.return_value.json.return_value = [
                {"base": "USD", "quote": "CAD", "rate": 1.25, "date": "2026-10-02"}
            ]
            response = self.client.get(
                reverse("listing-currency-api"),
                {"currency": "CAD", "q": "Oak Currency"},
            )

        self.assertEqual(response.status_code, 200)
        get_rate.assert_called_once_with(
            "https://api.frankfurter.dev/v2/rates",
            params={"base": "USD", "quotes": "CAD"},
            timeout=5,
        )
        get_rate.return_value.raise_for_status.assert_called_once()
        data = response.json()
        self.assertEqual(data["rate_date"], "2026-10-02")
        self.assertEqual(data["results"], [
            {"id": self.listing.pk, "listing_price": "50.00", "retail_price": None}
        ])

    def test_rejects_unsupported_currency_and_handles_timeout(self):
        with patch("marketplace.api.requests.get") as get_rate:
            invalid = self.client.get(
                reverse("listing-currency-api"), {"currency": "XYZ"}
            )
            self.assertEqual(invalid.status_code, 400)
            get_rate.assert_not_called()

            get_rate.side_effect = requests.Timeout
            timed_out = self.client.get(
                reverse("listing-currency-api"), {"currency": "CAD"}
            )
        self.assertEqual(timed_out.status_code, 504)
