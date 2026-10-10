"""Create fictional activity only in the dedicated local A5 preview database."""

import secrets
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connections, transaction

from marketplace.email_state import sync_campus_email
from marketplace.models import ItemCategory, ItemType, Listing, Transaction, User
from messaging.models import Conversation, Message


PREVIEW_SETTINGS = "moveon.settings.a5_preview"
MOCK_USERS = (
    ("mock_maya_01", "Mock Maya", True),
    ("mock_leo_02", "Mock Leo", True),
    ("mock_nora_03", "Mock Nora", False),
)
NAMESPACE = uuid.UUID("c3eb32e8-7c4f-4ee8-8b5d-2d0800bd2a50")
VERIFIED_AT = datetime(2026, 9, 1, 12, tzinfo=timezone.utc)

# number, owner, category, item type, title, price, initial listing status
MOCK_LISTINGS = (
    (1, 0, "Furniture", "Desk", "Mock Maya Desk", "80", "SOLD"),
    (2, 0, "Lighting", "Floor Lamp", "Mock Maya Floor Lamp", "25", "SOLD"),
    (3, 0, "Kitchen", "Microwave", "Mock Maya Microwave", "55", "RESERVED"),
    (4, 1, "Furniture", "Chair", "Mock Leo Chair", "45", "SOLD"),
    (5, 1, "Kitchen", "Kettle", "Mock Leo Kettle", "20", "SOLD"),
    (6, 1, "Electronics", "Monitor", "Mock Leo Monitor", "100", "ACTIVE"),
    (7, 0, "Furniture", "Bookcase", "Mock Maya Bookcase", "60", "ACTIVE"),
    (8, 0, "Furniture", "Rug", "Mock Maya Rug", "35", "ACTIVE"),
    (9, 1, "Lighting", "Desk Lamp", "Mock Leo Desk Lamp", "18", "ACTIVE"),
    (10, 1, "Sports", "Helmet", "Mock Leo Bike Helmet", "30", "ACTIVE"),
    (11, 0, "Kitchen", "Rice Cooker", "Mock Maya Rice Cooker", "40", "ACTIVE"),
    (12, 1, "Electronics", "Speaker", "Mock Leo Speaker", "32", "ACTIVE"),
    (13, 0, "Furniture", "Sofa", "Mock Maya Sofa Draft", "120", "DRAFT"),
    (14, 1, "Electronics", "Laptop Stand", "Mock Leo Stand Inactive", "16", "INACTIVE"),
)


def mock_id(label):
    return uuid.uuid5(NAMESPACE, label)


