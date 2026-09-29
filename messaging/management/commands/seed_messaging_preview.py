"""Seed only the isolated local preview database with Messaging examples."""

import secrets
import uuid
from decimal import Decimal

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from bundles.models import Bundle, BundleCategory, BundleItem
from marketplace.models import ItemType, Listing, Transaction, User
from messaging.models import Conversation, DealProposal, Message


def preview_id(name):
    """Stable IDs let the preview command add missing cases without duplicates."""
    return uuid.uuid5(uuid.NAMESPACE_URL, f"moveon/messaging-preview/{name}")


def seed_status_cases():
    """Add isolated conversations covering every trade summary and Bundle outcome."""
    with transaction.atomic():
        alex = User.objects.get(username="alex")
        maya = User.objects.get(username="maya")
        jamie = User.objects.get(username="jamie")
        types = {
            "Desk": ItemType.objects.get(category__category_name="Furniture", item_type_name="Desk"),
            "Lamp": ItemType.objects.get(category__category_name="Home Decor", item_type_name="Lamp"),
            "Rug": ItemType.objects.get(category__category_name="Home Decor", item_type_name="Rug"),
        }

        def listing(name, kind, price, status=Listing.Status.ACTIVE, bundle=False):
            item, _ = Listing.objects.get_or_create(
                listing_id=preview_id(f"listing/{name}"),
                defaults={
                    "seller": alex,
                    "item_type": types[kind],
                    "title": f"Preview: {name}",
                    "description": "Isolated Messaging status example.",
                    "condition": Listing.Condition.GOOD,
                    "listing_price": Decimal(price),
                    "benchmark_price": Decimal(price),
                    "bundle_eligible": bundle,
                    "fulfillment_option": Listing.Fulfillment.PICKUP,
                    "status": status,
                },
            )
            return item

        def conversation(item, *, buyer=maya, bundle_item=None):
            thread, _ = Conversation.objects.get_or_create(
                buyer=buyer, seller=alex, listing=item,
                defaults={"bundle_item": bundle_item},
            )
            return thread

        def proposal(thread, name, price, status, *, replaces=None, deal=None):
            offer, _ = DealProposal.objects.get_or_create(
                pk=preview_id(f"proposal/{name}"),
                defaults={
                    "conversation": thread,
                    "agreed_price": Decimal(price),
                    "status": status,
                    "replaces": replaces,
                    "client_request_id": preview_id(f"request/{name}"),
                    "transaction": deal,
                },
            )
            return offer

        negotiating = conversation(listing("Negotiating desk", "Desk", "25.00"))
        Message.objects.get_or_create(
            conversation=negotiating, sender=maya,
            client_request_id=preview_id("message/negotiating"),
            defaults={"body_text": "Hi, is this desk still available?"},
        )

        revised = conversation(listing("Revised offer awaiting buyer", "Desk", "55.00"))
        old = proposal(revised, "revised-old", "47.00", DealProposal.Status.SUPERSEDED)
        proposal(revised, "revised-current", "43.00", DealProposal.Status.AWAITING_BUYER,
                 replaces=old)

        reserved = listing("Offer reserved for pickup", "Desk", "25.00",
                           Listing.Status.RESERVED)
        reserved_thread = conversation(reserved)
        ordinary_deal, _ = Transaction.objects.get_or_create(
            transaction_id=preview_id("transaction/ordinary"),
            defaults={
                "conversation": reserved_thread, "listing": reserved,
                "buyer": maya, "seller": alex, "agreed_price": Decimal("30.00"),
                "benchmark_price_snapshot": reserved.benchmark_price,
                "status": Transaction.Status.PENDING_PICKUP,
            },
        )
        proposal(reserved_thread, "ordinary-confirmed", "30.00",
                 DealProposal.Status.CONFIRMED, deal=ordinary_deal)

        conversation(listing("Unavailable listing", "Desk", "20.00",
                             Listing.Status.INACTIVE))

        bundle, _ = Bundle.objects.get_or_create(
            bundle_id=preview_id("bundle/three-outcomes"),
            defaults={
                "buyer": maya, "space": Bundle.Space.BEDROOM,
                "selected_tier": Bundle.Tier.BEST_VALUE,
                "status": Bundle.Status.PARTIALLY_ACCEPTED,
            },
        )
        bundle_cases = (
            ("Bundle request pending", "Lamp", "18.00", "15.00",
             BundleItem.ItemStatus.REQUESTED, Listing.Status.ACTIVE),
            ("Bundle accepted for pickup", "Desk", "45.00", "39.00",
             BundleItem.ItemStatus.ACCEPTED, Listing.Status.RESERVED),
            ("Bundle request declined", "Rug", "28.00", "24.00",
             BundleItem.ItemStatus.DECLINED, Listing.Status.ACTIVE),
        )
        for name, kind, public_price, bundle_price, item_status, listing_status in bundle_cases:
            item_listing = listing(name, kind, public_price, listing_status, bundle=True)
            bundle_item, _ = BundleItem.objects.get_or_create(
                bundle=bundle, listing=item_listing,
                defaults={
                    "listing_price_snapshot": Decimal(public_price),
                    "proposed_bundle_price": Decimal(bundle_price),
                    "final_price": Decimal(bundle_price) if item_status == BundleItem.ItemStatus.ACCEPTED else None,
                    "item_status": item_status,
                    "responded_at": timezone.now() if item_status != BundleItem.ItemStatus.REQUESTED else None,
                },
            )
            BundleCategory.objects.get_or_create(
                bundle=bundle, item_type=types[kind],
                defaults={"bundle_item": bundle_item},
            )
            conversation(item_listing, bundle_item=bundle_item)
            if item_status == BundleItem.ItemStatus.ACCEPTED:
                Transaction.objects.get_or_create(
                    transaction_id=preview_id("transaction/bundle-accepted"),
                    defaults={
                        "listing": item_listing, "buyer": maya, "seller": alex,
                        "bundle": bundle, "bundle_item": bundle_item,
                        "agreed_price": Decimal(bundle_price),
                        "benchmark_price_snapshot": item_listing.benchmark_price,
                        "status": Transaction.Status.PENDING_PICKUP,
                    },
                )
                # The second buyer sees only Unavailable, never Maya's price.
                conversation(item_listing, buyer=jamie)


class Command(BaseCommand):
    help = "Seed isolated Messaging preview accounts and all six trade summary states."

    def handle(self, *args, **options):
        if settings.DATABASES["default"]["NAME"].name != "messaging_preview.sqlite3":
            raise CommandError("This command runs only with moveon.settings.messaging_preview.")
        call_command("seed_demo_data", stdout=self.stdout)
        for username in ("alex", "maya", "jamie"):
            user = User.objects.get(username=username)
            campus_email = f"{username}@illinois.edu"
            if user.email != campus_email:
                user.email = campus_email
                user.save(update_fields=["email"])
            password = None
            update_fields = ["email_verified", "email_verified_at"]
            if not user.has_usable_password():
                password = secrets.token_urlsafe(12)
                user.set_password(password)
                update_fields.append("password")
            user.email_verified = True
            user.email_verified_at = timezone.now()
            user.save(update_fields=update_fields)
            if password:
                self.stdout.write(f"Local preview account {username}: {password}")
            else:
                self.stdout.write(
                    f"Local preview account {username}: existing password unchanged; "
                    f"reset it with manage.py changepassword {username} "
                    "--settings=moveon.settings.messaging_preview"
                )
        seed_status_cases()
        self.stdout.write(self.style.SUCCESS("Messaging preview trade states are ready."))
