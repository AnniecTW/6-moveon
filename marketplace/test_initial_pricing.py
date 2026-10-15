from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch
import importlib

from django.test import TestCase, SimpleTestCase
from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone as django_timezone

from marketplace.models import ItemCategory, ItemType, Listing, User
from marketplace.pricing.initial import Observation, load_source, recommend
from marketplace.pricing.semantic import suggest_types
from marketplace.pricing import semantic
from marketplace.apps import MarketplaceConfig


def observation(number, price, condition="GOOD", brand=""):
    return Observation(
        item_id=str(number), observed_at=datetime(2023, 6, 1, tzinfo=timezone.utc),
        price=Decimal(str(price)), category="furniture", item_type="desk",
        condition=condition, brand=brand.casefold(), name=f"desk {number}", source_shard="sample",
    )


class ComparablePricingTests(SimpleTestCase):
    def test_exact_condition_median_and_observed_iqr(self):
        rows = [observation(i, 20 + i) for i in range(8)]
        result = recommend(rows, category="Furniture", item_type="Desk", condition="GOOD")
        self.assertEqual(result["benchmark_price"], Decimal("23.50"))
        self.assertEqual(result["range_low"], Decimal("21.75"))
        self.assertEqual(result["range_high"], Decimal("25.25"))
        self.assertEqual(result["range_kind"], "OBSERVED_IQR")
        self.assertEqual(result["evidence_grade"], "LOW")
        self.assertEqual(len(result["comparable_item_ids"]), 8)

    def test_type_only_guide_without_condition_uses_observed_median(self):
        rows = ([observation(i, 20, "NEW") for i in range(8)] +
                [observation(i + 8, 40, "GOOD") for i in range(8)])
        broad = recommend(rows, category="Furniture", item_type="Desk", condition="")
        specific = recommend(rows, category="Furniture", item_type="Desk", condition="NEW")
        self.assertEqual(broad["method"], "TYPE_MEDIAN_UNADJUSTED")
        self.assertEqual(broad["benchmark_price"], Decimal("30.00"))
        self.assertEqual(broad["comparable_count"], 16)
        self.assertIn("across all conditions", broad["explanation"])
        self.assertEqual(specific["method"], "TYPE_CONDITION_MEDIAN")
        self.assertEqual(specific["benchmark_price"], Decimal("20.00"))
        self.assertEqual(specific["comparable_count"], 8)

    def test_type_only_guide_warns_when_sample_is_sparse(self):
        rows = [observation(i, 30, "GOOD") for i in range(3)]
        result = recommend(rows, category="Furniture", item_type="Desk", condition="")
        self.assertEqual(result["method"], "SPARSE_TYPE_MEDIAN")
        self.assertEqual(result["benchmark_price"], Decimal("30.00"))
        self.assertEqual(result["comparable_count"], 3)
        self.assertEqual(result["evidence_grade"], "VERY_LOW")
        self.assertIsNone(result["range_kind"])
        self.assertIn("Only 3 historical items", result["warning"])

    def test_type_only_boundary_is_ten_observations(self):
        rows = [observation(i, 30, "NEW") for i in range(10)]
        below = recommend(rows[:9], category="Furniture", item_type="Desk", condition="")
        enough = recommend(rows, category="Furniture", item_type="Desk", condition="")
        self.assertEqual(below["method"], "SPARSE_TYPE_MEDIAN")
        self.assertIn("Only 9 historical items", below["warning"])
        self.assertEqual(enough["method"], "TYPE_MEDIAN_UNADJUSTED")
        self.assertEqual(enough["benchmark_price"], Decimal("30.00"))

    def test_condition_selected_unadjusted_fallback_uses_ten_observations(self):
        rows = ([observation(i, 20, "NEW") for i in range(5)] +
                [observation(i + 5, 40, "GOOD") for i in range(5)])
        below = recommend(rows[:9], category="Furniture", item_type="Desk", condition="NEW")
        enough = recommend(rows, category="Furniture", item_type="Desk", condition="NEW")
        self.assertEqual(below["method"], "SPARSE_CONDITION_MEDIAN")
        self.assertEqual(enough["method"], "TYPE_MEDIAN_UNADJUSTED")
        self.assertEqual(enough["benchmark_price"], Decimal("30.00"))

    def test_unknown_condition_does_not_use_type_only_guide(self):
        rows = [observation(i, 30, "GOOD") for i in range(12)]
        result = recommend(rows, category="Furniture", item_type="Desk", condition="BROKEN")
        self.assertEqual(result["method"], "ABSTAIN")

    def test_condition_factor_uses_matched_type_not_universal_percentage(self):
        rows = ([observation(i, 100, "NEW", "Known") for i in range(8)] +
                [observation(i + 8, 50, "GOOD", "Other") for i in range(8)])
        result = recommend(rows, category="Furniture", item_type="Desk",
                           condition="GOOD", brand="Known")
        self.assertEqual(result["method"], "BRAND_CONDITION_FACTOR")
        self.assertEqual(result["benchmark_price"], Decimal("50.00"))
        self.assertEqual(result["condition_factor"], "0.5")
        self.assertEqual(len(result["factor_target_item_ids"]), 8)
        self.assertEqual(len(result["factor_base_item_ids"]), 8)

    def test_sparse_fair_uses_observed_fair_price_with_warning(self):
        rows = [observation(i, 20, "NEW") for i in range(20)]
        rows.append(observation(21, 10, "FAIR"))
        result = recommend(rows, category="Furniture", item_type="Desk", condition="FAIR")
        self.assertEqual(result["benchmark_price"], Decimal("10.00"))
        self.assertEqual(result["method"], "SPARSE_CONDITION_MEDIAN")
        self.assertEqual(result["evidence_grade"], "VERY_LOW")
        self.assertIn("Only 1 historical item", result["warning"])
        self.assertIsNone(result["range_low"])

    def test_missing_type_explains_why_no_price_is_shown(self):
        result = recommend([], category="Furniture", item_type="Bookshelf", condition="GOOD")
        self.assertEqual(result["method"], "ABSTAIN")
        self.assertIn("No Furniture / Bookshelf observations", result["explanation"])

    def test_source_is_unchanged_and_risk_rows_are_excluded(self):
        rows, profile = load_source()
        self.assertEqual(profile["source_rows"], 1409)
        self.assertEqual(profile["price_flagged"], 2)
        self.assertEqual(len(rows), 1407)
        self.assertEqual(profile["sha256"],
                         "160c363b9df39c6007beecbfcfe1c49547ac7e4d3d9aaf5a3947bfdd2b8d7640")