class Command(BaseCommand):
    help = "Seed the dedicated A5 mock database; preserve existing passwords and verification."
    requires_system_checks = []

    def handle(self, *args, **options):
        expected = (settings.BASE_DIR / "data" / "a5-preview.sqlite3").resolve()
        configured = settings.DATABASES["default"]
        actual = connections["default"].settings_dict
        if (settings.SETTINGS_MODULE != PREVIEW_SETTINGS
                or configured["ENGINE"] != "django.db.backends.sqlite3"
                or actual["ENGINE"] != "django.db.backends.sqlite3"
                or Path(configured["NAME"]).resolve() != expected
                or Path(actual["NAME"]).resolve() != expected):
            raise CommandError("Only a5_preview settings and its exact dedicated database are allowed.")
        if not expected.is_file():
            raise CommandError("Initialize the dedicated preview database with migrate first.")

        credentials = settings.BASE_DIR / "data" / "a5-preview-credentials.local.txt"
        new_passwords = []
        with transaction.atomic():
            names = [row[0] for row in MOCK_USERS]
            if User.objects.exclude(username__in=names).exists():
                raise CommandError("Unrecognized accounts found. Preserve this database and inspect it first.")
            users = []
            for username, display_name, verified in MOCK_USERS:
                email = username + "@illinois.edu"
                user, created = User.objects.get_or_create(
                    username=username,
                    defaults={"email": email, "display_name": display_name,
                              "email_verified": verified,
                              "email_verified_at": VERIFIED_AT if verified else None},
                )
                if (user.email != email or user.is_staff or user.is_superuser
                        or user.google_subject or user.socialaccount_set.exists()):
                    raise CommandError("Mock identity conflict. Existing account data was not overwritten.")
                if created:
                    password = secrets.token_urlsafe(18)
                    user.set_password(password)
                    user.save(update_fields=["password"])
                    new_passwords.append((username, password))
                # Existing proof and passwords are deliberately never reset.
                sync_campus_email(user)
                users.append(user)

            listings = {}
            for number, owner, category_name, type_name, title, price, status in MOCK_LISTINGS:
                category, _ = ItemCategory.objects.get_or_create(category_name=category_name)
                item_type, _ = ItemType.objects.get_or_create(category=category, item_type_name=type_name)
                listing, created = Listing.objects.get_or_create(
                    listing_id=mock_id(f"listing-{number}"),
                    defaults={"seller": users[owner], "item_type": item_type, "title": title,
                              "description": "Fictional local A5 preview item; no real sale or identity.",
                              "listing_price": Decimal(price), "retail_price": Decimal(price) * 2,
                              "condition": Listing.Condition.GOOD,
                              "fulfillment_option": Listing.Fulfillment.PICKUP,
                              "bundle_eligible": status == Listing.Status.ACTIVE, "status": status},
                )
                if listing.seller_id != users[owner].pk:
                    raise CommandError("Mock listing ownership changed; existing data was preserved.")
                if created:
                    Listing.objects.filter(pk=listing.pk).update(created_at=VERIFIED_AT + timedelta(days=number))
                listings[number] = listing

            # All participants match the listing owner; cancelled/pending states
            # match the initial ACTIVE/RESERVED listing states above.
            activities = (
                (1, 1, "70", "COMPLETED", 20),
                (2, 1, "20", "COMPLETED", 22),
                (3, 1, "50", "PENDING_PICKUP", 30),
                (4, 0, "40", "COMPLETED", 24),
                (5, 0, "15", "COMPLETED", 28),
                (6, 0, "90", "CANCELLED", 29),
            )
            for number, buyer, amount, status, day in activities:
                listing = listings[number]
                happened = datetime(2026, 9, day, 12, tzinfo=timezone.utc)
                activity, created = Transaction.objects.get_or_create(
                    transaction_id=mock_id(f"transaction-{number}"),
                    defaults={"listing": listing, "seller": listing.seller, "buyer": users[buyer],
                              "agreed_price": Decimal(amount), "status": status,
                              "completed_at": happened if status == Transaction.Status.COMPLETED else None,
                              "meetup_datetime": datetime(2026, 10, 12, 12, tzinfo=timezone.utc)
                              if status == Transaction.Status.PENDING_PICKUP else None,
                              "meetup_location": "Mock campus pickup point"},
                )
                if (activity.listing_id != listing.pk or activity.seller_id != listing.seller_id
                        or activity.buyer_id != users[buyer].pk):
                    raise CommandError("Mock transaction identity changed; existing data was preserved.")
                if created:
                    Transaction.objects.filter(pk=activity.pk).update(created_at=happened)

            for number, buyer, replied in ((7, 1, False), (8, 1, True), (9, 0, False)):
                listing = listings[number]
                happened = datetime(2026, 10, number - 6, 12, tzinfo=timezone.utc)
                chat, created = Conversation.objects.get_or_create(
                    conversation_uid=mock_id(f"conversation-{number}"),
                    defaults={"listing": listing, "seller": listing.seller, "buyer": users[buyer]},
                )
                if (chat.listing_id != listing.pk or chat.seller_id != listing.seller_id
                        or chat.buyer_id != users[buyer].pk):
                    raise CommandError("Mock conversation identity changed; existing data was preserved.")
                if created:
                    Conversation.objects.filter(pk=chat.pk).update(created_at=happened, last_message_at=happened)
                inquiry, created = Message.objects.get_or_create(
                    conversation=chat, sender=users[buyer], client_request_id=mock_id(f"inquiry-{number}"),
                    defaults={"body_text": "Mock inquiry: is this available for pickup?", "is_read": replied},
                )
                if created:
                    Message.objects.filter(pk=inquiry.pk).update(sent_at=happened)
                if replied:
                    reply, created = Message.objects.get_or_create(
                        conversation=chat, sender=listing.seller, client_request_id=mock_id(f"reply-{number}"),
                        defaults={"body_text": "Mock reply: yes, pickup is available."},
                    )
                    if created:
                        Message.objects.filter(pk=reply.pk).update(sent_at=happened + timedelta(minutes=10))
                        Conversation.objects.filter(pk=chat.pk).update(last_message_at=happened + timedelta(minutes=10))

            if new_passwords:
                credentials.touch(mode=0o600, exist_ok=True)
                with credentials.open("a", encoding="utf-8") as credential_file:
                    for username, password in new_passwords:
                        credential_file.write(f"{username}\t{password}\n")

        self.stdout.write(self.style.SUCCESS(
            f"A5 preview prepared: {User.objects.count()} mock users, "
            f"{Listing.objects.count()} listings, {Transaction.objects.count()} transactions "
            f"and {Conversation.objects.count()} conversations."
        ))
        self.stdout.write(f"Database: {expected}")
        self.stdout.write(f"Local password file: {credentials} (passwords are not printed or reset)")
