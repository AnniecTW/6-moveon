from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from marketplace.models import User, ItemCategory, ItemType, Listing, Transaction
from bundles.models import Bundle, BundleItem
from messaging.models import Conversation, Message


class ParticipantIntegrityTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.seller = User.objects.create_user(
            username="seller", email="seller@example.com", display_name="Seller"
        )
        cls.buyer = User.objects.create_user(
            username="buyer", email="buyer@example.com", display_name="Buyer"
        )
        cls.outsider = User.objects.create_user(
            username="outsider", email="outsider@example.com", display_name="Outsider"
        )
        cls.admin = User.objects.create_superuser(
            username="admin",
            email="admin@example.com",
            display_name="Admin",
            password="test-password",
        )
        category = ItemCategory.objects.create(category_name="Furniture")
        item_type = ItemType.objects.create(category=category, item_type_name="Chair")
        cls.listing = Listing.objects.create(
            seller=cls.seller,
            item_type=item_type,
            title="Chair",
            condition="GOOD",
            listing_price=10,
            fulfillment_option="PICKUP",
        )
        cls.other_listing = Listing.objects.create(
            seller=cls.outsider,
            item_type=item_type,
            title="Desk",
            condition="GOOD",
            listing_price=20,
            fulfillment_option="PICKUP",
        )
        cls.bundle = Bundle.objects.create(buyer=cls.buyer, space="BEDROOM")
        cls.bundle_item = BundleItem.objects.create(
            bundle=cls.bundle, listing=cls.listing, listing_price_snapshot=10
        )

    def record(self, model, **overrides):
        values = dict(listing=self.listing, buyer=self.buyer, seller=self.seller)
        if model is Transaction:
            values["agreed_price"] = 10
        values.update(overrides)
        return model(**values)

    def test_self_roles_rejected_by_clean_and_save(self):
        for model in (Transaction, Conversation):
            for operation in ("full_clean", "save"):
                with self.subTest(model=model.__name__, operation=operation):
                    obj = self.record(model, buyer=self.seller)
                    with self.assertRaises(ValidationError):
                        getattr(obj, operation)()

    def test_fake_seller_cannot_hide_self_purchase(self):
        for model in (Transaction, Conversation):
            with self.subTest(model=model.__name__):
                with self.assertRaises(ValidationError):
                    self.record(model, buyer=self.seller, seller=self.outsider).save()

    def test_wrong_seller_rejected(self):
        for model in (Transaction, Conversation):
            with self.subTest(model=model.__name__):
                with self.assertRaises(ValidationError):
                    self.record(model, seller=self.outsider).save()

    def test_valid_transaction_and_conversation_save(self):
        for model in (Transaction, Conversation):
            obj = self.record(model)
            obj.save()
            self.assertIsNotNone(obj.pk)

    def test_self_roles_rejected_by_database_even_when_validation_bypassed(self):
        for model in (Transaction, Conversation):
            with self.subTest(model=model.__name__):
                with self.assertRaises(IntegrityError), transaction.atomic():
                    model.objects.bulk_create([self.record(model, buyer=self.seller)])

    def test_bundle_context_owner_is_validated(self):
        with self.assertRaises(ValidationError):
            self.record(
                Conversation,
                listing=self.other_listing,
                bundle_item=self.bundle_item,
                buyer=self.seller,
                seller=self.outsider,
            ).save()

    def test_nonparticipant_message_rejected_by_clean_and_save(self):
        conversation = self.record(Conversation)
        conversation.save()
        for operation in ("full_clean", "save"):
            with self.subTest(operation=operation):
                message = Message(
                    conversation=conversation,
                    sender=self.outsider,
                    body_text="Not my conversation",
                )
                with self.assertRaises(ValidationError):
                    getattr(message, operation)()

    def test_both_participants_can_send(self):
        conversation = self.record(Conversation)
        conversation.save()
        for sender in (self.buyer, self.seller):
            Message.objects.create(
                conversation=conversation, sender=sender, body_text="Hello"
            )
        self.assertEqual(conversation.messages.count(), 2)

    def test_message_sender_edit_rejected(self):
        conversation = self.record(Conversation)
        conversation.save()
        message = Message.objects.create(
            conversation=conversation, sender=self.buyer, body_text="Hello"
        )
        message.sender = self.outsider
        with self.assertRaises(ValidationError):
            message.save(update_fields=["sender"])

    def test_partial_save_validates_fields_that_will_actually_be_written(self):
        first = self.record(Conversation)
        first.save()
        second = self.record(Conversation, buyer=self.outsider)
        second.save()
        message = Message.objects.create(
            conversation=first, sender=self.buyer, body_text="Hello"
        )
        message.conversation = second
        message.sender = (
            self.outsider
        )  # Not included in update_fields; must not mask the invalid persisted sender.
        with self.assertRaises(ValidationError):
            message.save(update_fields=["conversation"])
        message.refresh_from_db()
        self.assertEqual(message.conversation_id, first.pk)

    def test_changing_participants_cannot_orphan_existing_senders(self):
        conversation = self.record(Conversation)
        conversation.save()
        Message.objects.create(
            conversation=conversation, sender=self.buyer, body_text="Hello"
        )
        conversation.buyer = self.outsider
        with self.assertRaises(ValidationError):
            conversation.save()

    def test_admin_shows_role_errors_instead_of_saving(self):
        self.client.force_login(self.admin)
        for model in (Transaction, Conversation):
            with self.subTest(model=model.__name__):
                data = dict(
                    listing=self.listing.pk,
                    buyer=self.seller.pk,
                    seller=self.seller.pk,
                    _save="Save",
                )
                if model is Transaction:
                    data.update(agreed_price="10.00", status="PENDING_PICKUP")
                response = self.client.post(
                    reverse(
                        f"admin:{model._meta.app_label}_{model._meta.model_name}_add"
                    ),
                    data,
                )
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.context["adminform"].form.errors)
                self.assertFalse(model.objects.exists())

    def test_admin_rejects_outside_sender(self):
        conversation = self.record(Conversation)
        conversation.save()
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("admin:messaging_message_add"),
            dict(
                conversation=conversation.pk,
                sender=self.outsider.pk,
                body_text="Hello",
                _save="Save",
            ),
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("sender", response.context["adminform"].form.errors)
        self.assertFalse(Message.objects.exists())

    def test_invalid_foreign_keys_report_validation_errors(self):
        for model in (Transaction, Conversation):
            with self.subTest(model=model.__name__):
                with self.assertRaises(ValidationError):
                    self.record(model, listing_id=999999).full_clean()

    def test_new_conversation_requires_explicit_listing(self):
        for extra in ({}, {"bundle_item": self.bundle_item}):
            with self.subTest(extra=extra):
                with self.assertRaises(ValidationError):
                    self.record(Conversation, listing=None, **extra).save()

    def test_bundle_item_must_match_listing(self):
        with self.assertRaises(ValidationError):
            self.record(
                Conversation,
                listing=self.other_listing,
                seller=self.outsider,
                bundle_item=self.bundle_item,
            ).save()

    def test_matching_bundle_context_is_allowed(self):
        self.record(Conversation, bundle_item=self.bundle_item).save()

    def test_listing_deletion_preserves_history_and_allows_message_updates(self):
        conversation = self.record(
            Conversation, listing=self.other_listing, seller=self.outsider
        )
        conversation.save()
        message = Message.objects.create(
            conversation=conversation, sender=self.buyer, body_text="History"
        )
        self.other_listing.delete()
        conversation.refresh_from_db()
        self.assertIsNone(conversation.listing_id)
        conversation.save()
        message.is_read = True
        message.save(update_fields=["is_read"])
        self.assertTrue(Message.objects.filter(pk=message.pk).exists())

    def test_existing_listing_cannot_be_cleared_manually(self):
        conversation = self.record(Conversation)
        conversation.save()
        conversation.listing = None
        with self.assertRaises(ValidationError):
            conversation.save()

    def test_admin_requires_listing_for_new_conversation(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("admin:messaging_conversation_add"),
            dict(
                buyer=self.buyer.pk,
                seller=self.seller.pk,
                bundle_item=self.bundle_item.pk,
                _save="Save",
            ),
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("listing", response.context["adminform"].form.errors)
        self.assertFalse(Conversation.objects.exists())

    def test_listing_owner_cannot_change_after_transaction(self):
        self.record(Transaction).save()
        self.listing.seller = self.buyer
        with self.assertRaises(ValidationError):
            self.listing.save(update_fields=["seller"])

    def test_listing_owner_cannot_change_after_conversation(self):
        self.record(Conversation).save()
        self.listing.seller = self.buyer
        with self.assertRaises(ValidationError):
            self.listing.save()

    def test_unused_listing_owner_can_be_corrected(self):
        self.other_listing.seller = self.seller
        self.other_listing.save(update_fields=["seller"])
        self.other_listing.refresh_from_db()
        self.assertEqual(self.other_listing.seller_id, self.seller.pk)

    def test_bundle_item_cannot_be_retargeted_after_conversation(self):
        self.record(Conversation, bundle_item=self.bundle_item).save()
        self.bundle_item.listing = self.other_listing
        with self.assertRaises(ValidationError):
            self.bundle_item.save(update_fields=["listing"])

    def test_admin_valid_workflow(self):
        self.client.force_login(self.admin)
        for model in (Transaction, Conversation):
            with self.subTest(model=model.__name__):
                data = dict(
                    listing=self.listing.pk,
                    buyer=self.buyer.pk,
                    seller=self.seller.pk,
                    _save="Save",
                )
                if model is Transaction:
                    data.update(agreed_price="10.00", status="PENDING_PICKUP")
                response = self.client.post(
                    reverse(
                        f"admin:{model._meta.app_label}_{model._meta.model_name}_add"
                    ),
                    data,
                )
                self.assertEqual(response.status_code, 302)
        conversation = Conversation.objects.get()
        response = self.client.post(
            reverse("admin:messaging_message_add"),
            dict(
                conversation=conversation.pk,
                sender=self.buyer.pk,
                body_text="Hello",
                _save="Save",
            ),
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Message.objects.count(), 1)

    def test_admin_can_edit_orphaned_history(self):
        conversation = self.record(
            Conversation, listing=self.other_listing, seller=self.outsider
        )
        conversation.save()
        self.other_listing.delete()
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("admin:messaging_conversation_change", args=[conversation.pk]),
            dict(buyer=self.buyer.pk, seller=self.outsider.pk, _save="Save"),
        )
        self.assertEqual(response.status_code, 302)

    def test_partial_save_ignores_unwritten_invalid_values(self):
        conversation = self.record(Conversation)
        conversation.save()
        message = Message.objects.create(
            conversation=conversation, sender=self.buyer, body_text="Hello"
        )
        message.sender = self.outsider
        message.is_read = True
        message.save(update_fields=["is_read"])
        message.refresh_from_db()
        self.assertEqual(message.sender_id, self.buyer.pk)
        self.assertTrue(message.is_read)

    def test_deferred_save_preserves_implicit_update_fields(self):
        from datetime import timedelta
        from unittest.mock import patch

        original_updated_at = self.other_listing.updated_at
        deferred = Listing.objects.only("title").get(pk=self.other_listing.pk)
        deferred.title = "Corrected title"
        with patch(
            "django.utils.timezone.now",
            return_value=original_updated_at + timedelta(days=1),
        ):
            deferred.save()
        self.other_listing.refresh_from_db()
        self.assertEqual(self.other_listing.title, "Corrected title")
        self.assertEqual(self.other_listing.updated_at, original_updated_at)

    def test_legacy_bundle_only_conversation_can_be_edited(self):
        legacy = Conversation(
            buyer=self.buyer, seller=self.seller, bundle_item=self.bundle_item
        )
        Conversation.objects.bulk_create(
            [legacy]
        )  # Simulate a row valid before the new creation rule.
        legacy = Conversation.objects.get(pk=legacy.pk)
        legacy.save()

    def test_adding_context_to_orphan_requires_listing(self):
        conversation = self.record(
            Conversation, listing=self.other_listing, seller=self.outsider
        )
        conversation.save()
        self.other_listing.delete()
        conversation.refresh_from_db()
        conversation.seller = self.seller
        conversation.bundle_item = self.bundle_item
        with self.assertRaises(ValidationError):
            conversation.save()