class SemanticSuggestionTests(SimpleTestCase):
    def test_catalog_is_embedded_once_per_process(self):
        category = SimpleNamespace(pk=1, category_name="Furniture")
        kind = SimpleNamespace(pk=1, category=category, category_id=1,
                               item_type_name="Bookshelf")
        rows = [Observation("1", datetime(2023, 6, 1, tzinfo=timezone.utc),
                            Decimal("35"), "furniture", "bookshelf", "GOOD", "",
                            "wooden bookcase", "sample")]

        class Encoder:
            def __init__(self):
                self.inputs = []

            def encode(self, texts, normalize_embeddings):
                self.inputs.append(tuple(texts))
                return [[1.0, 0.0] for _ in texts]

        encoder = Encoder()
        semantic._document_vectors.cache_clear()
        try:
            with patch("marketplace.pricing.semantic._model", return_value=encoder):
                for _ in range(2):
                    result = suggest_types(rows, [kind], title="Bookcase",
                                           category="Furniture", item_type="")
                    self.assertEqual(result[0]["item_type"], "Bookshelf")
            self.assertEqual([len(batch) for batch in encoder.inputs], [1, 1, 1])
            self.assertEqual(semantic._document_vectors.cache_info().hits, 1)
        finally:
            semantic._document_vectors.cache_clear()

    def test_source_rows_are_reused_until_file_changes(self):
        semantic._source_for_version.cache_clear()
        try:
            with patch("marketplace.pricing.semantic.load_source", return_value=([], {})) as loader:
                semantic.suggestion_source()
                semantic.suggestion_source()
            self.assertEqual(loader.call_count, 1)
        finally:
            semantic._source_for_version.cache_clear()

    def test_limits_results_to_five_and_returns_none_for_short_title(self):
        category = SimpleNamespace(pk=1, category_name="Furniture")
        kinds = [SimpleNamespace(pk=i, category=category, category_id=1,
                                 item_type_name=f"Shelf {i}") for i in range(1, 8)]
        rows = [Observation(str(i), datetime(2023, 6, 1, tzinfo=timezone.utc),
                            Decimal("30"), "furniture", f"shelf {i}", "GOOD", "",
                            f"shelf listing {i}", "sample") for i in range(1, 8)]

        class Encoder:
            def encode(self, texts, normalize_embeddings):
                return [[1.0, 0.0] for _ in texts]

        self.assertEqual(suggest_types(rows, kinds, title="x", category="",
                                       item_type="", model=Encoder()), [])
        result = suggest_types(rows, kinds, title="Shelf", category="Furniture",
                               item_type="", model=Encoder())
        self.assertEqual(len(result), 5)

    def test_only_source_backed_types_above_threshold_are_returned(self):
        furniture = SimpleNamespace(pk=1, category_name="Furniture")
        storage = SimpleNamespace(pk=2, category_name="Storage & Organization")
        types = [
            SimpleNamespace(pk=1, category=furniture, category_id=1, item_type_name="Bookshelf"),
            SimpleNamespace(pk=2, category=storage, category_id=2, item_type_name="Spice Racks"),
            SimpleNamespace(pk=3, category=furniture, category_id=1, item_type_name="Desk"),
        ]
        rows = [
            Observation("1", datetime(2023, 6, 1, tzinfo=timezone.utc), Decimal("35"),
                        "furniture", "bookshelf", "GOOD", "", "wooden bookcase", "sample"),
            Observation("2", datetime(2023, 6, 1, tzinfo=timezone.utc), Decimal("13"),
                        "storage & organization", "spice racks", "NEW", "", "spice rack", "sample"),
        ]

        class Encoder:
            def encode(self, texts, normalize_embeddings):
                self.assert_normalized = normalize_embeddings
                return [[1, 0], [0.9, 0.1], [0.1, 0.9]]

        result = suggest_types(rows, types, title="Bookcase", category="Furniture",
                               item_type="Bookshelf", model=Encoder())
        self.assertEqual([item["item_type_id"] for item in result], [1])
        self.assertEqual(result[0]["observation_count"], 1)
        self.assertTrue(result[0]["may_support_price"])
        self.assertTrue(result[0]["limited_evidence"])
        self.assertEqual(result[0]["category_id"], 1)
        self.assertEqual(result[0]["example_title"], "wooden bookcase")


class InitialPricingIntegrationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.seller = User.objects.create_user(
            username="pricing-seller", email="pricing-seller@illinois.edu",
            password="test-password", display_name="Pricing Seller",
            email_verified=True, email_verified_at=django_timezone.now(),
        )
        category = ItemCategory.objects.create(category_name="Kitchen & Dining")
        cls.item_type = ItemType.objects.create(category=category, item_type_name="Mugs & Cups")

    def setUp(self):
        self.client.force_login(self.seller)

    def form_data(self, **overrides):
        data = {
            "action": "preview", "title": "Ceramic mug", "brand": "",
            "listing_price": "999.00", "condition": "NEW",
            "item_type": str(self.item_type.pk), "fulfillment_pickup": "on",
            "image_ids": "", "pricing_decision": "EDITED",
        }
        data.update(overrides)
        return data

    def test_endpoint_returns_real_observed_evidence(self):
        response = self.client.get(reverse("listing-initial-price"), {
            "item_type": self.item_type.pk, "condition": "NEW",
        })
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertGreaterEqual(payload["comparable_count"], 8)
        self.assertEqual(payload["source_price_kind"], "UNVERIFIED_BUY_COMP_OBSERVED_PRICE")
        self.assertEqual(payload["range_kind"], "OBSERVED_IQR")
        self.assertNotEqual(payload["suggested_listing_price"], "52.50")

    def test_endpoint_returns_type_only_guide_before_condition(self):
        response = self.client.get(reverse("listing-initial-price"), {
            "item_type": self.item_type.pk,
        })
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["method"], "TYPE_MEDIAN_UNADJUSTED")
        self.assertIsNotNone(payload["suggested_listing_price"])
        self.assertIn("across all conditions", payload["explanation"])

    def test_sparse_suggested_type_returns_limited_reference(self):
        category = ItemCategory.objects.create(category_name="Storage & Organization")
        shelf_type = ItemType.objects.create(
            category=category, item_type_name="Storage Shelves & Racks"
        )
        response = self.client.get(reverse("listing-initial-price"), {
            "item_type": shelf_type.pk, "condition": "GOOD",
        })
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result["suggested_listing_price"], "24.00")
        self.assertEqual(result["method"], "SPARSE_TYPE_MEDIAN")
        self.assertEqual(result["comparable_count"], 3)
        self.assertIn("Only 3 historical items", result["warning"])
        self.assertIn("all conditions", result["warning"])

    def test_form_contains_no_fixed_price_or_floor_suggestion(self):
        response = self.client.get(reverse("listing-create-url"))
        self.assertContains(response, "Observed-price recommendation")
        self.assertNotContains(response, "data-range-midpoint=\"52.5\"")
        self.assertNotContains(response, "data-range-midpoint=\"35\"")
        self.assertContains(response, "Item type")
        self.assertContains(response, "data-suggestions-url")
        self.assertContains(response, "data-price-warning")
        self.assertContains(response, f'data-category-id="{self.item_type.category_id}"')

    def test_semantic_endpoint_returns_source_backed_candidates(self):
        with patch("marketplace.views.suggest_types", return_value=[{
            "item_type_id": self.item_type.pk, "category_id": self.item_type.category_id,
            "category": "Kitchen & Dining", "item_type": "Mugs & Cups",
            "observation_count": 14, "example_title": "ceramic mug", "similarity": 0.72,
        }]) as matcher:
            response = self.client.get(reverse("listing-type-suggestions"), {
                "title": "Ceramic cup", "category": self.item_type.category_id,
                "item_type": self.item_type.pk, "brand": "",
            })
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["candidates"][0]["item_type_id"], self.item_type.pk)
        self.assertEqual(payload["price_guide_condition"], "")
        guide = payload["candidates"][0]["price_guide"]
        direct = self.client.get(reverse("listing-initial-price"), {
            "item_type": self.item_type.pk,
        }).json()
        self.assertEqual(guide["method"], "TYPE_MEDIAN_UNADJUSTED")
        self.assertEqual(guide["suggested_listing_price"], direct["suggested_listing_price"])
        self.assertEqual(guide["range_low"], direct["range_low"])
        self.assertEqual(guide["range_high"], direct["range_high"])
        self.assertTrue(matcher.called)

    def test_sparse_candidate_previews_limited_reference(self):
        category = ItemCategory.objects.create(category_name="Storage & Organization")
        shelf_type = ItemType.objects.create(
            category=category, item_type_name="Storage Shelves & Racks"
        )
        with patch("marketplace.views.suggest_types", return_value=[{
            "item_type_id": shelf_type.pk, "category_id": category.pk,
            "category": category.category_name, "item_type": shelf_type.item_type_name,
            "observation_count": 3, "example_title": "shelf", "similarity": 0.7,
        }]):
            response = self.client.get(reverse("listing-type-suggestions"), {
                "title": "Bookshelf",
            })
        self.assertEqual(response.status_code, 200)
        guide = response.json()["candidates"][0]["price_guide"]
        self.assertEqual(guide["method"], "SPARSE_TYPE_MEDIAN")
        self.assertEqual(guide["suggested_listing_price"], "24.00")
        self.assertIn("Only 3 historical items", guide["warning"])

    def test_semantic_endpoint_degrades_to_manual_selection(self):
        with patch("marketplace.views.suggest_types", side_effect=ImportError("model unavailable")):
            response = self.client.get(reverse("listing-type-suggestions"), {
                "title": "Ceramic cup", "category": self.item_type.category_id,
            })
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["candidates"], [])

    def test_dev_server_preloads_model_without_preloading_during_tests(self):
        config = MarketplaceConfig("marketplace", importlib.import_module("marketplace"))
        with patch("marketplace.pricing.semantic._model") as model:
            with patch("marketplace.apps.sys.argv", ["manage.py", "test"]):
                config.ready()
            model.assert_not_called()
            with patch("marketplace.apps.sys.argv", ["manage.py", "runserver", "--noreload"]):
                config.ready()
            model.assert_called_once()
            with patch("marketplace.apps.sys.argv", ["manage.py", "runserver"]), \
                 patch.dict("marketplace.apps.os.environ", {"RUN_MAIN": "true"}):
                config.ready()
            self.assertEqual(model.call_count, 2)

    def test_none_match_keeps_manual_type_and_records_choice(self):
        response = self.client.post(reverse("listing-create-url"), self.form_data(
            category=str(self.item_type.category_id), match_choice="NONE"))
        self.assertEqual(response.status_code, 302)
        listing = Listing.objects.get(title="Ceramic mug")
        self.assertEqual(listing.item_type_id, self.item_type.pk)
        self.assertEqual(listing.valuation_metadata["semantic_match_choice"], "NONE")

    def test_category_mismatch_and_forged_match_are_rejected(self):
        other = ItemCategory.objects.create(category_name="Furniture")
        response = self.client.post(reverse("listing-create-url"), self.form_data(
            category=str(other.pk), match_choice=f"TYPE:{self.item_type.pk}"))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Listing.objects.filter(title="Ceramic mug").exists())
        response = self.client.post(reverse("listing-create-url"), self.form_data(
            category=str(self.item_type.category_id), match_choice="TYPE:999999"))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Listing.objects.filter(title="Ceramic mug").exists())

    def test_taxonomy_sync_adds_source_backed_types_idempotently(self):
        call_command("sync_pricing_taxonomy", verbosity=0)
        rows, _ = load_source()
        source_types = {(row.category, row.item_type) for row in rows}
        db_types = {(kind.category.category_name.casefold(), kind.item_type_name.casefold())
                    for kind in ItemType.objects.select_related("category")}
        self.assertTrue(source_types.issubset(db_types))
        before = ItemType.objects.count()
        call_command("sync_pricing_taxonomy", verbosity=0)
        self.assertEqual(ItemType.objects.count(), before)

    def test_seller_price_remains_distinct_and_decision_is_recorded(self):
        response = self.client.post(reverse("listing-create-url"), self.form_data())
        self.assertEqual(response.status_code, 302)
        listing = Listing.objects.get(title="Ceramic mug")
        self.assertEqual(listing.listing_price, Decimal("999.00"))
        self.assertIsNotNone(listing.benchmark_price)
        self.assertNotEqual(listing.listing_price, listing.benchmark_price)
        self.assertEqual(listing.valuation_metadata["seller_decision"], "EDITED")
        self.assertEqual(listing.valuation_metadata["range_kind"], "OBSERVED_IQR")

    def test_acceptance_uses_server_recomputed_price(self):
        response = self.client.post(reverse("listing-create-url"),
                                    self.form_data(title="Accepted mug", pricing_decision="ACCEPTED"))
        self.assertEqual(response.status_code, 302)
        listing = Listing.objects.get(title="Accepted mug")
        self.assertEqual(listing.listing_price, listing.benchmark_price)
        self.assertEqual(listing.valuation_metadata["seller_decision"], "ACCEPTED")

    def test_declined_recommendation_keeps_seller_price(self):
        response = self.client.post(reverse("listing-create-url"),
                                    self.form_data(title="Declined mug", pricing_decision="DECLINED"))
        self.assertEqual(response.status_code, 302)
        listing = Listing.objects.get(title="Declined mug")
        self.assertEqual(listing.listing_price, Decimal("999.00"))
        self.assertEqual(listing.valuation_metadata["seller_decision"], "DECLINED")

    def test_acceptance_cannot_cross_seller_floor(self):
        response = self.client.post(reverse("listing-create-url"), self.form_data(
            title="Floor protected mug", minimum_price="900.00", pricing_decision="ACCEPTED"))
        self.assertEqual(response.status_code, 302)
        listing = Listing.objects.get(title="Floor protected mug")
        self.assertEqual(listing.listing_price, Decimal("999.00"))
        self.assertEqual(listing.valuation_metadata["seller_decision"], "FLOOR_PROTECTED")

    def test_sparse_reference_is_recomputed_and_floor_protected_on_save(self):
        category = ItemCategory.objects.create(category_name="Storage & Organization")
        shelf_type = ItemType.objects.create(
            category=category, item_type_name="Storage Shelves & Racks"
        )
        response = self.client.post(reverse("listing-create-url"), self.form_data(
            title="Sparse shelf", item_type=str(shelf_type.pk), category=str(category.pk),
            condition="GOOD", minimum_price="30.00", pricing_decision="ACCEPTED",
        ))
        self.assertEqual(response.status_code, 302)
        listing = Listing.objects.get(title="Sparse shelf")
        self.assertEqual(listing.benchmark_price, Decimal("24.00"))
        self.assertEqual(listing.listing_price, Decimal("999.00"))
        self.assertEqual(listing.valuation_metadata["seller_decision"], "FLOOR_PROTECTED")
        self.assertEqual(listing.valuation_metadata["evidence_grade"], "VERY_LOW")
        self.assertEqual(listing.valuation_metadata["comparable_count"], 3)

    def test_decline_and_abstention(self):
        category = ItemCategory.objects.create(category_name="Rare category")
        rare = ItemType.objects.create(category=category, item_type_name="Rare type")
        response = self.client.post(reverse("listing-create-url"), self.form_data(
            title="Rare object", item_type=str(rare.pk), pricing_decision="ACCEPTED"))
        self.assertEqual(response.status_code, 302)
        listing = Listing.objects.get(title="Rare object")
        self.assertIsNone(listing.benchmark_price)
        self.assertEqual(listing.listing_price, Decimal("999.00"))
        self.assertEqual(listing.valuation_metadata["seller_decision"], "ABSTAINED")
