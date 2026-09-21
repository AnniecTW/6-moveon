from django.test import TestCase, override_settings
from django.urls import reverse

from marketplace.models import ItemCategory, ItemType, Listing, User
from messaging.models import Conversation, Message

from .models import Bundle, BundleItem


@override_settings(GEMINI_API_KEY="")
class BundleWizardTests(TestCase):
    """
    GEMINI_API_KEY is forced blank here regardless of the developer's local
    .env, so these tests always exercise the deterministic heuristic path -
    fast, free, and not dependent on network access or a real API key/quota.
    The heuristic's price-ordering behavior is exactly what these tests
    assert on; LLM prompt/response handling is a separate concern (see
    generate_bundle_tiers' own validation logic in services.py) that would
    need mocked API responses to test in isolation, not real network calls.
    """
    @classmethod
    def setUpTestData(cls):
        cls.buyer = User.objects.create_user(
            username="buyer", email="buyer@example.com", display_name="Buyer"
        )
        cls.seller_a = User.objects.create_user(
            username="seller_a", email="seller_a@example.com", display_name="Seller A"
        )
        cls.seller_b = User.objects.create_user(
            username="seller_b", email="seller_b@example.com", display_name="Seller B"
        )
        furniture = ItemCategory.objects.create(category_name="Furniture")
        decor = ItemCategory.objects.create(category_name="Home Decor")
        cls.sofa_type = ItemType.objects.create(
            category=furniture, item_type_name="Sofa"
        )
        cls.rug_type = ItemType.objects.create(category=decor, item_type_name="Rug")
        cls.lamp_type = ItemType.objects.create(category=decor, item_type_name="Lamp")

        def make_listing(title, seller, item_type, price, **extra):
            return Listing.objects.create(
                seller=seller,
                item_type=item_type,
                title=title,
                condition=Listing.Condition.GOOD,
                listing_price=price,
                fulfillment_option=Listing.Fulfillment.PICKUP,
                status=Listing.Status.ACTIVE,
                bundle_eligible=True,
                **extra,
            )

        cls.cheap_sofa = make_listing("Cheap Sofa", cls.seller_a, cls.sofa_type, 40)
        cls.pricey_sofa = make_listing("Pricey Sofa", cls.seller_b, cls.sofa_type, 120)
        cls.buyers_own_sofa = make_listing(
            "Buyer's Own Sofa", cls.buyer, cls.sofa_type, 1
        )
        cls.rug = make_listing("Only Rug", cls.seller_a, cls.rug_type, 25)
        cls.lamp = make_listing("Only Lamp", cls.seller_b, cls.lamp_type, 15)

    def setUp(self):
        self.client.force_login(self.buyer)

    def _start_wizard(self, space="LIVING_ROOM", item_type_ids=None):
        item_type_ids = item_type_ids or [
            self.sofa_type.id,
            self.rug_type.id,
            self.lamp_type.id,
        ]
        self.client.post(reverse("bundles:select_space"), {"space": space})
        response = self.client.post(
            reverse("bundles:select_categories"), {"categories": item_type_ids}
        )
        bundle_id = int(response["Location"].split("bundle=")[1])
        return Bundle.objects.get(pk=bundle_id)

    def test_start_modal_fragment_renders_all_spaces(self):
        response = self.client.get(reverse("bundles:start_modal"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "data-bundle-start-dialog")
        self.assertContains(response, 'data-space-panel="LIVING_ROOM"')
        self.assertContains(response, "Sofa")

    def test_start_endpoint_creates_bundle_and_redirects_to_generating(self):
        response = self.client.post(
            reverse("bundles:start"),
            {
                "space": "LIVING_ROOM",
                "categories": [self.sofa_type.id, self.rug_type.id, self.lamp_type.id],
            },
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn(reverse("bundles:generating"), payload["redirect_url"])

        bundle_id = int(payload["redirect_url"].split("bundle=")[1])
        bundle = Bundle.objects.get(pk=bundle_id)
        self.assertEqual(bundle.buyer, self.buyer)
        self.assertEqual(bundle.space, "LIVING_ROOM")
        self.assertEqual(bundle.requested_categories.count(), 3)

    def test_start_endpoint_rejects_invalid_space(self):
        response = self.client.post(
            reverse("bundles:start"),
            {"space": "NOT_A_REAL_SPACE", "categories": [self.sofa_type.id]},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("error", response.json())

    def test_start_endpoint_ignores_disabled_categories(self):
        # A category that shows as unavailable in the popup is disabled in
        # the HTML, but the endpoint must not trust that alone - a crafted
        # POST including it should be silently dropped, not accepted.
        curtains_type = ItemType.objects.create(
            category=self.rug_type.category, item_type_name="Curtains"
        )  # zero listings anywhere - not currently in SPACE_ITEM_TYPES, so
        # only reachable by a direct POST, which is exactly the case being
        # tested here.
        response = self.client.post(
            reverse("bundles:start"),
            {
                "space": "LIVING_ROOM",
                "categories": [self.sofa_type.id, curtains_type.id],
            },
        )
        payload = response.json()
        bundle_id = int(payload["redirect_url"].split("bundle=")[1])
        bundle = Bundle.objects.get(pk=bundle_id)
        self.assertEqual(
            list(bundle.requested_categories.values_list("item_type_id", flat=True)),
            [self.sofa_type.id],
        )

    def test_select_categories_redirects_to_generating_not_builder(self):
        self.client.post(reverse("bundles:select_space"), {"space": "LIVING_ROOM"})
        response = self.client.post(
            reverse("bundles:select_categories"),
            {"categories": [self.sofa_type.id, self.rug_type.id, self.lamp_type.id]},
        )
        self.assertIn(reverse("bundles:generating"), response["Location"])
        bundle_id = int(response["Location"].split("bundle=")[1])
        # Generation should NOT have run yet - that's the whole point of the
        # interstitial (it runs from the generating page's own fetch call).
        self.assertNotIn(
            str(bundle_id), self.client.session.get("bundle_generations", {})
        )

    def test_generating_page_then_generate_endpoint_then_builder(self):
        bundle = self._start_wizard()
        generating_url = f"{reverse('bundles:generating')}?bundle={bundle.id}"

        response = self.client.get(generating_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Generating")

        generate_response = self.client.post(
            f"{reverse('bundles:generate')}?bundle={bundle.id}"
        )
        self.assertEqual(generate_response.status_code, 200)
        payload = generate_response.json()
        self.assertIn(f"bundle={bundle.id}", payload["redirect_url"])
        self.assertIn(reverse("bundles:builder"), payload["redirect_url"])

        # Now that generation is cached, revisiting the interstitial should
        # skip straight to the builder instead of showing the animation again.
        response = self.client.get(generating_url)
        self.assertRedirects(response, f"{reverse('bundles:builder')}?bundle={bundle.id}")

    def test_generate_endpoint_reports_error_when_only_candidate_is_buyers_own(self):
        # A category can show as "available" on Screen 2 (any bundle-eligible
        # listing exists for it, buyer-agnostic per available_item_types_for_space)
        # yet still end up with zero real candidates once buyer-exclusion
        # applies - this is the realistic way generation ends up empty,
        # since a category with literally zero listings can't be selected
        # in the first place (the form's choices already exclude it).
        curtains_type = ItemType.objects.create(
            category=self.rug_type.category, item_type_name="Curtains"
        )
        Listing.objects.create(
            seller=self.buyer,
            item_type=curtains_type,
            title="Buyer's Own Curtains",
            condition=Listing.Condition.GOOD,
            listing_price=10,
            fulfillment_option=Listing.Fulfillment.PICKUP,
            status=Listing.Status.ACTIVE,
            bundle_eligible=True,
        )
        bundle = self._start_wizard(item_type_ids=[curtains_type.id])

        response = self.client.post(f"{reverse('bundles:generate')}?bundle={bundle.id}")
        payload = response.json()
        self.assertEqual(payload["redirect_url"], reverse("bundles:select_categories"))

    def test_full_wizard_happy_path(self):
        bundle = self._start_wizard()

        builder_url = f"{reverse('bundles:builder')}?bundle={bundle.id}"
        response = self.client.get(builder_url)
        self.assertEqual(response.status_code, 200)

        # Regression check: the generation dict is read back from the
        # session between requests, and Django's session backend silently
        # stringifies dict keys on the JSON round-trip. A prior version of
        # this view matched item_type_id (int) against those keys directly
        # and always missed, silently rendering "No listing available" for
        # every category despite BundleItem rows being created correctly
        # underneath - so this needs an actual content assertion, not just
        # a DB check, to catch it.
        self.assertNotContains(response, "No listing available")
        self.assertContains(response, "Sofa")

        bundle.refresh_from_db()
        self.assertEqual(bundle.selected_tier, "BEST_VALUE")
        self.assertEqual(BundleItem.objects.filter(bundle=bundle).count(), 3)

        summary_url = f"{reverse('bundles:summary')}?bundle={bundle.id}"
        response = self.client.post(summary_url)
        self.assertRedirects(response, summary_url)

        bundle.refresh_from_db()
        self.assertEqual(bundle.status, Bundle.Status.REQUESTS_SENT)
        self.assertEqual(
            BundleItem.objects.filter(
                bundle=bundle, item_status=BundleItem.ItemStatus.REQUESTED
            ).count(),
            3,
        )
        self.assertEqual(Conversation.objects.filter(buyer=self.buyer).count(), 3)
        self.assertEqual(Message.objects.filter(sender=self.buyer).count(), 3)

    def test_buyer_never_matched_with_own_listing(self):
        bundle = self._start_wizard()

        for tier in ["BUDGET", "BEST_VALUE", "PREMIUM"]:
            self.client.get(
                f"{reverse('bundles:builder')}?bundle={bundle.id}&tier={tier}"
            )
            sofa_item = BundleItem.objects.get(
                bundle=bundle, listing__item_type=self.sofa_type
            )
            self.assertNotEqual(sofa_item.listing_id, self.buyers_own_sofa.id)

    def test_heuristic_tiers_are_price_ordered(self):
        bundle = self._start_wizard()

        self.client.get(f"{reverse('bundles:builder')}?bundle={bundle.id}&tier=BUDGET")
        budget_sofa = BundleItem.objects.get(
            bundle=bundle, listing__item_type=self.sofa_type
        )
        self.assertEqual(budget_sofa.listing_id, self.cheap_sofa.id)

        self.client.get(
            f"{reverse('bundles:builder')}?bundle={bundle.id}&tier=PREMIUM"
        )
        premium_sofa = BundleItem.objects.get(
            bundle=bundle, listing__item_type=self.sofa_type
        )
        self.assertEqual(premium_sofa.listing_id, self.pricey_sofa.id)

    def test_swap_persists_after_page_reload(self):
        bundle = self._start_wizard()
        builder_url = f"{reverse('bundles:builder')}?bundle={bundle.id}"
        self.client.get(builder_url)
        bundle.refresh_from_db()

        sofa_item = BundleItem.objects.get(bundle=bundle, listing__item_type=self.sofa_type)
        other_sofa = (
            self.cheap_sofa if sofa_item.listing_id != self.cheap_sofa.id else self.pricey_sofa
        )

        self.client.post(
            builder_url,
            {
                "action": "swap",
                "tier": bundle.selected_tier,
                "item_type_id": self.sofa_type.id,
                "listing_id": other_sofa.id,
            },
        )
        # A swap deletes the old BundleItem row and creates a new one (a
        # different pk), so re-query rather than refresh_from_db the stale
        # instance.
        swapped_item = BundleItem.objects.get(bundle=bundle, listing__item_type=self.sofa_type)
        self.assertEqual(swapped_item.listing_id, other_sofa.id)

        # Regression check: a prior version of BundleBuilderView.get()
        # unconditionally re-synced BundleItem rows from the tier's original
        # generated recipe on every GET - including the GET that a swap POST
        # redirects to - which silently discarded the swap the buyer just
        # made. Reloading the page (a plain GET with no tier change) must
        # preserve the swap, not revert it.
        self.client.get(builder_url)
        reloaded_item = BundleItem.objects.get(bundle=bundle, listing__item_type=self.sofa_type)
        self.assertEqual(reloaded_item.listing_id, other_sofa.id)

    def test_checkout_blocked_under_minimum_items(self):
        bundle = self._start_wizard(item_type_ids=[self.lamp_type.id])

        summary_url = f"{reverse('bundles:summary')}?bundle={bundle.id}"
        response = self.client.post(summary_url)
        self.assertRedirects(
            response, f"{reverse('bundles:builder')}?bundle={bundle.id}"
        )
        bundle.refresh_from_db()
        self.assertEqual(bundle.status, Bundle.Status.DRAFT)

    def test_builder_redirects_to_summary_after_requests_sent(self):
        bundle = self._start_wizard()
        self.client.get(f"{reverse('bundles:builder')}?bundle={bundle.id}")
        summary_url = f"{reverse('bundles:summary')}?bundle={bundle.id}"
        self.client.post(summary_url)

        response = self.client.get(f"{reverse('bundles:builder')}?bundle={bundle.id}")
        self.assertRedirects(response, summary_url)

    def test_anonymous_user_redirected_to_login(self):
        self.client.logout()
        response = self.client.get(reverse("bundles:select_space"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response["Location"])
