from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.core.management import call_command
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .forms import ListingCreateForm
from .models import DeadlineNotification, ItemCategory, ItemType, Listing, PriceRecommendation, Transaction, User
from .pricing.deadline import curve_price, decide, evaluate_listing, notify_trigger, reset_schedule


class DeadlineCurveTests(TestCase):
    def test_endpoints_midpoint_and_acceleration(self):
        start = timezone.localdate()
        end = start + timedelta(days=30)
        prices = [curve_price(100, 60, start, end, start + timedelta(days=n), 2)
                  for n in (0, 15, 20, 25, 30)]
        self.assertEqual(prices, [Decimal("100.00"), Decimal("90.00"),
                                  Decimal("82.22"), Decimal("72.22"), Decimal("60.00")])
        self.assertLess(prices[1] - prices[2], prices[2] - prices[3])

    def test_bounds_rounding_and_invalid_window(self):
        start = timezone.localdate()
        end = start + timedelta(days=3)
        self.assertEqual(curve_price("10.00", "0.01", start, end,
                                     start - timedelta(days=5), "2"), Decimal("10.00"))
        self.assertEqual(curve_price("10.00", "0.01", start, end,
                                     end + timedelta(days=5), "2"), Decimal("0.01"))
        self.assertEqual(curve_price("10.00", "0.01", start, end,
                                     start + timedelta(days=1), "2"), Decimal("8.89"))
        with self.assertRaises(ValueError):
            curve_price(10, 5, start, start, start, 2)
        with self.assertRaises(ValueError):
            curve_price(10, 5, start, end, start, 1)


