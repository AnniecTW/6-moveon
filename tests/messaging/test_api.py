import io
import json
import os
import re
import tempfile
import uuid
from unittest.mock import Mock, patch

from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from bundles.models import Bundle, BundleItem
from marketplace.models import ItemCategory, ItemType, Listing, Transaction, User
from messaging.models import Conversation, Message, MessageImage


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
        self.login(self.seller)
        response = self.post_json("messaging_request_decision", item.pk, data={"decision": "accepted"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "accepted")
        self.assertEqual(Transaction.objects.get(bundle_item=item).agreed_price, 45)
        self.assertEqual(self.post_json("messaging_request_decision", item.pk, data={"decision": "accepted"}).status_code, 200)
        self.assertEqual(Transaction.objects.count(), 1)

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
