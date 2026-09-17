from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction as db_transaction
from django.utils import timezone

from bundles.models import Bundle, BundleCategory, BundleItem
from marketplace.models import (
    ItemCategory,
    ItemType,
    Listing,
    PriceRecommendation,
    Transaction,
)
from messaging.models import Conversation, Message

User = get_user_model()


class Command(BaseCommand):
    """Seeds realistic demo data across all 11 MoveOn models for Part 4 validation."""

    help = "Creates demo users, listings, bundles, messages, and a transaction for grading/demo purposes."

    def handle(self, *args, **options):
        with db_transaction.atomic():
            users = self._seed_users()
            categories, item_types = self._seed_taxonomy()
            listings = self._seed_listings(users, item_types)
            self._seed_price_recommendations(listings)
            self._seed_bundle(users, item_types, listings)
            self._seed_messaging(users, listings)
            self._seed_transaction(users, listings)

        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded {User.objects.count()} users, {Listing.objects.count()} listings, "
                f"{Bundle.objects.count()} bundle(s), {Conversation.objects.count()} conversation(s), "
                f"{Transaction.objects.count()} transaction(s)."
            )
        )

    def _seed_users(self):
        specs = [
            ("alex", "alex@illinois.edu", "Alex"),
            ("jamie", "jamie@illinois.edu", "Jamie"),
            ("sam", "sam@illinois.edu", "Sam"),
            ("maya", "maya@illinois.edu", "Maya"),
        ]
        users = {}
        for username, email, display_name in specs:
            user, created = User.objects.get_or_create(
                username=username,
                defaults={
                    "email": email,
                    "display_name": display_name,
                    "email_verified": True,
                },
            )
            if created:
                user.set_password("password123")
                user.save()
            users[display_name] = user
        return users

    def _seed_taxonomy(self):
        taxonomy = {
            "Furniture": ["Sofa", "Desk", "Chair", "Dresser"],
            "Electronics": ["Television", "Monitor", "Speaker"],
            "Home Decor": ["Rug", "Lamp"],
            "Appliances": ["Microwave"],
        }
        categories = {}
        item_types = {}
        for category_name, type_names in taxonomy.items():
            category, _ = ItemCategory.objects.get_or_create(
                category_name=category_name
            )
            categories[category_name] = category
            for type_name in type_names:
                item_type, _ = ItemType.objects.get_or_create(
                    category=category, item_type_name=type_name
                )
                item_types[type_name] = item_type
        return categories, item_types

    def _seed_listings(self, users, item_types):
        today = date.today()
        specs = [
            (
                "Blue Sofa",
                "Alex",
                "Sofa",
                65,
                90,
                "GOOD",
                True,
                today + timedelta(days=20),
            ),
            (
                "Floor Lamp",
                "Jamie",
                "Lamp",
                15,
                25,
                "LIKE_NEW",
                True,
                today + timedelta(days=10),
            ),
            (
                "Television",
                "Sam",
                "Television",
                120,
                180,
                "GOOD",
                False,
                today + timedelta(days=30),
            ),
            (
                "Gray Rug",
                "Maya",
                "Rug",
                25,
                40,
                "GOOD",
                True,
                today + timedelta(days=15),
            ),
            ("Desk", "Alex", "Desk", 45, 70, "FAIR", False, today + timedelta(days=20)),
            (
                "Microwave",
                "Jamie",
                "Microwave",
                30,
                55,
                "GOOD",
                False,
                today + timedelta(days=10),
            ),
            (
                "Dresser",
                "Sam",
                "Dresser",
                55,
                85,
                "GOOD",
                False,
                today + timedelta(days=30),
            ),
            (
                "Desk Chair",
                "Maya",
                "Chair",
                18,
                24,
                "FAIR",
                False,
                today - timedelta(days=2),
            ),
        ]
        listings = {}
        for (
            title,
            owner,
            type_name,
            price,
            retail,
            condition,
            bundle_eligible,
            move_out,
        ) in specs:
            listing, _ = Listing.objects.get_or_create(
                title=title,
                seller=users[owner],
                defaults={
                    "item_type": item_types[type_name],
                    "description": f"{title} in {condition.replace('_', ' ').title()} condition.",
                    "condition": condition,
                    "listing_price": price,
                    "retail_price": retail,
                    "benchmark_price": (Decimal(price) * Decimal("1.1")).quantize(
                        Decimal("0.01")
                    ),
                    "benchmark_low": (Decimal(price) * Decimal("0.85")).quantize(
                        Decimal("0.01")
                    ),
                    "benchmark_high": (Decimal(price) * Decimal("1.25")).quantize(
                        Decimal("0.01")
                    ),
                    "move_out_date": move_out,
                    "minimum_price": (Decimal(price) * Decimal("0.7")).quantize(
                        Decimal("0.01")
                    ),
                    "bundle_eligible": bundle_eligible,
                    "fulfillment_option": Listing.Fulfillment.PICKUP,
                    "status": Listing.Status.SOLD
                    if title == "Desk Chair"
                    else Listing.Status.ACTIVE,
                },
            )
            listings[title] = listing
        return listings

    def _seed_price_recommendations(self, listings):
        PriceRecommendation.objects.get_or_create(
            listing=listings["Blue Sofa"],
            previous_price=65,
            recommended_price=55,
            defaults={"status": PriceRecommendation.Status.PENDING},
        )
        PriceRecommendation.objects.get_or_create(
            listing=listings["Desk"],
            previous_price=45,
            recommended_price=39,
            defaults={
                "applied_price": 40,
                "status": PriceRecommendation.Status.MODIFIED,
                "responded_at": timezone.now(),
            },
        )

    def _seed_bundle(self, users, item_types, listings):
        # Sam is deliberately the buyer here (not Alex, who owns the Sofa listing)
        # so the bundle demonstrates a realistic cross-seller purchase rather than
        # a buyer "buying" their own listing.
        bundle, _ = Bundle.objects.get_or_create(
            buyer=users["Sam"],
            space=Bundle.Space.LIVING_ROOM,
            defaults={
                "selected_tier": Bundle.Tier.BEST_VALUE,
                "status": Bundle.Status.DRAFT,
            },
        )
        for type_name in ["Sofa", "Rug", "Lamp"]:
            BundleCategory.objects.get_or_create(
                bundle=bundle, item_type=item_types[type_name]
            )

        item_specs = [
            ("Blue Sofa", 65, 60),
            ("Gray Rug", 25, 22),
            ("Floor Lamp", 15, 13),
        ]
        for title, snapshot, proposed in item_specs:
            BundleItem.objects.get_or_create(
                bundle=bundle,
                listing=listings[title],
                defaults={
                    "listing_price_snapshot": snapshot,
                    "proposed_bundle_price": proposed,
                    "item_status": BundleItem.ItemStatus.SELECTED,
                },
            )

    def _seed_messaging(self, users, listings):
        conversation, _ = Conversation.objects.get_or_create(
            buyer=users["Alex"],
            seller=users["Maya"],
            listing=listings["Gray Rug"],
            defaults={"last_message_at": timezone.now()},
        )
        message_bodies = [
            (users["Alex"], "Hi! Is the gray rug still available?"),
            (users["Maya"], "Yes, still up for grabs. Want to meet this weekend?"),
            (users["Alex"], "Works for me, I'll come by Saturday."),
        ]
        for sender, body in message_bodies:
            Message.objects.get_or_create(
                conversation=conversation, sender=sender, body_text=body
            )

    def _seed_transaction(self, users, listings):
        Transaction.objects.get_or_create(
            listing=listings["Desk Chair"],
            buyer=users["Alex"],
            seller=users["Maya"],
            defaults={
                "agreed_price": 18,
                "benchmark_price_snapshot": 24,
                "status": Transaction.Status.COMPLETED,
                "completed_at": timezone.now(),
            },
        )
