"""Add only A4's private-chart examples for an existing campus account."""

import uuid
from collections import Counter
from datetime import date, datetime, timedelta, timezone as datetime_timezone
from decimal import Decimal
from pathlib import Path

from django.contrib.auth.hashers import make_password
from django.core.exceptions import MultipleObjectsReturned, ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import IntegrityError, connections, transaction
from django.utils import timezone

from marketplace.auth_backend import has_campus_access
from marketplace.models import ItemCategory, ItemType, Listing, Transaction, User
from messaging.models import Conversation, Message


NAMESPACE = uuid.UUID("bcb0b3c0-36d8-4dd6-9608-345643d24fde")

# From seed_demo_data: title, owner, category, type, price, retail, condition,
# bundle eligibility and move-out offset. Maya's role becomes the target user.
LISTINGS = (
    ("Blue Sofa", "alex", "Furniture", "Sofa", "65", "90", "GOOD", True, 20),
    ("Floor Lamp", "jamie", "Home Decor", "Lamp", "15", "25", "LIKE_NEW", True, 10),
    ("Desk", "alex", "Furniture", "Desk", "45", "70", "FAIR", False, 20),
    ("Desk Chair", "maya", "Furniture", "Chair", "18", "24", "FAIR", False, -2),
    ("Gray Rug", "maya", "Home Decor", "Rug", "25", "40", "GOOD", True, 15),
)

# A4 purchase amounts/dates plus its completed Desk Chair sale to Alex.
ACTIVITIES = (
    ("Blue Sofa", "maya", "65", 21),
    ("Floor Lamp", "maya", "15", 23),
    ("Desk", "maya", "33", 25),
    ("Desk Chair", "alex", "18", 27),
)


