from django.test import TestCase
from django.urls import reverse
from django.core.management import call_command
from io import StringIO
from .models import User, ItemCategory, ItemType, Listing


class BrowseTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.seller = User.objects.create_user(
            username="seller", email="seller@example.com", display_name="Seller"
        )
        cls.category = ItemCategory.objects.create(category_name="Furniture")
        cls.item_type = ItemType.objects.create(
            category=cls.category, item_type_name="Desk"
        )
        for title, price, status, delivery in [
            ("Oak desk", 50, "ACTIVE", "DELIVERY"),
            ("Small desk", 20, "ACTIVE", "PICKUP"),
            ("Shared desk", 30, "ACTIVE", "BOTH"),
            ("Private draft", 10, "DRAFT", "PICKUP"),
            ("Sold desk", 5, "SOLD", "DELIVERY"),
        ]:
            Listing.objects.create(
                seller=cls.seller,
                item_type=cls.item_type,
                title=title,
                listing_price=price,
                condition="GOOD",
                status=status,
                fulfillment_option=delivery,
                bundle_eligible=price == 50,
            )

    def test_all_view_styles_render_same_active_listings(self):
        for name in (
            "home",
            "listing_manual",
            "listing_render",
            "listing_cbv_base",
            "listing_cbv_generic",
        ):
            with self.subTest(name=name):
                response = self.client.get(reverse(name))
                self.assertEqual(response.status_code, 200)
                self.assertEqual(
                    {x.title for x in response.context["listings"]},
                    {"Oak desk", "Small desk", "Shared desk"},
                )
                self.assertContains(response, "css/marketplace.css")
                self.assertContains(response, 'type="module"')

    def test_search_price_category_and_bundle(self):
        response = self.client.get(
            reverse("home"),
            {
                "q": "oak",
                "min_price": "30",
                "max_price": "60",
                "category": str(self.category.pk),
                "bundle": "on",
            },
        )
        self.assertEqual([x.title for x in response.context["listings"]], ["Oak desk"])
        self.assertEqual(len(response.context["filter_chips"]), 5)

    def test_pickup_filter(self):
        response = self.client.get(
            reverse("home"), {"fulfillment": "PICKUP", "sort": "price-asc"}
        )
        self.assertEqual(
            [x.title for x in response.context["listings"]],
            ["Small desk", "Shared desk"],
        )

    def test_delivery_does_not_include_pickup_only_but_includes_both(self):
        response = self.client.get(
            reverse("home"), {"fulfillment": "DELIVERY", "sort": "price-asc"}
        )
        self.assertEqual(
            [x.title for x in response.context["listings"]],
            ["Shared desk", "Oak desk"],
        )

    def test_both_fulfillment_filters_all_selected_capabilities(self):
        response = self.client.get(
            reverse("home"),
            {"fulfillment": ["PICKUP", "DELIVERY"], "sort": "price-asc"},
        )
        self.assertEqual(
            [x.title for x in response.context["listings"]],
            ["Small desk", "Shared desk", "Oak desk"],
        )
        self.assertEqual(
            [
                value
                for value, _ in response.context["filter_form"].fields[
                    "fulfillment"
                ].choices
            ],
            ["PICKUP", "DELIVERY"],
        )

    def test_empty_fulfillment_does_not_filter_listings(self):
        response = self.client.get(reverse("home"), {"sort": "price-asc"})

        self.assertEqual(
            [x.title for x in response.context["listings"]],
            ["Small desk", "Shared desk", "Oak desk"],
        )

    def test_invalid_filters_return_errors_not_server_errors(self):
        for params in (
            {"min_price": "oops"},
            {"min_price": "80", "max_price": "20"},
            {"sort": "invalid"},
            {"category": "999999"},
        ):
            with self.subTest(params=params):
                response = self.client.get(reverse("home"), params)
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.context["filter_form"].errors)
                self.assertEqual(len(response.context["listings"]), 0)

    def test_chip_removal_preserves_other_parameters(self):
        response = self.client.get(
            reverse("home"), {"q": "desk", "condition": "GOOD", "sort": "price-desc"}
        )
        chip = next(c for c in response.context["filter_chips"] if c["label"] == "desk")
        self.assertNotIn("q=", chip["url"])
        self.assertIn("condition=GOOD", chip["url"])
        self.assertIn("sort=price-desc", chip["url"])

    def test_search_is_escaped_and_empty_state_works(self):
        response = self.client.get(reverse("home"), {"q": "<script>alert(1)</script>"})
        self.assertContains(response, "No listings found")
        self.assertNotContains(response, "<script>alert(1)</script>")

    def test_free_listing_and_query_efficiency(self):
        Listing.objects.create(
            seller=self.seller,
            item_type=self.item_type,
            title="Free desk",
            listing_price=0,
            condition="FAIR",
            status="ACTIVE",
            fulfillment_option="PICKUP",
        )
        with self.assertNumQueries(5):
            response = self.client.get(reverse("home"), {"max_price": "0"})
        self.assertContains(response, "Free desk")
        self.assertEqual(len(response.context["listings"]), 1)


class DemoSeedTests(TestCase):
    def test_seed_is_valid_and_idempotent(self):
        output = StringIO()
        call_command("seed_demo_data", stdout=output)
        self.assertEqual(Listing.objects.count(), 8)
        call_command("seed_demo_data", stdout=output)
        self.assertEqual(Listing.objects.count(), 8)

    def test_seed_covers_all_fulfillment_options(self):
        call_command("seed_demo_data", stdout=StringIO())

        self.assertEqual(
            Listing.objects.get(title="Blue Sofa").fulfillment_option,
            Listing.Fulfillment.BOTH,
        )
        self.assertEqual(
            Listing.objects.get(title="Television").fulfillment_option,
            Listing.Fulfillment.DELIVERY,
        )
