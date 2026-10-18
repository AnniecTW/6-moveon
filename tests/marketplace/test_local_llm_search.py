import json
from unittest.mock import patch

from django.db import OperationalError
from django.test import TestCase
from django.urls import reverse

from marketplace.local_llm import LocalLLMError, parse_listing_ids, rank_listing_ids
from marketplace.models import ItemCategory, ItemType, Listing, User


class ListingIdValidationTests(TestCase):
    @patch("marketplace.local_llm._generate_response")
    def test_removes_duplicates_and_unknown_ids_and_limits_results_to_five(
        self, generate_response
    ):
        generate_response.return_value = '{"ids":[4,4,99,3,2,1,5,6]}'
        candidates = [
            {
                "pk": listing_id,
                "title": "Lamp",
                "category": "Furniture / Lamp",
                "listing_price": "20.00",
                "condition": "GOOD",
                "description": "A lamp.",
            }
            for listing_id in range(1, 7)
        ]

        self.assertEqual(rank_listing_ids("lamp", candidates), [4, 3, 2, 1, 5])
        self.assertEqual(set(generate_response.call_args.args[0][1]), {"role", "content"})

    @patch("marketplace.local_llm._generate_response")
    def test_rejects_non_integer_ids(self, generate_response):
        generate_response.return_value = '{"ids":[true,"1",1]}'
        candidate = {
            "pk": 1,
            "title": "Lamp",
            "category": "Furniture / Lamp",
            "listing_price": "20.00",
            "condition": "GOOD",
            "description": "A lamp.",
        }

        self.assertEqual(rank_listing_ids("lamp", [candidate]), [1])

    def test_rejects_malformed_json(self):
        with self.assertRaises(LocalLLMError):
            parse_listing_ids("not json", [1])

    def test_accepts_an_empty_ids_list_as_no_relevant_matches(self):
        self.assertEqual(parse_listing_ids('{"ids":[]}', [1, 2]), [])

    def test_rejects_nonempty_list_with_only_unknown_ids(self):
        with self.assertRaisesRegex(LocalLLMError, "no valid candidate IDs"):
            parse_listing_ids('{"ids":[999]}', [1, 2])


class LocalLLMSearchViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.seller = User.objects.create_user(
            username="seller", email="seller@example.com", display_name="Seller"
        )
        category = ItemCategory.objects.create(category_name="Furniture")
        item_type = ItemType.objects.create(category=category, item_type_name="Lamp")
        cls.first = Listing.objects.create(
            seller=cls.seller,
            item_type=item_type,
            title="Oak bedside lamp",
            description="Warm light for a bedroom.",
            listing_price="25.00",
            condition=Listing.Condition.GOOD,
            status=Listing.Status.ACTIVE,
            fulfillment_option=Listing.Fulfillment.PICKUP,
        )
        cls.second = Listing.objects.create(
            seller=cls.seller,
            item_type=item_type,
            title="Blue reading lamp",
            description="A compact bedroom lamp for reading.",
            listing_price="18.00",
            condition=Listing.Condition.LIKE_NEW,
            status=Listing.Status.ACTIVE,
            fulfillment_option=Listing.Fulfillment.PICKUP,
        )
        cls.inactive = Listing.objects.create(
            seller=cls.seller,
            item_type=item_type,
            title="Inactive bedroom lamp",
            description="A bedroom lamp.",
            listing_price="10.00",
            condition=Listing.Condition.GOOD,
            status=Listing.Status.INACTIVE,
            fulfillment_option=Listing.Fulfillment.PICKUP,
        )

    @patch("marketplace.local_llm._generate_response")
    def test_search_renders_listings_in_model_order(self, generate_response):
        generate_response.return_value = (
            f'{{"ids":[{self.second.pk},{self.first.pk}]}}'
        )

        response = self.client.get(
            reverse("home"), {"q": "bedroom lighting", "search_mode": "ai"}
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [listing.pk for listing in response.context["listings"]],
            [self.second.pk, self.first.pk],
        )
        self.assertEqual(response.context["search_mode"], "ai")
        self.assertFalse(response.context["ai_search_error"])
        model_messages = generate_response.call_args.args[0]
        model_catalog = json.loads(model_messages[1]["content"])
        self.assertEqual(
            {listing["id"] for listing in model_catalog["candidate_listings"]},
            {self.first.pk, self.second.pk},
        )
        for candidate in model_catalog["candidate_listings"]:
            self.assertIs(type(candidate["id"]), int)
            self.assertEqual(
                set(candidate),
                {"id", "title", "category", "price", "condition", "description"},
            )

    @patch("marketplace.local_llm._generate_response")
    def test_bathroom_cleaning_with_unrelated_ranked_ids_shows_random_fallback(
        self, generate_response
    ):
        unrelated = []
        for title in ("Small Coffee Table", "Refurbished Flatscreen", "Sectional Sofa", "Dresser"):
            unrelated.append(
                Listing.objects.create(
                    seller=self.seller,
                    item_type=self.first.item_type,
                    title=title,
                    description="",
                    listing_price="30.00",
                    condition=Listing.Condition.GOOD,
                    status=Listing.Status.ACTIVE,
                    fulfillment_option=Listing.Fulfillment.PICKUP,
                )
            )
        generate_response.return_value = json.dumps(
            {"ids": [listing.pk for listing in unrelated]}
        )

        response = self.client.get(
            reverse("listing-list-url"),
            {"q": "bathroom cleaning", "search_mode": "ai"},
        )

        catalog = json.loads(generate_response.call_args.args[0][1]["content"])
        self.assertEqual(len(catalog["candidate_listings"]), 6)
        self.assertTrue(response.context["ai_search_fallback"])
        self.assertGreater(len(response.context["listings"]), 0)
        self.assertLessEqual(len(response.context["listings"]), 5)
        self.assertTrue(
            all(item.status == Listing.Status.ACTIVE for item in response.context["listings"])
        )
        self.assertFalse(response.context["ai_search_error"])
        self.assertContains(response, "No relevant listings found for this search.")
        self.assertContains(response, "Please update your search terms.")
        self.assertContains(
            response,
            "The listings below are randomly selected fallback items, not AI recommendations.",
        )
        self.assertNotIn(self.inactive.pk, [item.pk for item in response.context["listings"]])
        system_prompt = generate_response.call_args.args[0][0]["content"]
        self.assertIn('return exactly {"ids":[]}', system_prompt)
        self.assertIn("do not add unrelated listings", system_prompt)

    @patch("marketplace.local_llm._generate_response")
    def test_ai_displays_only_model_selected_relevant_ids_in_model_order(
        self, generate_response
    ):
        home_category = ItemCategory.objects.create(category_name="Home Care")
        cleaning_type = ItemType.objects.create(
            category=home_category, item_type_name="Cleaning Supplies"
        )
        table_type = ItemType.objects.create(
            category=self.first.item_type.category, item_type_name="Coffee Table"
        )
        relevant_first = Listing.objects.create(
            seller=self.seller,
            item_type=cleaning_type,
            title="Bathroom scrub brush",
            description="Scrubs tile and grout.",
            listing_price="8.00",
            condition=Listing.Condition.GOOD,
            status=Listing.Status.ACTIVE,
            fulfillment_option=Listing.Fulfillment.PICKUP,
        )
        relevant_second = Listing.objects.create(
            seller=self.seller,
            item_type=cleaning_type,
            title="Bathroom cleaner",
            description="Cleaning spray for sinks and tile.",
            listing_price="6.00",
            condition=Listing.Condition.GOOD,
            status=Listing.Status.ACTIVE,
            fulfillment_option=Listing.Fulfillment.PICKUP,
        )
        unrelated = Listing.objects.create(
            seller=self.seller,
            item_type=table_type,
            title="Coffee table",
            description="Wood living room table.",
            listing_price="40.00",
            condition=Listing.Condition.GOOD,
            status=Listing.Status.ACTIVE,
            fulfillment_option=Listing.Fulfillment.PICKUP,
        )
        generate_response.return_value = (
            f'{{"ids":[{relevant_second.pk},{relevant_first.pk}]}}'
        )

        response = self.client.get(
            reverse("home"), {"q": "bathroom cleaning", "search_mode": "ai"}
        )

        self.assertEqual(
            [listing.pk for listing in response.context["listings"]],
            [relevant_second.pk, relevant_first.pk],
        )
        catalog = json.loads(generate_response.call_args.args[0][1]["content"])
        self.assertIn(unrelated.pk, [item["id"] for item in catalog["candidate_listings"]])
        self.assertNotIn(unrelated.pk, [item.pk for item in response.context["listings"]])

    @patch("marketplace.local_llm._generate_response")
    def test_relevance_gate_rejects_unrelated_ranked_ids_and_keeps_relevant_item(
        self, generate_response
    ):
        home_care = ItemCategory.objects.create(category_name="Home Care")
        cleaning_type = ItemType.objects.create(
            category=home_care, item_type_name="Cleaning Supplies"
        )
        electronics = ItemCategory.objects.create(category_name="Electronics")
        television_type = ItemType.objects.create(
            category=electronics, item_type_name="Television"
        )
        furniture_type = ItemType.objects.create(
            category=self.first.item_type.category, item_type_name="Coffee Table"
        )
        relevant = Listing.objects.create(
            seller=self.seller,
            item_type=cleaning_type,
            title="Bathroom scrub brush",
            description="A brush for cleaning shower tile and grout.",
            listing_price="8.00",
            condition=Listing.Condition.GOOD,
            status=Listing.Status.ACTIVE,
            fulfillment_option=Listing.Fulfillment.PICKUP,
        )
        table = Listing.objects.create(
            seller=self.seller,
            item_type=furniture_type,
            title="Small Coffee Table",
            description="A compact table for a living room.",
            listing_price="30.00",
            condition=Listing.Condition.GOOD,
            status=Listing.Status.ACTIVE,
            fulfillment_option=Listing.Fulfillment.PICKUP,
        )
        television = Listing.objects.create(
            seller=self.seller,
            item_type=television_type,
            title="Refurbished Flatscreen",
            description="A television for streaming shows.",
            listing_price="85.00",
            condition=Listing.Condition.GOOD,
            status=Listing.Status.ACTIVE,
            fulfillment_option=Listing.Fulfillment.PICKUP,
        )
        generate_response.return_value = (
            f'{{"ids":[{table.pk},{relevant.pk},{television.pk}]}}'
        )

        response = self.client.get(
            reverse("home"), {"q": "bathroom cleaning", "search_mode": "ai"}
        )

        self.assertEqual(
            [listing.pk for listing in response.context["listings"]], [relevant.pk]
        )
        self.assertFalse(response.context["ai_search_fallback"])
        self.assertNotContains(response, "Small Coffee Table")
        self.assertNotContains(response, "Refurbished Flatscreen")

    @patch("marketplace.browse.rank_listing_ids")
    def test_database_recheck_excludes_inactive_model_ids(self, rank_listing_ids):
        rank_listing_ids.return_value = [self.inactive.pk, self.second.pk]

        response = self.client.get(
            reverse("home"), {"q": "bedroom lamp", "search_mode": "ai"}
        )

        self.assertEqual(
            [listing.pk for listing in response.context["listings"]],
            [self.second.pk],
        )

    @patch("marketplace.local_llm._generate_response", side_effect=RuntimeError("unavailable"))
    def test_model_failure_shows_random_filtered_fallback_not_keyword_results(
        self, generate_response
    ):
        with self.assertLogs("marketplace.local_llm", level="ERROR") as server_log:
            response = self.client.get(
                reverse("home"),
                {
                    "q": "Oak bedside lamp",
                    "search_mode": "ai",
                    "max_price": "20",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertIn("loading or inference failed", server_log.output[0])
        self.assertFalse(response.context["ai_search_error"])
        self.assertTrue(response.context["ai_search_fallback"])
        self.assertEqual(
            [listing.pk for listing in response.context["listings"]],
            [self.second.pk],
        )
        self.assertEqual(
            response.context["ai_search_fallback_title"],
            "AI search couldn't be completed.",
        )
        self.assertContains(response, "They are not AI recommendations.")

    @patch(
        "marketplace.browse._local_llm_candidates",
        side_effect=OperationalError("candidate query failed"),
    )
    def test_candidate_query_failure_shows_random_active_filtered_fallback(
        self, candidate_query
    ):
        with self.assertLogs("marketplace.browse", level="ERROR") as server_log:
            response = self.client.get(
                reverse("home"),
                {
                    "q": "bathroom cleaning",
                    "search_mode": "ai",
                    "max_price": "20",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertIn("candidate query failed", server_log.output[0])
        self.assertTrue(response.context["ai_search_fallback"])
        self.assertEqual(
            [listing.pk for listing in response.context["listings"]],
            [self.second.pk],
        )
        self.assertEqual(
            response.context["ai_search_fallback_title"],
            "AI search couldn't be completed.",
        )
        self.assertContains(response, "random available listings")
        self.assertContains(response, "not AI recommendations")
        candidate_query.assert_called_once()

    @patch("marketplace.browse._random_filtered_listings", return_value=None)
    @patch(
        "marketplace.browse._local_llm_candidates",
        side_effect=OperationalError("candidate query failed"),
    )
    def test_candidate_and_fallback_query_failures_show_error_without_listings(
        self, candidate_query, fallback_query
    ):
        response = self.client.get(
            reverse("home"),
            {"q": "bathroom cleaning", "search_mode": "ai"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["ai_search_error"])
        self.assertFalse(response.context["ai_search_fallback"])
        self.assertEqual(response.context["listings"], [])
        self.assertContains(response, "AI search could not load listings right now.")
        fallback_query.assert_called_once()

    @patch("marketplace.local_llm._generate_response")
    def test_ai_mode_applies_structured_filters_without_keyword_prefilter(
        self, generate_response
    ):
        generate_response.return_value = (
            f'{{"ids":[{self.first.pk},{self.second.pk}]}}'
        )

        response = self.client.get(
            reverse("home"),
            {
                "q": "minimal bedroom lamp",
                "search_mode": "ai",
                "category": str(self.first.item_type.category_id),
                "min_price": "20",
                "max_price": "30",
                "condition": Listing.Condition.GOOD,
            },
        )

        self.assertEqual(
            [listing.pk for listing in response.context["listings"]],
            [self.first.pk],
        )
        self.assertEqual(response.context["search_mode"], "ai")
        model_catalog = json.loads(
            generate_response.call_args.args[0][1]["content"]
        )["candidate_listings"]
        self.assertEqual([item["id"] for item in model_catalog], [self.first.pk])
        self.assertIn("search_mode=ai", response.context["filter_chips"][0]["url"])

    @patch("marketplace.local_llm._generate_response")
    def test_both_browse_pages_support_ai_mode(self, generate_response):
        generate_response.return_value = f'{{"ids":[{self.first.pk}]}}'

        for route_name in ("home", "listing-list-url"):
            with self.subTest(route_name=route_name):
                response = self.client.get(
                    reverse(route_name), {"q": "bedroom lamp", "search_mode": "ai"}
                )
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, 'name="search_mode"')
                self.assertContains(response, 'name="search_mode" value="ai"')
                self.assertContains(response, 'role="switch"')
                self.assertContains(response, 'data-search-mode-toggle')
                self.assertContains(response, 'data-search-mode-info')
                self.assertContains(response, 'class="search-mode-icon"')
                self.assertContains(response, "Turn on the switch for natural-language search")
                self.assertNotContains(response, 'class="search-info-button"')
                self.assertNotContains(response, '<select id="search-mode"')
                self.assertContains(response, "data-ai-search-status")
                self.assertEqual(response.context["search_mode"], "ai")
                if route_name == "listing-list-url":
                    self.assertContains(response, 'action="/listings/"')

    @patch("marketplace.local_llm._generate_response", return_value='{"ids":[999]}')
    def test_hallucinated_only_ids_show_random_filtered_fallback(
        self, generate_response
    ):
        with self.assertLogs("marketplace.local_llm", level="WARNING") as server_log:
            response = self.client.get(
                reverse("home"),
                {
                    "q": "bathroom cleaning",
                    "search_mode": "ai",
                    "min_price": "20",
                    "category": str(self.first.item_type.category_id),
                },
            )

        self.assertFalse(response.context["ai_search_error"])
        self.assertTrue(response.context["ai_search_fallback"])
        self.assertEqual(response.context["listings"], [self.first])
        self.assertTrue(any("no valid candidate IDs" in line for line in server_log.output))
        self.assertContains(response, "No relevant listings found for this search.")
        self.assertContains(response, "not AI recommendations.")
        self.assertContains(response, "data-ai-search-toast")

    @patch("marketplace.local_llm._generate_response", return_value='{"ids":[]}')
    def test_empty_model_ids_show_random_filtered_fallback(self, generate_response):
        response = self.client.get(
            reverse("home"),
            {
                "q": "bathroom cleaning",
                "search_mode": "ai",
                "min_price": "20",
                "condition": Listing.Condition.GOOD,
            },
        )

        self.assertTrue(response.context["ai_search_fallback"])
        self.assertEqual(response.context["listings"], [self.first])
        self.assertContains(response, "data-ai-search-toast")

    @patch("marketplace.local_llm._generate_response", return_value='{"ids":[]}')
    def test_candidate_pool_has_a_fixed_limit(self, generate_response):
        for index in range(45):
            Listing.objects.create(
                seller=self.seller,
                item_type=self.first.item_type,
                title=f"Bedroom lamp {index}",
                listing_price="12.00",
                condition=Listing.Condition.GOOD,
                status=Listing.Status.ACTIVE,
                fulfillment_option=Listing.Fulfillment.PICKUP,
            )

        self.client.get(
            reverse("home"), {"q": "bedroom lamp", "search_mode": "ai"}
        )

        catalog = generate_response.call_args.args[0][1]["content"]
        self.assertLessEqual(catalog.count('"id":'), 40)