class DeadlineWorkflowTests(TestCase):
    def setUp(self):
        self.day = timezone.localdate()
        self.seller = User.objects.create_user(username="deadline-seller", email="deadline@illinois.edu",
                                               email_verified=True, email_verified_at=timezone.now())
        self.other = User.objects.create_user(username="other-seller", email="other@illinois.edu",
                                              email_verified=True, email_verified_at=timezone.now())
        category = ItemCategory.objects.create(category_name="Furniture")
        item_type = ItemType.objects.create(category=category, item_type_name="Desk")
        self.listing = Listing.objects.create(
            seller=self.seller, item_type=item_type, title="Desk",
            condition=Listing.Condition.GOOD, listing_price=Decimal("100.00"),
            minimum_price=Decimal("60.00"), move_out_date=self.day + timedelta(days=30),
            fulfillment_option=Listing.Fulfillment.PICKUP, status=Listing.Status.ACTIVE,
        )
        reset_schedule(self.listing, day=self.day)
        self.listing.save()

    def proposal(self, days=15):
        return evaluate_listing(self.listing.pk, day=self.day + timedelta(days=days))

    def test_generation_is_idempotent_and_never_applies(self):
        first = self.proposal()
        self.assertEqual(first.recommended_price, Decimal("90.00"))
        self.assertEqual(first.policy_version, "deadline-power-v2")
        self.assertEqual(self.proposal().pk, first.pk)
        self.listing.refresh_from_db()
        self.assertEqual(self.listing.listing_price, Decimal("100.00"))
        self.assertEqual(PriceRecommendation.objects.count(), 1)

    def test_late_start_uses_thirty_day_reference_window(self):
        self.listing.move_out_date = self.day + timedelta(days=15)
        self.listing.save(update_fields=["move_out_date"])
        reset_schedule(self.listing, day=self.day)
        self.listing.save()
        self.assertEqual(self.listing.deadline_start_date, self.day - timedelta(days=15))
        proposal = evaluate_listing(self.listing.pk, day=self.day)
        self.assertEqual(proposal.recommended_price, Decimal("90.00"))
        self.listing.refresh_from_db()
        self.assertEqual(self.listing.listing_price, Decimal("100.00"))

    def test_accept_decline_modify_and_duplicate_decision(self):
        proposal = self.proposal()
        decide(proposal.pk, self.seller.pk, "decline", day=self.day + timedelta(days=15))
        self.listing.refresh_from_db()
        self.assertEqual(self.listing.listing_price, Decimal("100.00"))
        self.assertIsNone(self.proposal())
        with self.assertRaises(ValueError):
            decide(proposal.pk, self.seller.pk, "accept", day=self.day + timedelta(days=15))
        proposal = self.proposal(days=16)
        decided = decide(proposal.pk, self.seller.pk, "modify", chosen_price="75.00",
                         day=self.day + timedelta(days=16))
        self.assertEqual(decided.applied_price, Decimal("75.00"))
        self.assertEqual(decided.status, PriceRecommendation.Status.MODIFIED)
        self.listing.refresh_from_db()
        self.assertEqual(self.listing.listing_price, Decimal("75.00"))

    def test_stale_price_and_schedule_are_rejected(self):
        proposal = self.proposal()
        Listing.objects.filter(pk=self.listing.pk).update(listing_price=Decimal("90.00"))
        with self.assertRaises(ValueError):
            decide(proposal.pk, self.seller.pk, "accept", day=self.day + timedelta(days=15))
        self.listing.refresh_from_db()
        self.assertEqual(self.listing.listing_price, Decimal("90.00"))
        reset_schedule(self.listing, day=self.day + timedelta(days=15), start=False)
        self.listing.save()
        proposal.refresh_from_db()
        self.assertEqual(proposal.status, PriceRecommendation.Status.EXPIRED)
        self.assertIsNone(self.listing.deadline_start_date)

    def test_move_out_date_change_does_not_rewrite_original_window(self):
        proposal = self.proposal()
        Listing.objects.filter(pk=self.listing.pk).update(
            move_out_date=self.day + timedelta(days=45)
        )
        self.assertIsNone(self.proposal())
        proposal.refresh_from_db()
        self.assertEqual(proposal.status, PriceRecommendation.Status.EXPIRED)

    def test_below_floor_preference_change_invalidates_pending(self):
        proposal = self.proposal()
        Listing.objects.filter(pk=self.listing.pk).update(sell_no_matter_what=True)
        with self.assertRaises(ValueError):
            decide(proposal.pk, self.seller.pk, "accept", day=self.day + timedelta(days=15))
        proposal.refresh_from_db()
        self.assertEqual(proposal.status, PriceRecommendation.Status.EXPIRED)

    def test_floor_and_separate_below_floor_approval(self):
        proposal = self.proposal()
        with self.assertRaises(ValueError):
            decide(proposal.pk, self.seller.pk, "modify", chosen_price="50.00",
                   day=self.day + timedelta(days=15))
        self.listing.sell_no_matter_what = True
        self.listing.urgent_minimum_price = Decimal("50.00")
        self.listing.save(update_fields=["sell_no_matter_what", "urgent_minimum_price"])
        reset_schedule(self.listing, day=self.day)
        self.listing.save()
        proposal = self.proposal()
        with self.assertRaises(ValueError):
            decide(proposal.pk, self.seller.pk, "modify", chosen_price="50.00",
                   day=self.day + timedelta(days=15))
        decide(proposal.pk, self.seller.pk, "modify", chosen_price="50.00",
               below_floor_approved=True, day=self.day + timedelta(days=15))
        self.listing.refresh_from_db()
        self.assertEqual(self.listing.listing_price, Decimal("50.00"))

    def test_urgent_minimum_is_a_hard_limit_even_with_below_floor_approval(self):
        self.listing.sell_no_matter_what = True
        self.listing.urgent_minimum_price = Decimal("50.00")
        reset_schedule(self.listing, day=self.day)
        self.listing.save()
        proposal = self.proposal()
        with self.assertRaisesRegex(ValueError, "chosen minimum"):
            decide(proposal.pk, self.seller.pk, "modify", chosen_price="49.99",
                   below_floor_approved=True, day=self.day + timedelta(days=15))

    def test_deadline_below_floor_proposal_requires_confirmation(self):
        self.listing.sell_no_matter_what = True
        self.listing.urgent_minimum_price = Decimal("50.00")
        self.listing.save(update_fields=["sell_no_matter_what", "urgent_minimum_price"])
        reset_schedule(self.listing, day=self.day)
        self.listing.save()
        proposal = self.proposal(days=30)
        self.assertEqual(proposal.recommended_price, Decimal("50.00"))
        self.assertTrue(proposal.below_floor)
        with self.assertRaises(ValueError):
            decide(proposal.pk, self.seller.pk, "accept", day=self.day + timedelta(days=30))
        decide(proposal.pk, self.seller.pk, "accept", below_floor_approved=True,
               day=self.day + timedelta(days=30))

    def test_urgency_edit_preserves_original_base_after_accepted_markdown(self):
        self.listing.move_out_date = self.day + timedelta(days=15)
        reset_schedule(self.listing, day=self.day)
        self.listing.save()
        normal = evaluate_listing(self.listing.pk, day=self.day)
        self.assertEqual(normal.recommended_price, Decimal("90.00"))
        decide(normal.pk, self.seller.pk, "accept", day=self.day)
        self.listing.refresh_from_db()
        data = {
            "title": "Desk", "listing_price": "90.00", "condition": "GOOD",
            "item_type": str(self.listing.item_type_id),
            "category": str(self.listing.item_type.category_id),
            "fulfillment_pickup": "on", "minimum_price": "60.00",
            "urgent_minimum_price": "55.00", "sell_no_matter_what": "on",
            "move_out_date": self.listing.move_out_date.isoformat(),
            "pricing_decision": "EDITED", "image_ids": "",
        }
        form = ListingCreateForm(data=data, instance=self.listing, user=self.seller)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        self.listing.refresh_from_db()
        self.assertEqual(self.listing.deadline_start_price, Decimal("100.00"))
        self.assertEqual(self.listing.listing_price, Decimal("90.00"))
        self.assertEqual(self.listing.deadline_urgent_floor, Decimal("55.00"))
        self.assertEqual(self.listing.deadline_gamma, Decimal("1.2"))
        urgent = PriceRecommendation.objects.get(status=PriceRecommendation.Status.PENDING)
        self.assertEqual(urgent.recommended_price, Decimal("80.41"))

    def test_date_extension_keeps_base_and_does_not_raise_accepted_price(self):
        self.listing.move_out_date = self.day + timedelta(days=15)
        reset_schedule(self.listing, day=self.day)
        self.listing.save()
        proposal = evaluate_listing(self.listing.pk, day=self.day)
        decide(proposal.pk, self.seller.pk, "accept", day=self.day)
        self.listing.refresh_from_db()
        data = {
            "title": "Desk", "listing_price": "90.00", "condition": "GOOD",
            "item_type": str(self.listing.item_type_id),
            "category": str(self.listing.item_type.category_id),
            "fulfillment_pickup": "on", "minimum_price": "60.00",
            "move_out_date": (self.day + timedelta(days=20)).isoformat(),
            "pricing_decision": "EDITED", "image_ids": "",
        }
        form = ListingCreateForm(data=data, instance=self.listing, user=self.seller)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        self.listing.refresh_from_db()
        self.assertEqual(self.listing.deadline_start_price, Decimal("100.00"))
        self.assertEqual(self.listing.listing_price, Decimal("90.00"))
        self.assertFalse(PriceRecommendation.objects.filter(status=PriceRecommendation.Status.PENDING).exists())

    def test_normal_minimum_edit_recalculates_without_rebasing(self):
        self.listing.move_out_date = self.day + timedelta(days=15)
        reset_schedule(self.listing, day=self.day)
        self.listing.save()
        proposal = evaluate_listing(self.listing.pk, day=self.day)
        decide(proposal.pk, self.seller.pk, "accept", day=self.day)
        self.listing.refresh_from_db()
        data = {
            "title": "Desk", "listing_price": "90.00", "condition": "GOOD",
            "item_type": str(self.listing.item_type_id),
            "category": str(self.listing.item_type.category_id),
            "fulfillment_pickup": "on", "minimum_price": "55.00",
            "move_out_date": self.listing.move_out_date.isoformat(),
            "pricing_decision": "EDITED", "image_ids": "",
        }
        form = ListingCreateForm(data=data, instance=self.listing, user=self.seller)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        self.listing.refresh_from_db()
        self.assertEqual(self.listing.deadline_start_price, Decimal("100.00"))
        self.assertEqual(PriceRecommendation.objects.get(status="PENDING").recommended_price,
                         Decimal("88.75"))

    def test_sell_no_matter_what_requires_seller_chosen_urgent_minimum(self):
        data = {
            "title": "Desk", "listing_price": "100.00", "condition": "GOOD",
            "item_type": str(self.listing.item_type_id),
            "category": str(self.listing.item_type.category_id),
            "fulfillment_pickup": "on", "minimum_price": "60.00",
            "sell_no_matter_what": "on",
            "move_out_date": self.listing.move_out_date.isoformat(),
            "pricing_decision": "EDITED", "image_ids": "",
        }
        form = ListingCreateForm(data=data, instance=self.listing, user=self.seller)
        self.assertFalse(form.is_valid())
        self.assertIn("urgent_minimum_price", form.errors)

    def test_unavailable_and_overdue_are_excluded(self):
        self.listing.status = Listing.Status.SOLD
        self.listing.save(update_fields=["status"])
        self.assertIsNone(self.proposal())
        self.listing.status = Listing.Status.ACTIVE
        self.listing.save(update_fields=["status"])
        self.assertIsNone(self.proposal(days=31))

    def test_active_transaction_blocks_new_recommendation(self):
        Transaction.objects.create(
            listing=self.listing, buyer=self.other, seller=self.seller,
            agreed_price=Decimal("80.00"), status=Transaction.Status.PENDING_PICKUP,
        )
        self.assertIsNone(self.proposal())

    def test_web_action_is_seller_scoped(self):
        proposal = self.proposal()
        url = reverse("deadline-recommendation-decision", args=[proposal.pk])
        self.client.force_login(self.other)
        self.assertEqual(self.client.post(url, {"action": "accept"}).status_code, 404)
        self.client.force_login(self.seller)
        self.assertEqual(self.client.get(url).status_code, 405)

    def test_management_command_repeated_runs(self):
        reset_schedule(self.listing, day=self.day - timedelta(days=15))
        self.listing.save()
        call_command("evaluate_deadline_pricing", verbosity=0)
        call_command("evaluate_deadline_pricing", verbosity=0)
        self.assertEqual(PriceRecommendation.objects.filter(status="PENDING").count(), 1)
        self.assertEqual(DeadlineNotification.objects.count(), 1)
        self.assertEqual(DeadlineNotification.objects.get().trigger_days, 30)

    def test_only_exact_milestones_create_inbox_notifications(self):
        reset_schedule(self.listing, day=self.day - timedelta(days=15))
        self.listing.save()
        for remaining in (30, 29, 21, 20, 14, 13, 7, 6, 3, 2):
            day = self.listing.move_out_date - timedelta(days=remaining)
            recommendation = evaluate_listing(self.listing.pk, day=day)
            self.assertIsNotNone(recommendation)
            notification = notify_trigger(self.listing.pk, recommendation.pk, day=day)
            self.assertEqual(notification is not None, remaining in {30, 21, 14, 7, 3})
        self.assertEqual(
            list(DeadlineNotification.objects.order_by("-trigger_days").values_list("trigger_days", flat=True)),
            [30, 21, 14, 7, 3],
        )

    def test_manual_button_does_not_send_inbox_notification(self):
        reset_schedule(self.listing, day=self.day - timedelta(days=15))
        self.listing.save()
        self.client.force_login(self.seller)
        url = reverse("request-deadline-suggestion", args=[self.listing.pk])
        self.assertEqual(self.client.post(url).status_code, 302)
        self.assertEqual(PriceRecommendation.objects.filter(status="PENDING").count(), 1)
        self.assertEqual(DeadlineNotification.objects.count(), 0)
        self.assertContains(self.client.get(reverse("seller-listings")), "Markdown suggestion: $")

    def test_moveon_inbox_notification_is_private_and_readable(self):
        reset_schedule(self.listing, day=self.day - timedelta(days=15))
        self.listing.save()
        proposal = evaluate_listing(self.listing.pk, day=self.day)
        notice = notify_trigger(self.listing.pk, proposal.pk, day=self.day)
        self.client.force_login(self.other)
        self.assertNotContains(self.client.get(reverse("messages")), "30 days until move-out")
        self.assertEqual(self.client.post(reverse("deadline-notification-open", args=[notice.pk])).status_code, 404)
        self.client.force_login(self.seller)
        self.assertContains(self.client.get(reverse("messages")), "30 days until move-out")
        self.assertGreaterEqual(self.client.get(reverse("messaging_unread")).json()["unreadCount"], 1)
        response = self.client.post(reverse("deadline-notification-open", args=[notice.pk]))
        self.assertEqual(response.status_code, 302)
        notice.refresh_from_db()
        self.assertIsNotNone(notice.read_at)
        self.assertEqual(self.client.get(reverse("messaging_unread")).json()["unreadCount"], 0)
        decide(proposal.pk, self.seller.pk, "decline", day=self.day)
        notice.refresh_from_db()
        self.assertIsNotNone(notice.resolved_at)

    def test_opening_older_reminder_refreshes_current_curve_price(self):
        reset_schedule(self.listing, day=self.day - timedelta(days=15))
        self.listing.save()
        old = evaluate_listing(self.listing.pk, day=self.day)
        notice = notify_trigger(self.listing.pk, old.pk, day=self.day)
        self.client.force_login(self.seller)
        with patch("marketplace.pricing.deadline.timezone.localdate", return_value=self.day + timedelta(days=1)):
            self.assertEqual(
                self.client.post(reverse("deadline-notification-open", args=[notice.pk])).status_code,
                302,
            )
        old.refresh_from_db()
        self.assertEqual(old.status, PriceRecommendation.Status.EXPIRED)
        current = PriceRecommendation.objects.get(status=PriceRecommendation.Status.PENDING)
        self.assertEqual(current.schedule_date, self.day + timedelta(days=1))
        self.assertLess(current.recommended_price, old.recommended_price)

    def test_schedule_started_at_thirty_days_has_no_immediate_markdown_message(self):
        self.assertIsNone(evaluate_listing(self.listing.pk, day=self.day))
        self.assertFalse(DeadlineNotification.objects.exists())

    def test_manual_price_edit_keeps_original_base(self):
        proposal = self.proposal()
        data = {
            "title": "Desk", "listing_price": "95.00", "condition": "GOOD",
            "item_type": str(self.listing.item_type_id),
            "category": str(self.listing.item_type.category_id),
            "fulfillment_pickup": "on", "minimum_price": "60.00",
            "move_out_date": self.listing.move_out_date.isoformat(),
            "pricing_decision": "EDITED", "image_ids": "",
        }
        form = ListingCreateForm(data=data, instance=self.listing, user=self.seller)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        self.listing.refresh_from_db()
        proposal.refresh_from_db()
        self.assertEqual(self.listing.deadline_start_price, Decimal("100.00"))
        self.assertEqual(self.listing.deadline_start_date, self.day)
        self.assertEqual(proposal.status, PriceRecommendation.Status.EXPIRED)
        next_proposal = evaluate_listing(self.listing.pk, day=self.day + timedelta(days=15))
        self.assertEqual(next_proposal.recommended_price, Decimal("90.00"))

    def test_missing_schedule_starts_automatically_during_daily_evaluation(self):
        self.listing.move_out_date = self.day + timedelta(days=14)
        reset_schedule(self.listing, day=self.day, start=False)
        self.listing.save()
        call_command("evaluate_deadline_pricing")
        self.listing.refresh_from_db()
        self.assertEqual(self.listing.deadline_start_price, Decimal("100.00"))
        self.assertEqual(self.listing.deadline_start_date, self.day - timedelta(days=16))
        self.assertEqual(PriceRecommendation.objects.get(status="PENDING").recommended_price,
                         Decimal("88.62"))
        self.assertEqual(DeadlineNotification.objects.get().trigger_days, 14)

    def test_urgent_schedule_never_starts_without_urgent_minimum(self):
        self.listing.sell_no_matter_what = True
        reset_schedule(self.listing, day=self.day, start=False)
        self.listing.save()
        self.assertIsNone(evaluate_listing(self.listing.pk, day=self.day))
        self.listing.refresh_from_db()
        self.assertIsNone(self.listing.deadline_start_date)

    def test_manual_price_below_curve_waits_until_curve_catches_up(self):
        data = {
            "title": "Desk", "listing_price": "85.00", "condition": "GOOD",
            "item_type": str(self.listing.item_type_id),
            "category": str(self.listing.item_type.category_id),
            "fulfillment_pickup": "on", "minimum_price": "60.00",
            "move_out_date": self.listing.move_out_date.isoformat(),
            "pricing_decision": "EDITED", "image_ids": "",
        }
        form = ListingCreateForm(data=data, instance=self.listing, user=self.seller)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        self.listing.refresh_from_db()
        self.assertEqual(self.listing.deadline_start_price, Decimal("100.00"))
        self.assertIsNone(evaluate_listing(self.listing.pk, day=self.day + timedelta(days=15)))
        proposal = evaluate_listing(self.listing.pk, day=self.day + timedelta(days=20))
        self.assertEqual(proposal.recommended_price, Decimal("82.22"))

    def test_seller_can_edit_markdown_base_without_changing_listing_price(self):
        self.listing.move_out_date = self.day + timedelta(days=15)
        reset_schedule(self.listing, day=self.day)
        self.listing.save()
        self.assertEqual(
            ListingCreateForm(instance=self.listing, user=self.seller)["deadline_base_price"].value(),
            Decimal("100.00"),
        )
        old_proposal = evaluate_listing(self.listing.pk, day=self.day)
        data = {
            "title": "Desk", "listing_price": "100.00", "deadline_base_price": "95.00",
            "condition": "GOOD", "item_type": str(self.listing.item_type_id),
            "category": str(self.listing.item_type.category_id),
            "fulfillment_pickup": "on", "minimum_price": "60.00",
            "move_out_date": self.listing.move_out_date.isoformat(),
            "pricing_decision": "EDITED", "image_ids": "",
        }
        form = ListingCreateForm(data=data, instance=self.listing, user=self.seller)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        self.listing.refresh_from_db()
        old_proposal.refresh_from_db()
        self.assertEqual(old_proposal.status, PriceRecommendation.Status.EXPIRED)
        self.assertEqual(self.listing.deadline_base_price, Decimal("95.00"))
        self.assertEqual(self.listing.deadline_start_price, Decimal("95.00"))
        self.assertEqual(self.listing.listing_price, Decimal("100.00"))
        self.assertEqual(PriceRecommendation.objects.get(status="PENDING").recommended_price,
                         Decimal("86.25"))

        data["listing_price"] = "90.00"
        data.pop("deadline_base_price")
        form = ListingCreateForm(data=data, instance=self.listing, user=self.seller)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        self.listing.refresh_from_db()
        self.assertEqual(self.listing.deadline_base_price, Decimal("95.00"))
        self.assertEqual(self.listing.deadline_start_price, Decimal("95.00"))
        self.assertEqual(self.listing.listing_price, Decimal("90.00"))

        data["urgent_minimum_price"] = "55.00"
        data["sell_no_matter_what"] = "on"
        form = ListingCreateForm(data=data, instance=self.listing, user=self.seller)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        self.listing.refresh_from_db()
        self.assertEqual(self.listing.deadline_start_price, Decimal("95.00"))
        self.assertEqual(self.listing.deadline_gamma, Decimal("1.2"))
        self.assertEqual(PriceRecommendation.objects.get(status="PENDING").recommended_price,
                         Decimal("77.59"))

    def test_markdown_base_must_cover_normal_minimum(self):
        data = {
            "title": "Desk", "listing_price": "100.00", "deadline_base_price": "50.00",
            "condition": "GOOD", "item_type": str(self.listing.item_type_id),
            "category": str(self.listing.item_type.category_id),
            "fulfillment_pickup": "on", "minimum_price": "60.00",
            "move_out_date": self.listing.move_out_date.isoformat(),
            "pricing_decision": "EDITED", "image_ids": "",
        }
        form = ListingCreateForm(data=data, instance=self.listing, user=self.seller)
        self.assertFalse(form.is_valid())
        self.assertIn("deadline_base_price", form.errors)

    def test_moveout_edit_restarts_schedule_and_sends_milestone_reminder(self):
        data = {
            "title": "Desk", "listing_price": "100.00", "condition": "GOOD",
            "item_type": str(self.listing.item_type_id),
            "category": str(self.listing.item_type.category_id),
            "fulfillment_pickup": "on", "minimum_price": "60.00",
            "move_out_date": (self.day + timedelta(days=14)).isoformat(),
            "pricing_decision": "EDITED", "image_ids": "",
        }
        form = ListingCreateForm(data=data, instance=self.listing, user=self.seller)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        self.listing.refresh_from_db()
        self.assertEqual(self.listing.deadline_end_date, self.day + timedelta(days=14))
        self.assertEqual(self.listing.deadline_start_date, self.day - timedelta(days=16))
        proposal = PriceRecommendation.objects.get(status=PriceRecommendation.Status.PENDING)
        self.assertEqual(proposal.recommended_price, Decimal("88.62"))
        self.assertEqual(self.listing.listing_price, Decimal("100.00"))
        self.assertEqual(DeadlineNotification.objects.get().trigger_days, 14)

    def test_stale_edit_form_cannot_overwrite_new_price(self):
        data = {
            "title": "Updated desk", "listing_price": "100.00", "condition": "GOOD",
            "item_type": str(self.listing.item_type_id),
            "category": str(self.listing.item_type.category_id),
            "fulfillment_pickup": "on", "minimum_price": "60.00",
            "move_out_date": self.listing.move_out_date.isoformat(),
            "pricing_decision": "EDITED", "image_ids": "",
        }
        form = ListingCreateForm(data=data, instance=self.listing, user=self.seller)
        self.assertTrue(form.is_valid(), form.errors)
        Listing.objects.filter(pk=self.listing.pk).update(listing_price=Decimal("85.00"))
        with self.assertRaises(ValidationError):
            form.save()
        self.listing.refresh_from_db()
        self.assertEqual(self.listing.listing_price, Decimal("85.00"))
