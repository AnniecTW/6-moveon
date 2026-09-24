from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import ItemCategory, ItemType, Listing, ListingImage, Transaction, User, WatchlistItem
from bundles.models import Bundle, BundleItem
from messaging.models import Conversation, Message


class SellerListingsViewTests(TestCase):
	def test_profile_requires_canonical_campus_verification(self):
		User.objects.filter(pk=self.user.pk).update(email_verified_at=None)
		self.client.force_login(self.user)
		for route in ("seller-listings", "seller-settings", "buyer-pickups", "buyer-bundles", "buyer-purchase-history", "buyer-purchase-history-csv", "buyer-watchlist"):
			response = self.client.get(reverse(route))
			self.assertRedirects(response, reverse("account") + "?next=" + reverse(route).replace("/", "%2F"), fetch_redirect_response=False)

	def test_profile_reuses_images_header_and_edit_route(self):
		listing = Listing.objects.get(title="Study Desk")
		ListingImage.objects.create(listing=listing, uploaded_by=self.user, external_url="https://example.invalid/current-photo.jpg")
		self.client.force_login(self.user)
		response = self.client.get(reverse("seller-listings"))
		self.assertContains(response, "https://example.invalid/current-photo.jpg")
		self.assertContains(response, reverse("listing-update-url", args=[listing.pk]))
		self.assertContains(response, 'data-unread-url="' + reverse("messaging_unread") + '"')
		self.assertNotContains(response, "Verify account")
		self.assertNotContains(response, "Admin session")

	def test_preview_and_head_do_not_increment_public_views(self):
		listing = Listing.objects.get(title="Study Desk")
		self.client.head(reverse("listing-detail-url", args=[listing.pk]))
		listing.status = Listing.Status.DRAFT
		listing.save()
		self.client.force_login(self.user)
		self.assertEqual(self.client.get(reverse("listing-preview-url", args=[listing.pk])).status_code, 200)
		listing.refresh_from_db()
		self.assertEqual(listing.views, 0)

	def setUp(self):
		self.user = User.objects.create_user(email_verified=True, email_verified_at=timezone.now(),
			username="seller", email="seller@illinois.edu", display_name="Test Seller"
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

	def test_profile_routes_are_unified_and_insights_is_removed(self):
		self.assertEqual(reverse("seller-listings"), "/profile/listings/")
		self.assertEqual(reverse("seller-settings"), "/profile/settings/")
		self.assertEqual(reverse("buyer-pickups"), "/profile/pickups/")
		self.assertEqual(self.client.get("/seller/insights/").status_code, 404)
		self.client.force_login(self.user)
		response = self.client.get(reverse("seller-listings"))
		self.assertContains(response, "Listing Summary")
		self.assertContains(response, "Purchases")
		self.assertContains(response, "Total Earned vs. Total Spent")
		self.assertNotContains(response, "Net balance")
		self.assertNotContains(response, "Items without a move-out date")
		self.assertNotContains(response, "Active bundles")
		self.assertNotContains(response, "Avg. days to sell")
		self.assertNotContains(response, "Buyer</a>")
		self.assertNotContains(response, "Seller</a>")

	def test_status_choices_and_categories_come_from_models(self):
		self.client.force_login(self.user)
		response = self.client.get(reverse("seller-listings"))
		self.assertEqual(response.status_code, 200)
		self.assertEqual(
			list(response.context["listing_status_choices"]),
			list(Listing.Status.choices),
		)
		self.assertEqual(list(response.context["categories"]), [ItemCategory.objects.get(category_name="Furniture")])
		for label in ("All statuses", "Draft", "Active", "Reserved", "Sold", "Inactive"):
			self.assertContains(response, label)

	def test_listing_detail_visits_increment_views_and_update_seller_metrics(self):
		listing = Listing.objects.get(title="Study Desk")
		url = reverse("listing-detail-url", args=[listing.pk])
		self.assertEqual(self.client.get(url).status_code, 200)
		self.assertEqual(self.client.get(url).status_code, 200)
		self.assertEqual(self.client.post(url).status_code, 405)
		listing.refresh_from_db()
		self.assertEqual(listing.views, 2)

		self.client.force_login(self.user)
		response = self.client.get(reverse("seller-listings"))
		self.assertEqual(response.context["total_views"], 2)
		self.assertContains(response, "2 views")

	def test_listing_inquiries_count_unique_buyers(self):
		listing = Listing.objects.get(title="Study Desk")
		for number in range(2):
			buyer = User.objects.create_user(email_verified=True, email_verified_at=timezone.now(),
				username=f"buyer-{number}",
				email=f"buyer-{number}@illinois.edu",
				display_name=f"Buyer {number}",
			)
			Conversation.objects.create(
				listing=listing,
				buyer=buyer,
				seller=self.user,
			)
		conversations = list(Conversation.objects.filter(listing=listing).order_by("pk"))
		answered_conversation, unanswered_conversation = conversations
		Message.objects.create(
			conversation=answered_conversation,
			sender=answered_conversation.buyer,
			body_text="Is this available?",
			is_read=True,
		)
		Message.objects.create(
			conversation=answered_conversation,
			sender=self.user,
			body_text="Yes, this is still available.",
		)
		Message.objects.create(
			conversation=unanswered_conversation,
			sender=unanswered_conversation.buyer,
			body_text="Can I pick this up?",
			is_read=False,
		)

		self.client.force_login(self.user)
		response = self.client.get(reverse("seller-listings"))
		self.assertEqual(response.context["listings"][0].inquiry_count, 2)
		self.assertEqual(response.context["unanswered_inquiries"], 1)
		self.assertEqual(
			response.context["listing_inquiry_chart"][0],
			{
				"title": "Study Desk",
				"total": 2,
				"answered": 1,
				"unanswered": 1,
				"total_percent": 100,
				"answered_percent": 50,
				"unanswered_percent": 50,
			},
		)
		self.assertContains(response, "2 inquiries")
		self.assertContains(response, "Total inquiries")
		self.assertContains(response, "Top Listings by Inquiries")
		self.assertContains(response, "Unanswered inquiries")
		self.assertNotContains(response, f"More actions for {listing.title}")

	def test_profile_separates_seller_and_buyer_actions(self):
		owned_listing = Listing.objects.get(title="Study Desk")
		owned_listing.status = Listing.Status.RESERVED
		owned_listing.save()

		other_seller = User.objects.create_user(
			email_verified=True,
			email_verified_at=timezone.now(),
			username="purchase-seller",
			email="purchase-seller@illinois.edu",
			display_name="Purchase Seller",
		)
		purchase_listing = Listing.objects.create(
			seller=other_seller,
			item_type=owned_listing.item_type,
			title="Purchased Desk Lamp",
			condition=Listing.Condition.GOOD,
			listing_price=20,
			benchmark_low=15,
			benchmark_high=30,
			fulfillment_option=Listing.Fulfillment.PICKUP,
		)
		purchase_conversation = Conversation.objects.create(
			listing=purchase_listing,
			buyer=self.user,
			seller=other_seller,
		)
		Message.objects.create(
			conversation=purchase_conversation,
			sender=other_seller,
			body_text="Are you still interested?",
			is_read=False,
		)
		Transaction.objects.create(
			conversation=purchase_conversation,
			listing=purchase_listing,
			buyer=self.user,
			seller=other_seller,
			agreed_price=20,
			status=Transaction.Status.PENDING_PICKUP,
		)

		self.client.force_login(self.user)
		response = self.client.get(reverse("seller-listings"))
		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.context["reserved_count"], 1)
		self.assertEqual(response.context["buyer_unanswered_inquiries"], 1)
		self.assertEqual(response.context["buyer_summary"]["pending_pickups"], 1)
		self.assertContains(response, "Actions Needed - Items Sold")
		self.assertContains(response, "Actions Needed - Items Purchased")

	def test_public_ids_and_transaction_conversation_are_model_backed(self):
		listing = Listing.objects.get(title="Study Desk")
		buyer = User.objects.create_user(email_verified=True, email_verified_at=timezone.now(),
			username="status-buyer",
			email="status-buyer@illinois.edu",
			display_name="Status Buyer",
		)
		conversation = Conversation.objects.create(
			listing=listing,
			buyer=buyer,
			seller=self.user,
		)
		transaction = Transaction.objects.create(
			listing=listing,
			buyer=buyer,
			seller=self.user,
			conversation=conversation,
			agreed_price=listing.listing_price,
			status=Transaction.Status.PENDING_PICKUP,
		)
		self.assertIsNotNone(listing.listing_id)
		self.assertIsNotNone(conversation.conversation_uid)
		self.assertIsNotNone(transaction.transaction_id)
		self.assertEqual(transaction.conversation, conversation)
		self.assertEqual(transaction.status, Transaction.Status.PENDING_PICKUP)

	def test_listing_pricing_plan_is_model_backed(self):
		listing = Listing.objects.get(title="Study Desk")
		listing.pricing_plan = Listing.PricingPlan.BALANCED
		listing.save()
		self.client.force_login(self.user)
		response = self.client.get(reverse("seller-listings"))
		self.assertContains(response, "Balanced")
		self.assertContains(response, "Pricing plan")

	def test_pricing_and_moveout_page_is_removed(self):
		response = self.client.get("/seller/pricing-and-moveout/")
		self.assertEqual(response.status_code, 404)
		self.client.force_login(self.user)
		response = self.client.get(reverse("seller-listings"))
		self.assertNotContains(response, "Pricing &amp; Move-Out")

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
		self.assertContains(response, 'aria-current="page" href="/profile/settings/"')

	def test_unmodeled_settings_are_not_persisted(self):
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
		self.assertEqual(response.status_code, 200)
		self.assertNotIn("seller_settings", self.client.session)
		self.assertContains(response, "Save seller settings")
		self.assertContains(response, "disabled")

	def test_buyer_pickups_is_authenticated_and_scoped_to_buyer(self):
		response = self.client.get(reverse("buyer-pickups"))
		self.assertEqual(response.status_code, 302)

		buyer = User.objects.create_user(email_verified=True, email_verified_at=timezone.now(),
			username="buyer", email="buyer@illinois.edu", display_name="Test Buyer"
		)
		listing = Listing.objects.get(title="Study Desk")
		Transaction.objects.create(
			listing=listing,
			buyer=buyer,
			seller=self.user,
			agreed_price=35,
			benchmark_price_snapshot=55,
			status=Transaction.Status.PENDING_PICKUP,
			meetup_datetime=timezone.now() + timedelta(days=1),
			meetup_location="Main Library",
		)
		self.client.force_login(buyer)
		response = self.client.get(reverse("buyer-pickups"))
		self.assertEqual(response.status_code, 200)
		self.assertContains(response, "Study Desk")
		self.assertContains(response, "Meet-up date")
		self.assertNotContains(response, "Main Library")
		self.assertNotContains(response, "vs. estimated value")
		self.assertContains(response, "Confirm Item Received &amp; Complete Order")
		self.assertContains(response, 'aria-current="page" href="/profile/pickups/"')
		self.assertContains(response, 'data-chart-date="start"')
		self.assertContains(response, 'data-chart-date="end"')
		self.assertContains(response, 'value="purchase" data-chart-type checked')
		self.assertContains(response, 'value="sale" data-chart-type checked')
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

		buyer = User.objects.create_user(email_verified=True, email_verified_at=timezone.now(),
			username="bundle-buyer",
			email="bundle-buyer@illinois.edu",
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
		self.assertContains(response, "Accepted")
		self.assertNotContains(response, "Target budget")
		self.assertContains(response, 'aria-current="page" href="/profile/saved-bundles/"')
		self.assertNotContains(response, "Bundle Tips &amp; Next Steps")

	def test_purchase_history_and_csv_are_authenticated_and_buyer_scoped(self):
		self.assertEqual(self.client.get(reverse("buyer-purchase-history")).status_code, 302)
		self.assertEqual(self.client.get(reverse("buyer-purchase-history-csv")).status_code, 302)

		buyer = User.objects.create_user(email_verified=True, email_verified_at=timezone.now(),
			username="history-buyer", email="history@illinois.edu", display_name="History Buyer"
		)
		other_buyer = User.objects.create_user(email_verified=True, email_verified_at=timezone.now(),
			username="other-buyer", email="other@illinois.edu", display_name="Other Buyer"
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
		self.assertNotContains(response, "saved vs. retail")
		self.assertNotContains(response, "All-time Spend")
		self.assertNotContains(response, "All-time Savings")
		self.assertNotContains(response, "Download Purchase Receipts")
		self.assertNotContains(response, "View Receipt")
		self.assertNotContains(response, "Browse Similar")
		self.assertContains(response, 'aria-current="page" href="/profile/purchase-history/"')

		csv_response = self.client.get(reverse("buyer-purchase-history-csv"))
		self.assertEqual(csv_response.status_code, 200)
		self.assertEqual(csv_response["Content-Type"], "text/csv")
		csv_text = csv_response.content.decode()
		self.assertIn("Study Desk", csv_text)
		self.assertIn("30.00", csv_text)
		self.assertNotIn("24.00", csv_text)

	def test_watchlist_is_authenticated_and_empty_without_saved_items(self):
		self.assertEqual(self.client.get(reverse("buyer-watchlist")).status_code, 302)
		buyer = User.objects.create_user(email_verified=True, email_verified_at=timezone.now(),
			username="watchlist-buyer",
			email="watchlist@illinois.edu",
			display_name="Watchlist Buyer",
		)
		self.client.force_login(buyer)
		response = self.client.get(reverse("buyer-watchlist"))
		self.assertEqual(response.status_code, 200)
		self.assertContains(response, "Your watchlist is empty")
		self.assertNotContains(response, "Study Desk")
		self.assertContains(response, "All Categories")
		self.assertContains(response, "Sort: Recently Added")
		self.assertNotContains(response, "watchlist-heart")
		self.assertContains(response, 'aria-current="page" href="/profile/watchlist/"')
		for removed_text in ("Price dropped!", "people interested"):
			self.assertNotContains(response, removed_text)

	def test_watchlist_uses_persistent_user_scoped_records(self):
		buyer = User.objects.create_user(email_verified=True, email_verified_at=timezone.now(),
			username="saved-item-buyer",
			email="saved-item@illinois.edu",
			display_name="Saved Item Buyer",
		)
		listing = Listing.objects.get(title="Study Desk")
		WatchlistItem.objects.create(user=buyer, listing=listing)
		self.client.force_login(buyer)
		response = self.client.get(reverse("buyer-watchlist"))
		self.assertContains(response, "Study Desk")
		self.assertContains(response, "Not bundle eligible")
		self.assertNotContains(response, "Estimated retail")
		self.assertNotContains(response, "% savings")
		self.assertEqual(response.context["watchlist_candidates"], [listing])

	def test_profiles_do_not_substitute_cross_account_or_dummy_data(self):
		buyer = User.objects.create_user(email_verified=True, email_verified_at=timezone.now(),
			username="empty-buyer", email="empty@illinois.edu", display_name="Empty Buyer"
		)
		self.client.force_login(buyer)
		for route, empty_text in (
			("buyer-pickups", "No active pickups"),
			("buyer-bundles", "No saved bundles"),
			("buyer-purchase-history", "No completed purchases yet"),
		):
			response = self.client.get(reverse(route))
			self.assertContains(response, empty_text)
			self.assertNotContains(response, "Demo")
			self.assertNotContains(response, "4.9")

		self.client.force_login(self.user)
		response = self.client.get(reverse("seller-listings"))
		self.assertNotContains(response, "Next review")
		self.assertNotContains(response, "Balanced")
		self.assertNotContains(response, "4.9")
		self.assertNotContains(response, "reviews")
		self.assertNotContains(response, "Preferred meetup")
		self.assertNotContains(response, "Notification Preferences")
		self.assertContains(response, "Edit Profile")
