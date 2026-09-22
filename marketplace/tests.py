from django.test import TestCase
from django.urls import reverse

from .models import ItemCategory, ItemType, Listing, Transaction, User
from bundles.models import Bundle, BundleItem


class SellerListingsViewTests(TestCase):
	def setUp(self):
		self.user = User.objects.create_user(
			username="seller", email="seller@example.com", display_name="Test Seller"
		)
		category = ItemCategory.objects.create(category_name="Furniture")
		item_type = ItemType.objects.create(category=category, item_type_name="Desk")
		Listing.objects.create(
			seller=self.user,
			item_type=item_type,
			title="Study Desk",
			condition=Listing.Condition.GOOD,
			listing_price=40,
			benchmark_low=35,
			benchmark_high=55,
			fulfillment_option=Listing.Fulfillment.PICKUP,
			status=Listing.Status.ACTIVE,
		)

	def test_dashboard_is_authenticated_and_scoped_to_seller(self):
		response = self.client.get(reverse("seller-listings"))
		self.assertEqual(response.status_code, 302)

		self.client.force_login(self.user)
		response = self.client.get(reverse("seller-listings"))
		self.assertEqual(response.status_code, 200)
		self.assertContains(response, "Study Desk")
		self.assertContains(response, "My Listings (1)")

	def test_insights_is_authenticated_and_serializes_chart_data(self):
		response = self.client.get(reverse("seller-insights"))
		self.assertEqual(response.status_code, 302)

		self.client.force_login(self.user)
		response = self.client.get(reverse("seller-insights"))
		self.assertEqual(response.status_code, 200)
		self.assertContains(response, "Track how your listings are performing.")
		self.assertContains(response, 'id="seller-insights-data"')
		self.assertContains(response, 'aria-current="page" href="/seller/insights/"')

	def test_pricing_is_authenticated_and_uses_listing_data(self):
		response = self.client.get(reverse("seller-pricing"))
		self.assertEqual(response.status_code, 302)

		self.client.force_login(self.user)
		response = self.client.get(reverse("seller-pricing"))
		self.assertEqual(response.status_code, 200)
		self.assertContains(response, "Manage pricing plans and move-out deadlines.")
		self.assertContains(response, "Study Desk")
		self.assertContains(response, "Default selling preferences")
		self.assertContains(response, 'aria-current="page" href="/seller/pricing-and-moveout/"')

	def test_settings_is_authenticated_and_has_required_sections(self):
		response = self.client.get(reverse("seller-settings"))
		self.assertEqual(response.status_code, 302)

		self.client.force_login(self.user)
		response = self.client.get(reverse("seller-settings"))
		self.assertEqual(response.status_code, 200)
		for label in (
			"Payment details",
			"Default meet-up locations",
			"Delivery preferences",
			"Notifications",
		):
			self.assertContains(response, label)
		self.assertNotContains(response, "Account &amp; profile")
		self.assertNotContains(response, "Saved defaults")
		self.assertContains(response, 'aria-current="page" href="/seller/settings/"')

	def test_settings_are_validated_and_saved_in_session(self):
		self.client.force_login(self.user)
		response = self.client.post(
			reverse("seller-settings"),
			{
				"payment_preference": "meetup",
				"primary_meetup": "Main Library",
				"alternate_meetup": "Student Union",
				"delivery_preference": "local",
				"delivery_notes": "Within two miles of campus",
				"notify_inquiries": "on",
				"notify_pricing": "on",
			},
		)
		self.assertRedirects(response, reverse("seller-settings"))
		self.assertEqual(
			self.client.session["seller_settings"]["primary_meetup"],
			"Main Library",
		)

		response = self.client.post(
			reverse("seller-settings"),
			{
				"payment_preference": "meetup",
				"delivery_preference": "local",
				"delivery_notes": "",
			},
		)
		self.assertEqual(response.status_code, 200)
		self.assertContains(response, "Add a short delivery area")

	def test_buyer_pickups_is_authenticated_and_scoped_to_buyer(self):
		response = self.client.get(reverse("buyer-pickups"))
		self.assertEqual(response.status_code, 302)

		buyer = User.objects.create_user(
			username="buyer", email="buyer@example.com", display_name="Test Buyer"
		)
		listing = Listing.objects.get(title="Study Desk")
		Transaction.objects.create(
			listing=listing,
			buyer=buyer,
			seller=self.user,
			agreed_price=35,
			benchmark_price_snapshot=55,
			status=Transaction.Status.PENDING_PICKUP,
			meetup_location="Main Library",
		)
		self.client.force_login(buyer)
		response = self.client.get(reverse("buyer-pickups"))
		self.assertEqual(response.status_code, 200)
		self.assertContains(response, "Study Desk")
		self.assertContains(response, "Main Library")
		self.assertContains(response, "Confirm Item Received &amp; Complete Order")
		self.assertContains(response, 'aria-current="page" href="/buyer/pickups/"')
		self.assertContains(response, 'data-chart-date="start"')
		self.assertContains(response, 'data-chart-date="end"')
		self.assertContains(response, 'value="pickup" data-chart-type checked')
		self.assertContains(response, 'value="history" data-chart-type checked')
		self.assertContains(response, 'id="buyer-chart-data"')
		for removed_text in (
			"Download Purchase Receipts",
			"Good finds. A brighter tomorrow",
			"View Location on Map",
			"Upcoming Schedule",
			"Pickup Checklist",
		):
			self.assertNotContains(response, removed_text)

	def test_saved_bundles_is_authenticated_and_uses_bundle_items(self):
		response = self.client.get(reverse("buyer-bundles"))
		self.assertEqual(response.status_code, 302)

		buyer = User.objects.create_user(
			username="bundle-buyer",
			email="bundle-buyer@example.com",
			display_name="Bundle Buyer",
		)
		bundle = Bundle.objects.create(
			buyer=buyer,
			space=Bundle.Space.BEDROOM,
			selected_tier=Bundle.Tier.BEST_VALUE,
			status=Bundle.Status.PARTIALLY_ACCEPTED,
		)
		BundleItem.objects.create(
			bundle=bundle,
			listing=Listing.objects.get(title="Study Desk"),
			listing_price_snapshot=40,
			proposed_bundle_price=35,
			item_status=BundleItem.ItemStatus.ACCEPTED,
		)
		self.client.force_login(buyer)
		response = self.client.get(reverse("buyer-bundles"))
		self.assertEqual(response.status_code, 200)
		self.assertContains(response, "Bedroom Move-In Bundle")
		self.assertContains(response, "Study Desk")
		self.assertContains(response, "Confirmed")
		self.assertContains(response, "Target budget")
		self.assertContains(response, 'aria-current="page" href="/buyer/saved-bundles/"')
		self.assertNotContains(response, "Bundle Tips &amp; Next Steps")

	def test_purchase_history_and_csv_are_authenticated_and_buyer_scoped(self):
		self.assertEqual(self.client.get(reverse("buyer-purchase-history")).status_code, 302)
		self.assertEqual(self.client.get(reverse("buyer-purchase-history-csv")).status_code, 302)

		buyer = User.objects.create_user(
			username="history-buyer", email="history@example.com", display_name="History Buyer"
		)
		other_buyer = User.objects.create_user(
			username="other-buyer", email="other@example.com", display_name="Other Buyer"
		)
		listing = Listing.objects.get(title="Study Desk")
		Transaction.objects.create(
			listing=listing,
			buyer=buyer,
			seller=self.user,
			agreed_price=30,
			benchmark_price_snapshot=55,
			status=Transaction.Status.COMPLETED,
		)
		Transaction.objects.create(
			listing=listing,
			buyer=other_buyer,
			seller=self.user,
			agreed_price=24,
			status=Transaction.Status.COMPLETED,
		)

		self.client.force_login(buyer)
		response = self.client.get(reverse("buyer-purchase-history"))
		self.assertEqual(response.status_code, 200)
		self.assertContains(response, "Study Desk")
		self.assertContains(response, "$25 saved vs. retail")
		self.assertContains(response, "All-time Spend")
		self.assertContains(response, "All-time Savings")
		self.assertContains(response, "Download Purchase Receipts (CSV)")
		self.assertContains(response, 'aria-current="page" href="/buyer/purchase-history/"')

		csv_response = self.client.get(reverse("buyer-purchase-history-csv"))
		self.assertEqual(csv_response.status_code, 200)
		self.assertEqual(csv_response["Content-Type"], "text/csv")
		csv_text = csv_response.content.decode()
		self.assertIn("Study Desk", csv_text)
		self.assertIn("30.00", csv_text)
		self.assertNotIn("24.00", csv_text)

	def test_watchlist_is_authenticated_and_exposes_model_backed_candidates(self):
		self.assertEqual(self.client.get(reverse("buyer-watchlist")).status_code, 302)
		buyer = User.objects.create_user(
			username="watchlist-buyer",
			email="watchlist@example.com",
			display_name="Watchlist Buyer",
		)
		self.client.force_login(buyer)
		response = self.client.get(reverse("buyer-watchlist"))
		self.assertEqual(response.status_code, 200)
		self.assertContains(response, "Study Desk")
		self.assertContains(response, "$40")
		self.assertContains(response, "Message Seller")
		self.assertContains(response, "Add to Bundle")
		self.assertContains(response, "Remove from Watchlist")
		self.assertContains(response, "All Categories")
		self.assertContains(response, "Sort: Recently Added")
		self.assertContains(response, "watchlist-heart")
		self.assertContains(response, 'aria-current="page" href="/buyer/watchlist/"')
		for removed_text in ("Price dropped!", "people interested"):
			self.assertNotContains(response, removed_text)
