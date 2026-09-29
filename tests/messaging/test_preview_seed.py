"""Preview fixtures should expose each real Messaging trade state."""

from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from bundles.models import BundleItem
from marketplace.models import Listing, Transaction, User
from messaging.api import conversation_data
from messaging.management.commands import seed_messaging_preview
from messaging.models import Conversation, DealProposal


class MessagingPreviewSeedTests(TestCase):
    def test_seeded_cases_cover_six_states_and_can_be_repeated(self):
        call_command("seed_demo_data", stdout=StringIO())
        seed_messaging_preview.seed_status_cases()

        alex = User.objects.get(username="alex")
        maya = User.objects.get(username="maya")
        cases = {
            "Preview: Negotiating desk": "negotiating",
            "Preview: Bundle request pending": "action_needed",
            "Preview: Revised offer awaiting buyer": "waiting",
            "Preview: Offer reserved for pickup": "pending_pickup",
            "Preview: Bundle request declined": "declined",
            "Preview: Unavailable listing": "unavailable",
            "Preview: Bundle accepted for pickup": "pending_pickup",
        }
        for title, expected in cases.items():
            with self.subTest(title=title):
                conversation = Conversation.objects.get(
                    listing__title=title, buyer=maya, seller=alex
                )
                self.assertEqual(
                    conversation_data(conversation, alex)["trade"]["summaryState"],
                    expected,
                )

        pending = Conversation.objects.get(listing__title="Preview: Bundle request pending")
        revised = Conversation.objects.get(listing__title="Preview: Revised offer awaiting buyer")
        self.assertEqual(conversation_data(pending, maya)["trade"]["summaryState"], "waiting")
        self.assertEqual(conversation_data(revised, maya)["trade"]["summaryState"], "action_needed")
        self.assertEqual(
            list(revised.deal_proposals.values_list("status", flat=True)),
            [DealProposal.Status.SUPERSEDED, DealProposal.Status.AWAITING_BUYER],
        )

        accepted = Conversation.objects.get(
            listing__title="Preview: Bundle accepted for pickup", buyer=maya
        )
        self.assertEqual(
            conversation_data(accepted, maya)["trade"]["transaction"]["source"], "bundle"
        )
        other = Conversation.objects.get(listing=accepted.listing, buyer__username="jamie")
        other_trade = conversation_data(other, other.buyer)["trade"]
        self.assertEqual(other_trade["summaryState"], "unavailable")
        self.assertIsNone(other_trade["transaction"])

        counts = tuple(model.objects.count() for model in (
            Listing, Conversation, DealProposal, BundleItem, Transaction
        ))
        seed_messaging_preview.seed_status_cases()
        self.assertEqual(
            tuple(model.objects.count() for model in (
                Listing, Conversation, DealProposal, BundleItem, Transaction
            )),
            counts,
        )
