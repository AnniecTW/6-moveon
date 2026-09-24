from django.test import TestCase

from .forms import ListingCreateForm
from .models import ItemCategory, ItemType, Listing


class ListingCreateFormTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        category = ItemCategory.objects.create(category_name="Furniture")
        cls.item_type = ItemType.objects.create(
            category=category, item_type_name="Desk"
        )

    def form_data(self, **overrides):
        data = {
            "title": "Desk",
            "listing_price": "25.00",
            "condition": "GOOD",
            "item_type": str(self.item_type.pk),
            "description": "",
            "minimum_price": "",
            "move_out_date": "",
            "bundle_eligible": "",
            "sell_no_matter_what": "",
        }
        data.update(overrides)
        return data

    def test_pickup_and_delivery_checkboxes_map_to_fulfillment_values(self):
        cases = (
            ({"fulfillment_pickup": "on"}, Listing.Fulfillment.PICKUP),
            ({"fulfillment_delivery": "on"}, Listing.Fulfillment.DELIVERY),
            (
                {"fulfillment_pickup": "on", "fulfillment_delivery": "on"},
                Listing.Fulfillment.BOTH,
            ),
        )
        for selected, expected in cases:
            with self.subTest(selected=selected):
                form = ListingCreateForm(data=self.form_data(**selected))
                self.assertTrue(form.is_valid(), form.errors)
                self.assertEqual(form.cleaned_data["fulfillment_option"], expected)

    def test_at_least_one_fulfillment_checkbox_is_required(self):
        form = ListingCreateForm(data=self.form_data())

        self.assertFalse(form.is_valid())
        self.assertIn(
            "Select pickup, delivery, or both fulfillment options.",
            form.non_field_errors(),
        )
