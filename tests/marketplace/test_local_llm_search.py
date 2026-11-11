import json
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse

from marketplace.local_llm import LocalLLMError, parse_listing_ids, rank_listing_ids
from marketplace.models import ItemCategory, ItemType, Listing, User
from marketplace.search_semantic import SemanticSearchError, retrieve


class FakeEncoder:
    def encode(self, texts, normalize_embeddings=True):
        vectors = {"relevant": [1.0, 0.0], "weak": [0.2, 0.98],
                   "unrelated": [0.0, 1.0]}
        return [vectors[next(key for key in vectors if key in text)] for text in texts]


class SemanticRetrievalTests(TestCase):
    def test_ranks_relevant_candidates_and_rejects_unrelated_ones(self):
        candidates = [{"pk": 3, "title": "unrelated"},
                      {"pk": 2, "title": "weak"},
                      {"pk": 1, "title": "relevant"}]
        results = retrieve("relevant", candidates, model=FakeEncoder())
        self.assertEqual([item["pk"] for item, _ in results], [1])


class ListingIdValidationTests(TestCase):
    def test_validates_ids(self):
        self.assertEqual(parse_listing_ids('{"ids":[4,4,99,true,3,2,1,5,6]}', range(1, 7)),
                         [4, 3, 2, 1, 5])
        self.assertEqual(parse_listing_ids('{"ids":[]}', [1]), [])
        with self.assertRaises(LocalLLMError):
            parse_listing_ids("not json", [1])
        with self.assertRaises(LocalLLMError):
            parse_listing_ids('{"ids":[999]}', [1])

    def test_accepts_near_miss_formats_from_the_3b_model(self):
        self.assertEqual(parse_listing_ids('```json\n{"ids":[2,1]}\n```', [1, 2]), [2, 1])
        self.assertEqual(parse_listing_ids('[{"ids":[2]}]', [1, 2]), [2])
        self.assertEqual(parse_listing_ids("[6]", [6]), [6])

    def test_still_rejects_prose_code_and_ambiguous_lists(self):
        for response in (
            "```json\ndef rank_marketplace_listings(candidates):",
            "The only matching item is a Microwave.",
            '[{"ids":[1]},{"ids":[2]}]',
            '[1, "2"]',
        ):
            with self.subTest(response=response), self.assertRaises(LocalLLMError):
                parse_listing_ids(response, [1, 2])


class RelevanceGateTests(TestCase):
    @patch("marketplace.local_llm._generate_response", return_value='{"ids":[1,2]}')
    def test_sit_keeps_seating_and_rejects_coffee_table(self, generate):
        candidates = [
            {"pk": 1, "title": "Coffee table", "category": "Furniture / Tables",
             "description": "Oak table", "listing_price": "20", "condition": "good"},
            {"pk": 2, "title": "Armchair", "category": "Furniture / Chairs",
             "description": "Comfy chair", "listing_price": "30", "condition": "good"},
        ]
        self.assertEqual(rank_listing_ids("sit", candidates), [2])

    @patch("marketplace.local_llm._generate_response", return_value='{"ids":[1]}')
    def test_free_text_does_not_require_every_query_word(self, generate):
        candidates = [
            {"pk": 1, "title": "Blue reading lamp", "category": "Lighting",
             "description": "Reading light", "listing_price": "20", "condition": "good"},
        ]
        self.assertEqual(rank_listing_ids(
            "need something blue to complement my bedside lamps", candidates,
        ), [1])


class LocalLLMSearchViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.seller = User.objects.create_user(username="seller", email="seller@example.com")
        category = ItemCategory.objects.create(category_name="Furniture")
        kind = ItemType.objects.create(category=category, item_type_name="Lamp")
        cls.first = cls._listing(kind, "Oak bedside lamp", "Warm bedroom light", "25.00")
        cls.second = cls._listing(kind, "Blue reading lamp", "Light for reading", "18.00")
        cls.inactive = cls._listing(kind, "Inactive lamp", "", "10.00", Listing.Status.INACTIVE)

    @classmethod
    def _listing(cls, kind, title, description, price, status=Listing.Status.ACTIVE):
        return Listing.objects.create(
            seller=cls.seller, item_type=kind, title=title, description=description,
            listing_price=price, condition=Listing.Condition.GOOD, status=status,
            fulfillment_option=Listing.Fulfillment.PICKUP,
        )

    def _get(self, query="bedroom lighting", **filters):
        return self.client.get(reverse("home"), {"q": query, "search_mode": "ai", **filters})

    @patch("marketplace.browse.retrieve")
    @patch("marketplace.local_llm._generate_response")
    def test_irrelevant_dresser_cannot_return_through_ai_or_fallback(self, generate, semantic):
        dresser = self._listing(self.first.item_type, "Wood dresser", "Bedroom storage", "40")
        semantic.side_effect = lambda query, candidates: [
            (item, .8) for item in candidates if item["pk"] == dresser.pk
        ]
        for model_response in (json.dumps({"ids": [dresser.pk]}), '{"ids":[]}', RuntimeError("offline")):
            with self.subTest(model_response=model_response):
                generate.side_effect = model_response if isinstance(model_response, Exception) else None
                generate.return_value = model_response
                response = self._get("bathroom cleaning")
                self.assertEqual(response.context["listings"], [])
                self.assertFalse(response.context["ai_search_fallback"])

    @patch("marketplace.browse.retrieve")
    @patch("marketplace.local_llm._generate_response")
    def test_model_order_and_filters(self, generate, semantic):
        semantic.side_effect = lambda query, candidates: [(item, .8) for item in candidates]
        generate.return_value = json.dumps({"ids": [self.second.pk, self.first.pk]})
        response = self._get()
        self.assertEqual([item.pk for item in response.context["listings"]],
                         [self.second.pk, self.first.pk])
        self.assertFalse(response.context["ai_search_fallback"])
        catalog = json.loads(generate.call_args.args[0][1]["content"])["candidate_listings"]
        self.assertEqual({item["id"] for item in catalog}, {self.first.pk, self.second.pk})
        self._get(max_price="20")
        self.assertEqual([item["pk"] for item in semantic.call_args.args[1]], [self.second.pk])

    @patch("marketplace.browse.retrieve", return_value=[])
    def test_no_relevant_candidates_has_empty_state(self, semantic):
        response = self._get("unrelated request")
        self.assertEqual(response.context["listings"], [])
        self.assertContains(response, "No relevant listings found")

    @patch("marketplace.browse.retrieve", side_effect=SemanticSearchError("offline"))
    def test_embedding_failure_shows_unavailable_state(self, semantic):
        response = self._get()
        self.assertEqual(response.context["listings"], [])
        self.assertContains(response, "AI search is unavailable right now")

    @patch("marketplace.browse.retrieve")
    @patch("marketplace.local_llm._generate_response", side_effect=RuntimeError("offline"))
    def test_model_failure_shows_labeled_semantic_results(self, generate, semantic):
        semantic.side_effect = lambda query, candidates: [(item, .8) for item in candidates]
        response = self._get(max_price="20")
        self.assertEqual([item.pk for item in response.context["listings"]], [self.second.pk])
        self.assertTrue(response.context["ai_search_fallback"])
        self.assertContains(response, "Showing semantic search matches")
        self.assertContains(response, "Llama ranking could not be completed")

    @patch("marketplace.browse.retrieve")
    @patch("marketplace.local_llm._generate_response", return_value='{"ids":[]}')
    def test_empty_llama_result_uses_confident_semantic_matches(self, generate, semantic):
        semantic.side_effect = lambda query, candidates: [(item, .8) for item in candidates]
        response = self._get()
        self.assertEqual([item.pk for item in response.context["listings"]],
                         [self.first.pk, self.second.pk])
        self.assertTrue(response.context["ai_search_fallback"])
        self.assertContains(response, "Llama did not select any listings")

    @patch("marketplace.browse.retrieve")
    @patch("marketplace.local_llm._generate_response", return_value='{"ids":[]}')
    def test_empty_llama_result_with_weak_matches_is_empty(self, generate, semantic):
        semantic.side_effect = lambda query, candidates: [(item, .35) for item in candidates]
        response = self._get()
        self.assertEqual(response.context["listings"], [])
        self.assertContains(response, "No relevant listings found")

    @patch("marketplace.browse.retrieve")
    @patch("marketplace.local_llm._generate_response", return_value='{"ids":[999]}')
    def test_invalid_ids_use_semantic_fallback(self, generate, semantic):
        semantic.side_effect = lambda query, candidates: [(item, .8) for item in candidates]
        response = self._get(max_price="20")
        self.assertEqual([item.pk for item in response.context["listings"]], [self.second.pk])
        self.assertTrue(response.context["ai_search_fallback"])

    @patch("marketplace.browse.retrieve")
    @patch("marketplace.local_llm._generate_response")
    def test_llama_cannot_promote_an_unretrieved_listing(self, generate, semantic):
        semantic.side_effect = lambda query, candidates: [(candidates[0], .8)]
        generate.return_value = json.dumps({"ids": [self.second.pk]})
        response = self._get()
        self.assertEqual([item.pk for item in response.context["listings"]], [self.first.pk])
        self.assertTrue(response.context["ai_search_fallback"])

    @patch("marketplace.browse.retrieve")
    def test_structured_filters_apply_before_semantic_ranking(self, semantic):
        semantic.return_value = []
        self._get(max_price="20", condition=Listing.Condition.GOOD,
                  category=str(self.first.item_type.category_id),
                  fulfillment=Listing.Fulfillment.PICKUP)
        self.assertEqual([item["pk"] for item in semantic.call_args.args[1]], [self.second.pk])

    @patch("marketplace.browse.retrieve")
    def test_retrieval_receives_all_eligible_listings(self, semantic):
        for index in range(45):
            self._listing(self.first.item_type, f"Lamp {index}", "", "12.00")
        semantic.return_value = []
        self._get()
        self.assertEqual(len(semantic.call_args.args[1]), 47)