class Command(BaseCommand):
    help = "Add fictional A4 chart activity to an existing verified campus account."
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument("--username", required=True, help="Existing campus username.")

    def handle(self, *args, **options):
        database = connections["default"].settings_dict
        if database["ENGINE"] != "django.db.backends.sqlite3":
            raise CommandError("This command expects the project's SQLite database.")
        database_path = Path(database["NAME"]).resolve()
        if not database_path.is_file():
            raise CommandError("Working database is missing; preserve and locate it first.")
        self.stdout.write(f"Database: {database_path}")

        counts = Counter()
        try:
            with transaction.atomic():
                try:
                    target = User.objects.select_for_update().get(username=options["username"])
                except User.DoesNotExist as exc:
                    raise CommandError("Target user must already exist.") from exc
                if not has_campus_access(target):
                    raise CommandError("Target user must have current verified campus access.")
                self._seed(target, counts)
        except (ValidationError, IntegrityError, MultipleObjectsReturned) as exc:
            raise CommandError("Demo data conflict; all writes were rolled back.") from exc

        self.stdout.write(f"Target: {target.username} (id={target.pk})")
        self.stdout.write(self.style.SUCCESS("Added demo records: " + ", ".join(
            f"{name}={counts[name]}"
            for name in ("participants", "categories", "item_types", "listings",
                         "transactions", "conversations", "messages")
        )))
        self.stdout.write("Fictional demo activity only; existing records were not reset.")

    @staticmethod
    def _identifier(target, label):
        return uuid.uuid5(NAMESPACE, f"account:{target.pk}:{label}")

    @staticmethod
    def _ensure(model, lookup, defaults, identity, counts, counter):
        obj, created = model.objects.get_or_create(**lookup, defaults=defaults)
        if any(getattr(obj, field) != value for field, value in identity.items()):
            raise CommandError(f"{model.__name__} demo identifier/ownership conflict; no writes committed.")
        # Validate existing relationships too, without saving or resetting edits.
        obj.full_clean()
        counts[counter] += int(created)
        return obj, created

    def _participant(self, target, role, counts):
        username = f"a5_demo_{target.pk}_{role}"
        email = f"a5-demo-{target.pk}-{role}@example.invalid"
        if User.objects.filter(email__iexact=email).exclude(username=username).exists():
            raise CommandError("Demo participant email identifier conflict; no writes committed.")
        user, _ = self._ensure(
            User, {"username": username},
            {"email": email, "display_name": f"Demo {role.title()}",
             "password": make_password(None), "is_active": False,
             "is_staff": False, "is_superuser": False,
             "email_verified": False, "email_verified_at": None, "google_subject": None},
            {"email": email}, counts, "participants",
        )
        if (user.pk == target.pk or user.is_active or user.has_usable_password()
                or user.is_staff or user.is_superuser or user.email_verified
                or user.email_verified_at is not None or user.google_subject
                or user.socialaccount_set.exists()):
            raise CommandError("Demo participant identity conflict; no writes committed.")
        return user

    def _seed(self, target, counts):
        users = {"maya": target}
        users.update({role: self._participant(target, role, counts) for role in ("alex", "jamie")})
        listings = {}
        today = date.today()
        for title, owner, category_name, type_name, price, retail, condition, eligible, offset in LISTINGS:
            category, _ = self._ensure(
                ItemCategory, {"category_name": category_name}, {}, {}, counts, "categories",
            )
            item_type, _ = self._ensure(
                ItemType, {"category": category, "item_type_name": type_name}, {},
                {"category_id": category.pk}, counts, "item_types",
            )
            amount = Decimal(price)
            listing, _ = self._ensure(
                Listing, {"listing_id": self._identifier(target, f"listing:{title}")},
                {"seller": users[owner], "item_type": item_type, "title": title,
                 "description": f"Demo: fictional A4 {title}; no real item or sale.",
                 "condition": condition, "listing_price": amount, "retail_price": Decimal(retail),
                 "benchmark_price": (amount * Decimal("1.1")).quantize(Decimal("0.01")),
                 "benchmark_low": (amount * Decimal("0.85")).quantize(Decimal("0.01")),
                 "benchmark_high": (amount * Decimal("1.25")).quantize(Decimal("0.01")),
                 "minimum_price": (amount * Decimal("0.7")).quantize(Decimal("0.01")),
                 "move_out_date": today + timedelta(days=offset), "bundle_eligible": eligible,
                 "fulfillment_option": Listing.Fulfillment.BOTH if title == "Blue Sofa"
                 else Listing.Fulfillment.PICKUP,
                 # Completed purchases must not leave their demo items for sale.
                 "status": Listing.Status.ACTIVE if title == "Gray Rug" else Listing.Status.SOLD},
                {"seller_id": users[owner].pk}, counts, "listings",
            )
            listings[title] = listing

        for title, buyer, amount, day in ACTIVITIES:
            listing = listings[title]
            completed_at = datetime(2026, 9, day, 12, tzinfo=datetime_timezone.utc)
            activity, created = self._ensure(
                Transaction, {"transaction_id": self._identifier(target, f"transaction:{title}")},
                {"listing": listing, "seller": listing.seller, "buyer": users[buyer],
                 "agreed_price": Decimal(amount), "status": Transaction.Status.COMPLETED,
                 "completed_at": completed_at,
                 "benchmark_price_snapshot": Decimal("24") if title == "Desk Chair" else None},
                {"listing_id": listing.pk, "seller_id": listing.seller_id,
                 "buyer_id": users[buyer].pk}, counts, "transactions",
            )
            expected_status = {
                Transaction.Status.COMPLETED: Listing.Status.SOLD,
                Transaction.Status.PENDING_PICKUP: Listing.Status.RESERVED,
                Transaction.Status.CANCELLED: Listing.Status.ACTIVE,
            }[activity.status]
            if listing.status != expected_status:
                raise CommandError("Demo transaction/listing status conflict; no writes committed.")
            if created and title != "Desk Chair":
                # A4 fixed purchase created_at; only newly inserted timestamps change.
                Transaction.objects.filter(pk=activity.pk).update(created_at=completed_at)

        rug = listings["Gray Rug"]
        for role in ("alex", "jamie"):
            chat, _ = self._ensure(
                Conversation, {"conversation_uid": self._identifier(target, f"rug:{role}")},
                {"listing": rug, "seller": target, "buyer": users[role],
                 "last_message_at": timezone.now() if role == "alex" else None},
                {"listing_id": rug.pk, "seller_id": target.pk, "buyer_id": users[role].pk},
                counts, "conversations",
            )
            messages = (
                ("alex", "Hi! Is the gray rug still available?"),
                ("maya", "Yes, still up for grabs. Want to meet this weekend?"),
                ("alex", "Works for me, I'll come by Saturday."),
            ) if role == "alex" else (
                ("jamie", "Fictional A4 inquiry: is pickup available?"),
            )
            for index, (sender, body) in enumerate(messages):
                self._ensure(
                    Message, {"client_request_id": self._identifier(target, f"rug:{role}:message:{index}")},
                    {"conversation": chat, "sender": users[sender],
                     "body_text": f"Demo: {body}", "is_read": role == "alex"},
                    {"conversation_id": chat.pk, "sender_id": users[sender].pk},
                    counts, "messages",
                )
