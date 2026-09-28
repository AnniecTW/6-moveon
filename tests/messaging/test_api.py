import io
import json
import os
import re
import tempfile
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock, patch

from django.core import mail
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, close_old_connections
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from bundles.models import Bundle, BundleItem
from marketplace.models import ItemCategory, ItemType, Listing, Transaction, User
from messaging.models import Conversation, DealProposal, Message, MessageImage
from messaging import api as messaging_api


class MessagingApiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.buyer = cls.user("buyer")
        cls.seller = cls.user("seller")
        cls.other = cls.user("other")
        category = ItemCategory.objects.create(category_name="Furniture")
        item_type = ItemType.objects.create(category=category, item_type_name="Desk")
        cls.listing = Listing.objects.create(
            seller=cls.seller, item_type=item_type, title="Oak Desk",
            condition=Listing.Condition.GOOD, listing_price=50,
            fulfillment_option=Listing.Fulfillment.PICKUP, status=Listing.Status.ACTIVE,
        )
        cls.conversation = Conversation.objects.create(
            buyer=cls.buyer, seller=cls.seller, listing=cls.listing,
        )

    @staticmethod
    def user(name, **extra):
        return User.objects.create_user(
            username=name, email=f"{name}@illinois.edu", password="pass12345",
            display_name=name.title(), email_verified=True,
            email_verified_at=timezone.now(), **extra,
        )

    def login(self, user):
        self.client.force_login(user)

    def post_json(self, name, *args, data):
        return self.client.post(reverse(name, args=args),
                                data=json.dumps(data), content_type="application/json")

    def offer(self, price="42.50", *, key=None, conversation=None):
        return self.post_json("messaging_deal_proposals", (conversation or self.conversation).pk,
            data={"agreedPrice": price, "sellerConfirmed": True,
                  "clientRequestId": key or str(uuid.uuid4())})

    def revise_offer(self, proposal_id, price, *, key=None):
        return self.client.patch(reverse("messaging_deal_proposal", args=[proposal_id]),
            data=json.dumps({"agreedPrice": price, "sellerConfirmed": True,
                             "clientRequestId": key or str(uuid.uuid4())}),
            content_type="application/json")

    def decide_offer(self, proposal_id, decision="confirmed", **extra):
        return self.post_json("messaging_deal_decision", proposal_id,
                              data={"decision": decision, **extra})

    def test_page_and_api_require_campus_access_even_for_staff(self):
        self.assertEqual(self.client.get(reverse("messages")).status_code, 302)
        self.assertEqual(self.client.get(reverse("messaging_conversations")).status_code, 401)
        staff = self.user("staff", is_staff=True)
        self.login(staff)
        self.assertEqual(self.client.get(reverse("messages")).status_code, 200)
        staff.email_verified = False
        staff.save(update_fields=["email_verified"])
        self.assertEqual(self.client.get(reverse("messaging_conversations")).status_code, 403)

    def test_unread_total_counts_only_other_people_messages(self):
        first = Message.objects.create(conversation=self.conversation, sender=self.seller,
                                       body_text="Please reply")
        Message.objects.create(conversation=self.conversation, sender=self.buyer,
                               body_text="My own message")
        self.assertEqual(self.client.get(reverse("messaging_unread")).status_code, 401)
        self.login(self.other)
        self.assertEqual(self.client.get(reverse("messaging_unread")).json()["unreadCount"], 0)
        self.login(self.buyer)
        self.assertEqual(self.client.get(reverse("messaging_unread")).json()["unreadCount"], 1)
        self.post_json("messaging_read", self.conversation.pk, data={"messageIds": [first.pk]})
        self.assertEqual(self.client.get(reverse("messaging_unread")).json()["unreadCount"], 0)

    def test_new_login_entry_replaces_previous_message_destination(self):
        response = self.client.get(reverse("messages"))
        self.assertEqual(response.status_code, 302)
        self.client.get(response.url)
        self.assertEqual(self.client.session["account_next"], reverse("messages"))
        self.client.post(reverse("account"), {"mode": "login", "username": "buyer",
                                                   "password": "wrong"})
        self.client.get(reverse("account"))
        self.assertEqual(self.client.session["account_next"], reverse("home"))
        response = self.client.post(reverse("account"), {"mode": "login",
            "username": "buyer", "password": "pass12345"})
        self.assertRedirects(response, reverse("home"))

    def test_signup_tab_keeps_explicit_message_destination(self):
        self.client.get(reverse("account") + "?next=%2Fmessages%2F")
        response = self.client.get(reverse("account") + "?mode=signup&next=%2Fmessages%2F")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.session["account_next"], reverse("messages"))

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_signup_verification_from_messages_keeps_destination(self):
        self.client.get(reverse("account") + "?next=%2Fmessages%2F")
        self.client.post(reverse("account"), {
            "mode": "signup", "username": "newbuyer", "email": "newbuyer@illinois.edu",
            "password1": "A-strong-password-2026", "password2": "A-strong-password-2026",
        })
        code = re.search(r"\b\d{6}\b", mail.outbox[-1].body).group()
        response = self.client.post(reverse("account_verify"), {"code": code})
        self.assertEqual(response.status_code, 302)
        self.client.get(response.url)
        response = self.client.post(reverse("account"), {
            "mode": "login", "username": "newbuyer", "password": "A-strong-password-2026",
        })
        self.assertRedirects(response, reverse("messages"))

    def test_participant_scope_search_and_history(self):
        Message.objects.create(conversation=self.conversation, sender=self.seller, body_text="secret")
        self.login(self.other)
        self.assertEqual(self.client.get(reverse("messaging_conversations"), {"q": "Oak"}).json()["conversations"], [])
        self.assertEqual(self.client.get(reverse("messaging_messages", args=[self.conversation.pk])).status_code, 404)
        self.login(self.buyer)
        response = self.client.get(reverse("messaging_conversations"), {"q": "Seller"}).json()
        self.assertEqual(len(response["conversations"]), 1)
        self.assertEqual(response["conversations"][0]["unreadCount"], 1)

    def test_send_idempotency_and_explicit_read(self):
        self.login(self.buyer)
        key = str(uuid.uuid4())
        payload = {"text": "Hello", "imageIds": [], "clientRequestId": key}
        first = self.post_json("messaging_messages", self.conversation.pk, data=payload)
        second = self.post_json("messaging_messages", self.conversation.pk, data=payload)
        self.assertEqual(first.status_code, 201)
        self.assertEqual(first.json()["id"], second.json()["id"])
        self.assertEqual(Message.objects.count(), 1)
        self.login(self.seller)
        newer = Message.objects.create(conversation=self.conversation, sender=self.buyer, body_text="newer")
        self.post_json("messaging_read", self.conversation.pk, data={"messageIds": [first.json()["id"]]})
        newer.refresh_from_db()
        self.assertFalse(newer.is_read)

    def test_history_is_paginated(self):
        self.login(self.buyer)
        for i in range(35):
            Message.objects.create(conversation=self.conversation, sender=self.seller, body_text=str(i))
        page = self.client.get(reverse("messaging_messages", args=[self.conversation.pk])).json()
        self.assertEqual(len(page["messages"]), 30)
        self.assertTrue(page["hasMore"])
        older = self.client.get(reverse("messaging_messages", args=[self.conversation.pk]), {"before": page["nextBefore"]}).json()
        self.assertEqual(len(older["messages"]), 5)

    def test_create_or_reuse_inquiry(self):
        self.login(self.buyer)
        response = self.post_json("messaging_create", data={"listingId": self.listing.pk})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["id"], str(self.conversation.pk))
        self.assertEqual(Conversation.objects.count(), 1)

    def test_create_race_reuses_conversation_after_unique_conflict(self):
        self.login(self.buyer)
        missing = Mock()
        missing.first.return_value = None
        with (
            patch.object(Conversation.objects, "filter", return_value=missing),
            patch.object(Conversation.objects, "create", side_effect=IntegrityError),
        ):
            response = self.post_json(
                "messaging_create", data={"listingId": self.listing.pk}
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["id"], str(self.conversation.pk))
        self.assertEqual(Conversation.objects.count(), 1)

    def test_create_rejects_own_listing(self):
        self.login(self.seller)

        response = self.post_json(
            "messaging_create", data={"listingId": self.listing.pk}
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "You cannot message yourself.")
        self.assertEqual(Conversation.objects.count(), 1)

    def test_create_rejects_non_integer_listing_id(self):
        self.login(self.buyer)

        response = self.post_json("messaging_create", data={"listingId": "abc"})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "Invalid listing.")

    def test_create_returns_not_found_for_missing_listing(self):
        self.login(self.buyer)

        response = self.post_json("messaging_create", data={"listingId": 999999})

        self.assertEqual(response.status_code, 404)

    def test_create_rejects_unavailable_listing_without_conversation(self):
        listing = Listing.objects.create(
            seller=self.seller,
            item_type=self.listing.item_type,
            title="Inactive desk",
            condition=Listing.Condition.GOOD,
            listing_price=40,
            fulfillment_option=Listing.Fulfillment.PICKUP,
            status=Listing.Status.INACTIVE,
        )
        self.login(self.buyer)

        response = self.post_json("messaging_create", data={"listingId": listing.pk})

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["code"], "listing_unavailable")
        self.assertFalse(Conversation.objects.filter(listing=listing).exists())

    def test_create_reopens_existing_conversation_for_unavailable_listing(self):
        self.listing.status = Listing.Status.INACTIVE
        self.listing.save(update_fields=["status"])
        self.login(self.buyer)

        response = self.post_json(
            "messaging_create", data={"listingId": self.listing.pk}
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["id"], str(self.conversation.pk))
        self.assertEqual(Conversation.objects.count(), 1)

    def test_bundle_decision_creates_transaction_once(self):
        bundle = Bundle.objects.create(buyer=self.buyer, space=Bundle.Space.BEDROOM, status=Bundle.Status.REQUESTS_SENT)
        item = BundleItem.objects.create(bundle=bundle, listing=self.listing,
                                         listing_price_snapshot=50, proposed_bundle_price=45,
                                         item_status=BundleItem.ItemStatus.REQUESTED)
        self.conversation.bundle_item = item
        self.conversation.save(update_fields=["bundle_item"])
        before_reservation = self.listing.updated_at
        self.login(self.seller)
        response = self.post_json("messaging_request_decision", item.pk, data={"decision": "accepted"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "accepted")
        self.assertEqual(Transaction.objects.get(bundle_item=item).agreed_price, 45)
        self.listing.refresh_from_db()
        self.assertGreater(self.listing.updated_at, before_reservation)
        row = self.client.get(reverse("messaging_conversations")).json()["conversations"][0]
        self.assertEqual(row["trade"]["summaryState"], "pending_pickup")
        self.assertEqual(self.post_json("messaging_request_decision", item.pk, data={"decision": "accepted"}).status_code, 200)
        self.assertEqual(Transaction.objects.count(), 1)

    def test_trade_state_follows_real_bundle_reservation_for_each_conversation(self):
        other_buyer = self.user("secondbuyer")
        Conversation.objects.create(buyer=other_buyer, seller=self.seller, listing=self.listing)
        bundle = Bundle.objects.create(buyer=self.buyer, space=Bundle.Space.BEDROOM)
        item = BundleItem.objects.create(
            bundle=bundle, listing=self.listing, listing_price_snapshot=50,
            proposed_bundle_price=45, item_status=BundleItem.ItemStatus.ACCEPTED,
        )
        deal = Transaction.objects.create(
            listing=self.listing, buyer=self.buyer, seller=self.seller,
            bundle=bundle, bundle_item=item, agreed_price=45,
        )
        self.listing.status = Listing.Status.RESERVED
        self.listing.save(update_fields=["status"])

        for user in (self.buyer, self.seller):
            with self.subTest(user=user.username):
                self.login(user)
                rows = self.client.get(reverse("messaging_conversations")).json()["conversations"]
                row = next(row for row in rows if row["id"] == str(self.conversation.pk))
                self.assertEqual(row["listing"]["status"], Listing.Status.RESERVED)
                self.assertEqual(row["trade"]["summaryState"], "pending_pickup")
                self.assertEqual(row["trade"]["transaction"], {
                    "id": str(deal.pk), "source": "bundle",
                    "status": Transaction.Status.PENDING_PICKUP,
                    "agreedPrice": "45.00",
                })
                self.assertIsNone(row["trade"]["currentProposalId"])
                self.assertEqual(row["dealProposals"], [])

        self.login(other_buyer)
        response = self.client.get(reverse("messaging_conversations"))
        self.assertEqual(response["Cache-Control"], "private, no-store")
        row = response.json()["conversations"][0]
        self.assertEqual(row["trade"]["summaryState"], "unavailable")
        self.assertIsNone(row["trade"]["transaction"])
        self.assertNotIn("45.00", json.dumps(row))

        deal.status = Transaction.Status.CANCELLED
        deal.save(update_fields=["status"])
        self.listing.status = Listing.Status.ACTIVE
        self.listing.save(update_fields=["status"])
        self.login(self.buyer)
        row = self.client.get(reverse("messaging_conversations")).json()["conversations"][0]
        self.assertEqual(row["trade"]["summaryState"], "negotiating")
        self.assertIsNone(row["trade"]["transaction"])
        self.listing.status = Listing.Status.INACTIVE
        self.listing.save(update_fields=["status"])
        row = self.client.get(reverse("messaging_conversations")).json()["conversations"][0]
        self.assertEqual(row["trade"]["summaryState"], "unavailable")

    def test_bundle_request_action_state_uses_same_server_trade_result(self):
        bundle = Bundle.objects.create(buyer=self.buyer, space=Bundle.Space.BEDROOM)
        item = BundleItem.objects.create(
            bundle=bundle, listing=self.listing, listing_price_snapshot=50,
            item_status=BundleItem.ItemStatus.REQUESTED,
        )
        for user, state in ((self.buyer, "waiting"), (self.seller, "action_needed")):
            with self.subTest(user=user.username):
                self.login(user)
                row = self.client.get(reverse("messaging_conversations")).json()["conversations"][0]
                self.assertEqual(row["trade"]["summaryState"], state)
                self.assertEqual(row["trade"]["allowedActions"]["bundleRequestIds"],
                                 [str(item.pk)] if user == self.seller else [])
        item.item_status = BundleItem.ItemStatus.DECLINED
        item.save(update_fields=["item_status"])
        self.login(self.buyer)
        row = self.client.get(reverse("messaging_conversations")).json()["conversations"][0]
        self.assertEqual(row["trade"]["summaryState"], "declined")
        item.item_status = BundleItem.ItemStatus.ACCEPTED
        item.save(update_fields=["item_status"])
        row = self.client.get(reverse("messaging_conversations")).json()["conversations"][0]
        self.assertNotEqual(row["trade"]["summaryState"], "pending_pickup")

    def test_unlinked_transaction_without_bundle_item_is_not_attributed(self):
        Transaction.objects.create(
            listing=self.listing, buyer=self.buyer, seller=self.seller, agreed_price=39,
        )
        self.listing.status = Listing.Status.RESERVED
        self.listing.save(update_fields=["status"])
        self.login(self.buyer)
        with self.assertLogs("messaging.api", level="WARNING") as logs:
            row = self.client.get(reverse("messaging_conversations")).json()["conversations"][0]
        self.assertIn("cannot be attributed", logs.output[0])
        self.assertEqual(row["trade"]["summaryState"], "unavailable")
        self.assertIsNone(row["trade"]["transaction"])
        self.assertNotIn("39.00", json.dumps(row))

    def test_deal_permissions_campus_access_and_csrf(self):
        self.login(self.buyer)
        self.assertEqual(self.offer().status_code, 403)
        self.login(self.other)
        self.assertEqual(self.offer().status_code, 404)
        self.login(self.seller)
        proposal_id = self.offer().json()["proposal"]["id"]
        self.assertEqual(self.decide_offer(proposal_id).status_code, 403)
        self.login(self.buyer)
        self.assertEqual(self.revise_offer(proposal_id, "46.00").status_code, 403)
        self.assertEqual(self.post_json("messaging_deal_withdraw", proposal_id, data={}).status_code, 403)
        self.login(self.other)
        self.assertEqual(self.decide_offer(proposal_id).status_code, 404)
        self.assertEqual(self.revise_offer(proposal_id, "46.00").status_code, 404)
        self.assertEqual(self.post_json("messaging_deal_withdraw", proposal_id, data={}).status_code, 404)
        self.login(self.buyer)
        self.assertEqual(self.decide_offer(proposal_id, "declined").status_code, 200)

        seller = self.seller
        seller.email_verified = False
        seller.save(update_fields=["email_verified"])
        self.login(seller)
        self.assertEqual(self.offer().status_code, 403)
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.buyer)
        self.assertEqual(csrf_client.post(reverse("messaging_deal_decision", args=[proposal_id]),
            data=json.dumps({"decision": "confirmed"}), content_type="application/json").status_code, 403)

    def test_deal_price_validation_and_server_owned_transaction_fields(self):
        self.login(self.seller)
        for price in (None, True, 1.234, "0", "-1", "1.234", "1000000", "NaN", "Infinity", "1e2"):
            with self.subTest(price=price):
                self.assertEqual(self.offer(price).status_code, 400)
        self.assertEqual(self.post_json("messaging_deal_proposals", self.conversation.pk,
            data={"agreedPrice": "42.50", "sellerConfirmed": False,
                  "clientRequestId": str(uuid.uuid4())}).status_code, 400)
        self.assertEqual(self.offer(key="not-a-uuid").status_code, 400)
        response = self.post_json("messaging_deal_proposals", self.conversation.pk, data={
            "agreedPrice": "42.50", "sellerConfirmed": True,
            "clientRequestId": str(uuid.uuid4()), "buyerId": self.other.pk,
            "sellerId": self.other.pk, "role": "buyer", "allowedActions": ["confirm"],
        })
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["proposal"]["agreedPrice"], "42.50")
        self.login(self.buyer)
        decision = self.decide_offer(response.json()["proposal"]["id"], agreedPrice="0.01",
                                     buyerId=self.other.pk, sellerId=self.other.pk)
        self.assertEqual(decision.status_code, 200)
        deal = Transaction.objects.get()
        self.assertEqual(str(deal.agreed_price), "42.50")
        self.assertEqual((deal.buyer_id, deal.seller_id), (self.buyer.pk, self.seller.pk))

    def test_offer_request_key_retries_and_conflicting_reuse(self):
        self.login(self.seller)
        key = str(uuid.uuid4())
        with patch.object(DealProposal.objects, "create", side_effect=IntegrityError):
            failed = self.offer("25.00", key=key)
        self.assertEqual((failed.status_code, failed.json()["code"]),
                         (503, "offer_save_failed"))
        self.assertEqual(DealProposal.objects.count(), 0)
        first = self.offer("25.00", key=key)
        again = self.offer("25.00", key=key)
        self.assertEqual(first.status_code, 201)
        self.assertEqual(first.json()["proposal"]["id"], again.json()["proposal"]["id"])
        self.assertEqual(len(again.json()["dealProposals"]), 1)
        conflict = self.offer("26.00", key=key)
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(conflict.json()["code"], "idempotency_conflict")
        another_buyer = self.user("keyother")
        another_conversation = Conversation.objects.create(
            buyer=another_buyer, seller=self.seller, listing=self.listing)
        separate = self.offer("25.00", key=key, conversation=another_conversation)
        self.assertEqual(separate.status_code, 201)
        self.assertNotEqual(separate.json()["proposal"]["id"], first.json()["proposal"]["id"])

    def test_confirmed_offer_creates_one_real_transaction_and_both_roles_see_it(self):
        other_buyer = self.user("offerother")
        other_conversation = Conversation.objects.create(
            buyer=other_buyer, seller=self.seller, listing=self.listing)
        self.listing.benchmark_price = 70
        self.listing.save(update_fields=["benchmark_price"])
        self.login(self.seller)
        proposal_id = self.offer().json()["proposal"]["id"]
        self.listing.refresh_from_db()
        before_reservation = self.listing.updated_at
        self.login(self.buyer)
        result = self.decide_offer(proposal_id)
        self.assertEqual(result.status_code, 200)
        deal = Transaction.objects.get()
        self.listing.refresh_from_db()
        proposal = DealProposal.objects.get(pk=proposal_id)
        self.assertEqual(self.listing.status, Listing.Status.RESERVED)
        self.assertGreater(self.listing.updated_at, before_reservation)
        self.assertEqual((deal.conversation_id, deal.buyer_id, deal.seller_id),
                         (self.conversation.pk, self.buyer.pk, self.seller.pk))
        self.assertIsNone(deal.bundle_item_id)
        self.assertEqual((deal.agreed_price, deal.benchmark_price_snapshot), (42.50, 70))
        self.assertEqual((proposal.status, proposal.transaction_id),
                         (DealProposal.Status.CONFIRMED, deal.pk))
        for user in (self.buyer, self.seller):
            with self.subTest(user=user.username):
                self.login(user)
                rows = self.client.get(reverse("messaging_conversations")).json()["conversations"]
                row = next(row for row in rows if row["id"] == str(self.conversation.pk))
                self.assertEqual(row["trade"]["summaryState"], "pending_pickup")
                self.assertEqual(row["trade"]["transaction"]["agreedPrice"], "42.50")
                self.assertEqual(row["trade"]["transaction"]["source"], "deal")
        self.login(other_buyer)
        row = self.client.get(reverse("messaging_conversations")).json()["conversations"][0]
        self.assertEqual(row["id"], str(other_conversation.pk))
        self.assertEqual(row["trade"]["summaryState"], "unavailable")
        self.assertNotIn("42.50", json.dumps(row))

    def test_confirmation_retry_returns_the_original_transaction(self):
        self.login(self.seller)
        proposal_id = self.offer().json()["proposal"]["id"]
        self.login(self.buyer)
        first = self.decide_offer(proposal_id)
        retry = self.decide_offer(proposal_id)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(retry.status_code, 200)
        self.assertEqual(first.json()["trade"]["transaction"]["id"],
                         retry.json()["trade"]["transaction"]["id"])
        self.assertEqual(Transaction.objects.count(), 1)

    def test_revisions_withdrawal_and_decline_make_old_versions_stale(self):
        self.login(self.seller)
        old_id = self.offer("30.00").json()["proposal"]["id"]
        key = str(uuid.uuid4())
        with patch.object(DealProposal.objects, "create", side_effect=IntegrityError):
            failed = self.revise_offer(old_id, "35.00", key=key)
        self.assertEqual((failed.status_code, failed.json()["code"]),
                         (503, "offer_save_failed"))
        self.assertEqual(DealProposal.objects.get(pk=old_id).status,
                         DealProposal.Status.AWAITING_BUYER)
        revised = self.revise_offer(old_id, "35.00", key=key)
        self.assertEqual(revised.status_code, 201)
        new_id = revised.json()["proposal"]["id"]
        self.assertNotEqual(old_id, new_id)
        self.assertEqual(self.revise_offer(old_id, "35.00", key=key).json()["proposal"]["id"], new_id)
        self.assertEqual(self.revise_offer(new_id, "35.00", key=key).json()["code"], "idempotency_conflict")
        self.assertEqual(self.revise_offer(old_id, "36.00", key=key).json()["code"], "idempotency_conflict")
        self.assertEqual(DealProposal.objects.get(pk=old_id).agreed_price, 30)
        self.assertEqual(DealProposal.objects.get(pk=old_id).status, DealProposal.Status.SUPERSEDED)
        self.login(self.buyer)
        self.assertEqual(self.decide_offer(old_id).json()["code"], "stale_proposal")
        self.login(self.seller)
        withdrawal = self.post_json("messaging_deal_withdraw", new_id, data={})
        self.assertEqual(withdrawal.status_code, 200)
        self.assertEqual(self.post_json("messaging_deal_withdraw", new_id, data={}).json()["code"],
                         "stale_proposal")
        self.login(self.buyer)
        self.assertEqual(self.decide_offer(new_id).json()["code"], "stale_proposal")
        self.login(self.seller)
        third_id = self.offer("40.00").json()["proposal"]["id"]
        self.login(self.buyer)
        self.assertEqual(self.decide_offer(third_id, "declined").status_code, 200)
        self.assertEqual(self.decide_offer(third_id).json()["code"], "stale_proposal")
        self.assertEqual(Transaction.objects.count(), 0)

    def test_unavailable_offer_stays_invalid_and_failed_transaction_rolls_back(self):
        self.login(self.seller)
        old_id = self.offer().json()["proposal"]["id"]
        self.listing.status = Listing.Status.INACTIVE
        self.listing.save(update_fields=["status"])
        self.login(self.buyer)
        unavailable = self.decide_offer(old_id)
        self.assertEqual((unavailable.status_code, unavailable.json()["code"]),
                         (409, "listing_unavailable"))
        self.assertEqual(DealProposal.objects.get(pk=old_id).status,
                         DealProposal.Status.UNAVAILABLE)
        self.listing.status = Listing.Status.ACTIVE
        self.listing.save(update_fields=["status"])
        self.assertEqual(self.decide_offer(old_id).status_code, 409)
        self.login(self.seller)
        new_id = self.offer("44.00").json()["proposal"]["id"]
        self.login(self.buyer)
        with patch.object(Transaction.objects, "create", side_effect=IntegrityError):
            failed = self.decide_offer(new_id)
        self.assertEqual(failed.status_code, 503)
        self.listing.refresh_from_db()
        self.assertEqual(self.listing.status, Listing.Status.ACTIVE)
        self.assertEqual(DealProposal.objects.get(pk=new_id).status,
                         DealProposal.Status.AWAITING_BUYER)
        self.assertEqual(Transaction.objects.count(), 0)

        with patch.object(DealProposal, "save", side_effect=ValidationError("Link failed")):
            failed_link = self.decide_offer(new_id)
        self.assertEqual(failed_link.status_code, 503)
        self.listing.refresh_from_db()
        self.assertEqual(self.listing.status, Listing.Status.ACTIVE)
        self.assertEqual(Transaction.objects.count(), 0)
        self.assertEqual(DealProposal.objects.get(pk=new_id).status,
                         DealProposal.Status.AWAITING_BUYER)
        bundle = Bundle.objects.create(buyer=self.buyer, space=Bundle.Space.BEDROOM)
        item = BundleItem.objects.create(bundle=bundle, listing=self.listing,
            listing_price_snapshot=50, item_status=BundleItem.ItemStatus.REQUESTED)
        self.login(self.seller)
        with patch.object(Transaction.objects, "create", side_effect=IntegrityError):
            failed_bundle = self.post_json("messaging_request_decision", item.pk,
                                           data={"decision": "accepted"})
        self.assertEqual(failed_bundle.status_code, 503)
        self.listing.refresh_from_db()
        item.refresh_from_db()
        self.assertEqual((self.listing.status, item.item_status),
                         (Listing.Status.ACTIVE, BundleItem.ItemStatus.REQUESTED))
        self.assertEqual(DealProposal.objects.get(pk=new_id).status,
                         DealProposal.Status.AWAITING_BUYER)
        with patch.object(Bundle, "save", side_effect=ValidationError("Summary failed")):
            failed_summary = self.post_json("messaging_request_decision", item.pk,
                                            data={"decision": "accepted"})
        self.assertEqual(failed_summary.status_code, 503)
        self.listing.refresh_from_db()
        item.refresh_from_db()
        self.assertEqual((self.listing.status, item.item_status),
                         (Listing.Status.ACTIVE, BundleItem.ItemStatus.REQUESTED))
        self.assertEqual(Transaction.objects.count(), 0)

    def test_listing_deactivation_invalidates_offer_before_any_confirmation_request(self):
        self.login(self.seller)
        for unavailable_status in (Listing.Status.DRAFT, Listing.Status.INACTIVE):
            with self.subTest(status=unavailable_status):
                proposal_id = self.offer().json()["proposal"]["id"]
                self.listing.status = unavailable_status
                self.listing.save(update_fields=["status"])
                self.assertEqual(DealProposal.objects.get(pk=proposal_id).status,
                                 DealProposal.Status.UNAVAILABLE)
                self.listing.status = Listing.Status.ACTIVE
                self.listing.save(update_fields=["status"])
                self.login(self.buyer)
                result = self.decide_offer(proposal_id)
                self.assertEqual((result.status_code, result.json()["code"]),
                                 (409, "stale_proposal"))
                self.assertEqual(Transaction.objects.count(), 0)
                self.login(self.seller)
        proposal_id = self.offer().json()["proposal"]["id"]
        self.listing.status = Listing.Status.DRAFT
        with patch.object(DealProposal.objects, "using", side_effect=IntegrityError("invalidation failed")):
            with self.assertRaises(IntegrityError):
                self.listing.save(update_fields=["status"])
        self.listing.refresh_from_db()
        self.assertEqual(self.listing.status, Listing.Status.ACTIVE)
        self.assertEqual(DealProposal.objects.get(pk=proposal_id).status,
                         DealProposal.Status.AWAITING_BUYER)

    def test_pending_bundle_blocks_new_offer_and_revision_but_existing_offer_can_win(self):
        self.login(self.seller)
        offer_id = self.offer().json()["proposal"]["id"]
        bundle = Bundle.objects.create(buyer=self.buyer, space=Bundle.Space.BEDROOM)
        item = BundleItem.objects.create(
            bundle=bundle, listing=self.listing, listing_price_snapshot=50,
            item_status=BundleItem.ItemStatus.SELECTED,
        )
        other_offer_ids = []
        for number in (2, 3):
            listing = Listing.objects.create(
                seller=self.seller, item_type=self.listing.item_type, title=f"Bundle desk {number}",
                condition=Listing.Condition.GOOD, listing_price=50,
                fulfillment_option=Listing.Fulfillment.PICKUP, status=Listing.Status.ACTIVE,
            )
            BundleItem.objects.create(bundle=bundle, listing=listing, listing_price_snapshot=50,
                                      item_status=BundleItem.ItemStatus.SELECTED)
            other_conversation = Conversation.objects.create(
                buyer=self.buyer, seller=self.seller, listing=listing)
            other_offer_ids.append(self.offer("40.00", conversation=other_conversation)
                                   .json()["proposal"]["id"])
        self.login(self.buyer)
        self.assertEqual(self.client.post(reverse("bundle_send_requests", args=[bundle.pk])).status_code, 200)
        item.refresh_from_db()
        self.assertEqual(item.item_status, BundleItem.ItemStatus.REQUESTED)
        self.assertEqual(DealProposal.objects.get(pk=offer_id).status,
                         DealProposal.Status.AWAITING_BUYER)
        self.login(self.seller)
        self.assertEqual(self.offer("46.00").json()["code"], "bundle_request_pending")
        self.assertEqual(self.revise_offer(offer_id, "46.00").json()["code"],
                         "bundle_request_pending")
        self.assertEqual(DealProposal.objects.count(), 3)
        self.assertEqual(self.post_json("messaging_deal_withdraw", other_offer_ids[1],
                                        data={}).status_code, 200)
        self.login(self.buyer)
        self.assertEqual(self.decide_offer(other_offer_ids[0], "declined").status_code, 200)
        self.assertEqual(self.decide_offer(offer_id).status_code, 200)
        self.login(self.seller)
        blocked = self.post_json("messaging_request_decision", item.pk, data={"decision": "accepted"})
        self.assertEqual((blocked.status_code, blocked.json()["code"]),
                         (409, "listing_unavailable"))
        item.refresh_from_db()
        self.assertEqual(item.item_status, BundleItem.ItemStatus.REQUESTED)
        rows = self.client.get(reverse("messaging_conversations")).json()["conversations"]
        row = next(row for row in rows if row["id"] == str(self.conversation.pk))
        self.assertEqual(row["trade"]["allowedActions"]["bundleRequestIds"], [])
        self.assertEqual(row["trade"]["allowedActions"]["bundleDeclineRequestIds"],
                         [str(item.pk)])
        self.assertEqual(self.post_json("messaging_request_decision", item.pk,
                                     data={"decision": "declined"}).status_code, 200)
        self.assertEqual(self.post_json("messaging_request_decision", item.pk,
                                     data={"decision": "declined"}).status_code, 200)
        self.assertEqual(Transaction.objects.count(), 1)

    def test_competing_buyers_and_bundle_win_invalidate_other_offers(self):
        second_buyer = self.user("offersecond")
        second_conversation = Conversation.objects.create(
            buyer=second_buyer, seller=self.seller, listing=self.listing)
        self.login(self.seller)
        first_id = self.offer("41.00").json()["proposal"]["id"]
        second_id = self.offer("43.00", conversation=second_conversation).json()["proposal"]["id"]
        self.login(self.buyer)
        self.assertEqual(self.decide_offer(first_id).status_code, 200)
        self.assertEqual(DealProposal.objects.get(pk=second_id).status,
                         DealProposal.Status.UNAVAILABLE)
        self.login(second_buyer)
        self.assertEqual(self.decide_offer(second_id).json()["code"], "listing_unavailable")
        self.assertEqual(Transaction.objects.count(), 1)

        another_listing = Listing.objects.create(
            seller=self.seller, item_type=self.listing.item_type, title="Second desk",
            condition=Listing.Condition.GOOD, listing_price=50,
            fulfillment_option=Listing.Fulfillment.PICKUP, status=Listing.Status.ACTIVE,
        )
        another_conversation = Conversation.objects.create(
            buyer=self.buyer, seller=self.seller, listing=another_listing)
        self.login(self.seller)
        losing_id = self.offer("39.00", conversation=another_conversation).json()["proposal"]["id"]
        bundle = Bundle.objects.create(buyer=self.buyer, space=Bundle.Space.BEDROOM,
                                       status=Bundle.Status.REQUESTS_SENT)
        item = BundleItem.objects.create(
            bundle=bundle, listing=another_listing, listing_price_snapshot=50,
            item_status=BundleItem.ItemStatus.REQUESTED,
        )
        self.assertEqual(self.post_json("messaging_request_decision", item.pk,
                                     data={"decision": "accepted"}).status_code, 200)
        self.assertEqual(DealProposal.objects.get(pk=losing_id).status,
                         DealProposal.Status.UNAVAILABLE)
        self.login(self.buyer)
        self.assertEqual(self.decide_offer(losing_id).json()["code"], "listing_unavailable")
        another_listing.status = Listing.Status.ACTIVE
        another_listing.save(update_fields=["status"])
        Transaction.objects.filter(bundle_item=item).update(status=Transaction.Status.CANCELLED)
        self.assertEqual(self.decide_offer(losing_id).status_code, 409)

    def test_bundle_send_is_idempotent_and_keeps_existing_request_link(self):
        bundle = Bundle.objects.create(buyer=self.buyer, space=Bundle.Space.BEDROOM)
        item = BundleItem.objects.create(bundle=bundle, listing=self.listing,
            listing_price_snapshot=50, item_status=BundleItem.ItemStatus.SELECTED)
        for number in (2, 3):
            listing = Listing.objects.create(seller=self.seller, item_type=self.listing.item_type,
                title=f"Desk {number}", condition=Listing.Condition.GOOD, listing_price=50,
                fulfillment_option=Listing.Fulfillment.PICKUP, status=Listing.Status.ACTIVE)
            BundleItem.objects.create(bundle=bundle, listing=listing,
                listing_price_snapshot=50, item_status=BundleItem.ItemStatus.SELECTED)
        earlier = Bundle.objects.create(buyer=self.buyer, space=Bundle.Space.KITCHEN)
        old_item = BundleItem.objects.create(bundle=earlier, listing=self.listing,
            listing_price_snapshot=50, item_status=BundleItem.ItemStatus.REQUESTED)
        self.conversation.bundle_item = old_item
        self.conversation.save(update_fields=["bundle_item"])
        self.login(self.buyer)
        url = reverse("bundle_send_requests", args=[bundle.pk])
        self.assertEqual(self.client.post(url).status_code, 200)
        self.assertEqual(self.client.post(url).status_code, 200)
        self.conversation.refresh_from_db()
        item.refresh_from_db()
        self.assertEqual(self.conversation.bundle_item_id, old_item.pk)
        self.assertEqual(item.item_status, BundleItem.ItemStatus.REQUESTED)
        self.assertEqual(Message.objects.count(), 3)

    @staticmethod
    def png_file():
        data = io.BytesIO()
        Image.new("RGB", (2, 2), "red").save(data, format="PNG")
        return SimpleUploadedFile("a.png", data.getvalue(), content_type="image/png")

    def test_private_image_upload_and_send(self):
        with tempfile.TemporaryDirectory() as directory, override_settings(MEDIA_ROOT=directory):
            self.login(self.buyer)
            upload = self.client.post(reverse("messaging_upload"), {
                "conversationId": self.conversation.pk, "file": self.png_file(),
            })
            self.assertEqual(upload.status_code, 201)
            image_id = upload.json()["id"]
            self.login(self.seller)
            self.assertEqual(self.client.get(reverse("messaging_attachment", args=[image_id])).status_code, 404)
            self.login(self.other)
            self.assertEqual(self.client.get(reverse("messaging_attachment", args=[image_id])).status_code, 404)
            self.login(self.buyer)
            response = self.post_json("messaging_messages", self.conversation.pk, data={
                "text": "", "imageIds": [image_id], "clientRequestId": str(uuid.uuid4()),
            })
            self.assertEqual(response.status_code, 201)
            self.assertEqual(len(response.json()["images"]), 1)
            self.assertEqual(str(MessageImage.objects.get(pk=image_id).message_id), response.json()["id"])
            image_response = self.client.get(reverse("messaging_attachment", args=[image_id]))
            self.assertEqual(image_response.status_code, 200)
            image_response.close()

    def test_invalid_upload_content_is_rejected(self):
        self.login(self.buyer)
        response = self.client.post(reverse("messaging_upload"), {
            "conversationId": self.conversation.pk,
            "file": SimpleUploadedFile("bad.png", b"not an image", content_type="image/png"),
        })
        self.assertEqual(response.status_code, 400)

    def test_csrf_is_required_on_message_send(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.buyer)
        response = client.post(reverse("messaging_messages", args=[self.conversation.pk]),
            data=json.dumps({"text": "hi", "imageIds": [], "clientRequestId": str(uuid.uuid4())}),
            content_type="application/json")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "csrf_failed")
        self.assertEqual(Message.objects.count(), 0)

    def test_listing_history_survives_deletion(self):
        self.login(self.buyer)
        self.listing.delete()
        result = self.client.get(reverse("messaging_conversations")).json()["conversations"][0]
        self.assertEqual(result["listing"]["title"], "Oak Desk")
        self.assertFalse(result["listing"]["available"])

    def test_request_is_private_and_rejects_stale_decision(self):
        bundle = Bundle.objects.create(buyer=self.buyer, space=Bundle.Space.BEDROOM,
                                       status=Bundle.Status.REQUESTS_SENT)
        item = BundleItem.objects.create(bundle=bundle, listing=self.listing,
            listing_price_snapshot=50, item_status=BundleItem.ItemStatus.REQUESTED)
        self.login(self.other)
        self.assertEqual(self.post_json("messaging_request_decision", item.pk,
            data={"decision": "accepted"}).status_code, 404)
        self.login(self.buyer)
        self.assertEqual(self.post_json("messaging_request_decision", item.pk,
            data={"decision": "accepted"}).status_code, 404)
        self.login(self.seller)
        self.assertEqual(self.post_json("messaging_request_decision", item.pk,
            data={"decision": "declined"}).status_code, 200)
        self.assertEqual(self.post_json("messaging_request_decision", item.pk,
            data={"decision": "accepted"}).status_code, 409)

    def test_upload_over_limit_is_rejected(self):
        self.login(self.buyer)
        response = self.client.post(reverse("messaging_upload"), {
            "conversationId": self.conversation.pk,
            "file": SimpleUploadedFile("large.png", b"x" * (10 * 1024 * 1024 + 1),
                                       content_type="image/png"),
        })
        self.assertEqual(response.status_code, 400)
        self.assertEqual(MessageImage.objects.count(), 0)

    def test_valid_image_between_five_and_ten_megabytes_is_accepted(self):
        raw = os.urandom(1500 * 1500 * 3)
        data = io.BytesIO()
        Image.frombytes("RGB", (1500, 1500), raw).save(data, format="PNG")
        self.assertGreater(len(data.getvalue()), 5 * 1024 * 1024)
        self.assertLess(len(data.getvalue()), 10 * 1024 * 1024)
        with tempfile.TemporaryDirectory() as directory, override_settings(MEDIA_ROOT=directory):
            self.login(self.buyer)
            response = self.client.post(reverse("messaging_upload"), {
                "conversationId": self.conversation.pk,
                "file": SimpleUploadedFile("large-valid.png", data.getvalue(), content_type="image/png"),
            })
            self.assertEqual(response.status_code, 201)

    def test_image_cannot_bind_to_another_conversation_or_exceed_three(self):
        with tempfile.TemporaryDirectory() as directory, override_settings(MEDIA_ROOT=directory):
            other_listing = Listing.objects.create(seller=self.seller,
                item_type=self.listing.item_type, title="Second desk",
                condition=Listing.Condition.GOOD, listing_price=40,
                fulfillment_option=Listing.Fulfillment.PICKUP,
                status=Listing.Status.ACTIVE)
            second = Conversation.objects.create(buyer=self.buyer, seller=self.seller,
                listing=other_listing)
            self.login(self.buyer)
            ids = []
            for _ in range(4):
                upload = self.client.post(reverse("messaging_upload"), {
                    "conversationId": self.conversation.pk, "file": self.png_file(),
                })
                self.assertEqual(upload.status_code, 201)
                ids.append(upload.json()["id"])
            payload = {"text": "with image", "imageIds": [ids[0]],
                "clientRequestId": str(uuid.uuid4())}
            self.assertEqual(self.post_json("messaging_messages", second.pk,
                data=payload).status_code, 409)
            payload["imageIds"] = ids
            self.assertEqual(self.post_json("messaging_messages", self.conversation.pk,
                data=payload).status_code, 400)
            payload["imageIds"] = ids[:1]
            result = self.post_json("messaging_messages", self.conversation.pk,
                data=payload)
            self.assertEqual(result.status_code, 201)
            self.assertEqual(result.json()["text"], "with image")
            self.assertEqual(len(result.json()["images"]), 1)

    def test_suspended_and_inactive_sessions_lose_api_access(self):
        self.login(self.buyer)
        self.buyer.account_status = User.AccountStatus.SUSPENDED
        self.buyer.save(update_fields=["account_status"])
        self.assertIn(self.client.get(reverse("messaging_conversations")).status_code, (401, 403))
        self.buyer.account_status = User.AccountStatus.ACTIVE
        self.buyer.is_active = False
        self.buyer.save(update_fields=["account_status", "is_active"])
        self.assertIn(self.client.get(reverse("messaging_conversations")).status_code, (401, 403))

    def test_search_covers_conversations_older_than_first_page(self):
        needle = Listing.objects.create(seller=self.seller, item_type=self.listing.item_type,
            title="Needle desk", condition=Listing.Condition.GOOD, listing_price=20,
            fulfillment_option=Listing.Fulfillment.PICKUP, status=Listing.Status.ACTIVE)
        original = Conversation.objects.create(buyer=self.buyer, seller=self.seller,
            listing=needle)
        for number in range(35):
            listing = Listing.objects.create(seller=self.seller, item_type=self.listing.item_type,
                title=f"Other desk {number}", condition=Listing.Condition.GOOD,
                listing_price=20, fulfillment_option=Listing.Fulfillment.PICKUP,
                status=Listing.Status.ACTIVE)
            Conversation.objects.create(buyer=self.buyer, seller=self.seller, listing=listing)
        self.login(self.buyer)
        results = self.client.get(reverse("messaging_conversations"), {"q": "Needle"}).json()["conversations"]
        self.assertEqual([item["id"] for item in results], [str(original.pk)])


class MessagingDealConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.buyer = MessagingApiTests.user("racebuyer")
        self.seller = MessagingApiTests.user("raceseller")
        category = ItemCategory.objects.create(category_name="Race furniture")
        self.item_type = ItemType.objects.create(category=category, item_type_name="Race desk")
        self.listing = self.new_listing("First race desk")
        self.conversation = Conversation.objects.create(
            buyer=self.buyer, seller=self.seller, listing=self.listing)
        self.buyer_client = Client()
        self.buyer_client.force_login(self.buyer)
        self.seller_client = Client()
        self.seller_client.force_login(self.seller)

    def new_listing(self, title):
        return Listing.objects.create(
            seller=self.seller, item_type=self.item_type, title=title,
            condition=Listing.Condition.GOOD, listing_price=50,
            fulfillment_option=Listing.Fulfillment.PICKUP, status=Listing.Status.ACTIVE,
        )

    @staticmethod
    def json_request(client, name, record_id, payload, method="post"):
        return getattr(client, method)(reverse(name, args=[record_id]),
            data=json.dumps(payload), content_type="application/json")

    @staticmethod
    def race(first, second):
        barrier = threading.Barrier(2)
        original_reserve = messaging_api.reserve_listing
        original_touch = messaging_api.touch_available_listing

        def reserve(listing_id):
            barrier.wait(timeout=10)
            return original_reserve(listing_id)

        def touch(listing_id):
            barrier.wait(timeout=10)
            return original_touch(listing_id)

        with patch.object(messaging_api, "reserve_listing", side_effect=reserve), \
             patch.object(messaging_api, "touch_available_listing", side_effect=touch):
            with ThreadPoolExecutor(max_workers=2) as workers:
                a = workers.submit(first)
                b = workers.submit(second)
                results = a.result(timeout=20), b.result(timeout=20)
        close_old_connections()
        return results

    def test_confirmation_races_revision_and_bundle_acceptance_without_double_sale(self):
        offered = self.json_request(self.seller_client, "messaging_deal_proposals",
            self.conversation.pk, {"agreedPrice": "42.00", "sellerConfirmed": True,
                                   "clientRequestId": str(uuid.uuid4())})
        old_id = offered.json()["proposal"]["id"]
        revision_key = str(uuid.uuid4())
        confirm = lambda: self.json_request(self.buyer_client, "messaging_deal_decision",
            old_id, {"decision": "confirmed"})
        revise = lambda: self.json_request(self.seller_client, "messaging_deal_proposal",
            old_id, {"agreedPrice": "45.00", "sellerConfirmed": True,
                     "clientRequestId": revision_key}, method="patch")
        first, second = self.race(confirm, revise)
        self.assertIn(first.status_code, (200, 409, 503))
        self.assertIn(second.status_code, (201, 409, 503))
        self.assertLessEqual(Transaction.objects.filter(listing=self.listing).count(), 1)
        old = DealProposal.objects.get(pk=old_id)
        if old.status == DealProposal.Status.CONFIRMED:
            self.assertFalse(DealProposal.objects.filter(
                conversation=self.conversation, status=DealProposal.Status.AWAITING_BUYER).exists())
            self.assertEqual(Transaction.objects.filter(listing=self.listing).count(), 1)
        else:
            self.assertEqual(old.status, DealProposal.Status.SUPERSEDED)
            self.assertEqual(Transaction.objects.filter(listing=self.listing).count(), 0)
            self.assertEqual(confirm().json()["code"], "stale_proposal")

        listing = self.new_listing("Second race desk")
        conversation = Conversation.objects.create(buyer=self.buyer, seller=self.seller,
                                                   listing=listing)
        offered = self.json_request(self.seller_client, "messaging_deal_proposals",
            conversation.pk, {"agreedPrice": "38.00", "sellerConfirmed": True,
                              "clientRequestId": str(uuid.uuid4())})
        proposal_id = offered.json()["proposal"]["id"]
        bundle = Bundle.objects.create(buyer=self.buyer, space=Bundle.Space.BEDROOM)
        item = BundleItem.objects.create(bundle=bundle, listing=listing,
            listing_price_snapshot=50, item_status=BundleItem.ItemStatus.REQUESTED)
        confirm = lambda: self.json_request(self.buyer_client, "messaging_deal_decision",
            proposal_id, {"decision": "confirmed"})
        accept = lambda: self.json_request(self.seller_client, "messaging_request_decision",
            item.pk, {"decision": "accepted"})
        normal, bundled = self.race(confirm, accept)
        self.assertIn(normal.status_code, (200, 409, 503))
        self.assertIn(bundled.status_code, (200, 409, 503))
        self.assertEqual(Transaction.objects.filter(listing=listing).count(), 1)
        listing.refresh_from_db()
        self.assertEqual(listing.status, Listing.Status.RESERVED)
        deal = Transaction.objects.get(listing=listing)
        proposal = DealProposal.objects.get(pk=proposal_id)
        if deal.bundle_item_id:
            self.assertEqual(proposal.status, DealProposal.Status.UNAVAILABLE)
            self.assertEqual(confirm().json()["code"], "listing_unavailable")
        else:
            self.assertEqual(proposal.status, DealProposal.Status.CONFIRMED)
            self.assertEqual(accept().json()["code"], "listing_unavailable")

        listing = self.new_listing("Duplicate confirmation desk")
        conversation = Conversation.objects.create(buyer=self.buyer, seller=self.seller,
                                                   listing=listing)
        offered = self.json_request(self.seller_client, "messaging_deal_proposals",
            conversation.pk, {"agreedPrice": "31.00", "sellerConfirmed": True,
                              "clientRequestId": str(uuid.uuid4())})
        proposal_id = offered.json()["proposal"]["id"]
        confirm = lambda: self.json_request(self.buyer_client, "messaging_deal_decision",
            proposal_id, {"decision": "confirmed"})
        first, second = self.race(confirm, confirm)
        self.assertIn(first.status_code, (200, 503))
        self.assertIn(second.status_code, (200, 503))
        self.assertEqual(Transaction.objects.filter(listing=listing).count(), 1)
        retry = confirm()
        self.assertEqual(retry.status_code, 200)
        self.assertEqual(retry.json()["trade"]["transaction"]["id"],
                         str(Transaction.objects.get(listing=listing).pk))

        listing = self.new_listing("New offer race desk")
        winning_conversation = Conversation.objects.create(
            buyer=self.buyer, seller=self.seller, listing=listing)
        other_buyer = MessagingApiTests.user("racesecondbuyer")
        other_conversation = Conversation.objects.create(
            buyer=other_buyer, seller=self.seller, listing=listing)
        offered = self.json_request(self.seller_client, "messaging_deal_proposals",
            winning_conversation.pk, {"agreedPrice": "33.00", "sellerConfirmed": True,
                                      "clientRequestId": str(uuid.uuid4())})
        winning_id = offered.json()["proposal"]["id"]
        confirm = lambda: self.json_request(self.buyer_client, "messaging_deal_decision",
            winning_id, {"decision": "confirmed"})
        create = lambda: self.json_request(self.seller_client, "messaging_deal_proposals",
            other_conversation.pk, {"agreedPrice": "34.00", "sellerConfirmed": True,
                                    "clientRequestId": str(new_key)})
        new_key = uuid.uuid4()
        confirming, creating = self.race(confirm, create)
        self.assertIn(confirming.status_code, (200, 503))
        self.assertIn(creating.status_code, (201, 409, 503))
        if confirming.status_code == 503:
            self.assertEqual(confirm().status_code, 200)
        self.assertEqual(Transaction.objects.filter(listing=listing).count(), 1)
        self.assertFalse(DealProposal.objects.filter(
            conversation__listing=listing, status=DealProposal.Status.AWAITING_BUYER).exists())
