"""
Extra bundle-eligible inventory for the AI Bundle Builder (bundles app).

origin/week3's own seed_demo_data only covers 8 listings, most of them not
bundle_eligible, and seed_featured_bundles covers 6 more tied to a single
demo seller. Between them, only Sofa/Table/Lamp/Rug/Bookshelf/Chair/Desk/
Pillow have any bundle-eligible ACTIVE inventory - most Space -> ItemType
combinations in bundles/space_categories.py (Kitchen, Bathroom, Entire
House, Assorted) would show all-greyed-out category tiles without this.

Deliberately NOT folded into seed_demo_data.py: that command is a shared
conflict hotspot other teammates also edit; this command only adds to it
(get_or_create throughout, safe to re-run, safe to run before or after
seed_demo_data/seed_featured_bundles in any order).

Also flips the demo sellers (alex/jamie/sam/maya, moveon-featured-demo) to
campus-access-eligible with a known local password, so a developer can
actually log in as a bundle seller to accept/decline requests end to end.
LOCAL DEVELOPMENT ONLY - like seed_demo_data's own known-password users,
never run this against a database anyone else can reach.
"""

from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from marketplace.featured import DEMO_USERNAME
from marketplace.models import ItemCategory, ItemType, Listing

User = get_user_model()

LOCAL_PASSWORD = "previewpass123"

# Extra bundle-eligible listings covering the Living Room category grid
# (Sofa, Television, Rug, Curtains, Coffee Table, Lamp, Shelf, Decor).
# Several of these item types have no listings at all elsewhere, and the
# ones that do only have one each - the AI Bundle Builder needs multiple
# distinct candidates per category to produce meaningfully different
# Budget/Best Value/Premium picks. (title, owner, type_name, price,
# condition, move_out_days)
LIVING_ROOM_SPECS = [
    ("Compact Loveseat", "jamie", "Sofa", 45, "FAIR", 18),
    ("Sectional Sofa", "sam", "Sofa", 110, "LIKE_NEW", 25),
    ("32-inch TV", "maya", "Television", 60, "FAIR", 12),
    ("55-inch Smart TV", "alex", "Television", 200, "LIKE_NEW", 28),
    ("Refurbished Flatscreen", "jamie", "Television", 85, "GOOD", 20),
    ("Small Area Rug", "jamie", "Rug", 18, "FAIR", 14),
    ("Patterned Wool Rug", "sam", "Rug", 48, "LIKE_NEW", 22),
    ("Blackout Curtains", "alex", "Curtains", 12, "GOOD", 16),
    ("Linen Curtain Panels", "maya", "Curtains", 28, "LIKE_NEW", 24),
    ("Sheer Window Curtains", "sam", "Curtains", 9, "FAIR", 10),
    ("Small Coffee Table", "jamie", "Coffee Table", 22, "FAIR", 19),
    ("Glass Coffee Table", "sam", "Coffee Table", 58, "LIKE_NEW", 27),
    ("Rustic Wood Coffee Table", "alex", "Coffee Table", 40, "GOOD", 21),
    ("Desk Lamp", "alex", "Lamp", 10, "GOOD", 15),
    ("Modern Floor Lamp", "maya", "Lamp", 32, "NEW", 26),
    ("Small Bookshelf", "jamie", "Shelf", 20, "GOOD", 17),
    ("Tall Shelving Unit", "sam", "Shelf", 45, "LIKE_NEW", 23),
    ("Cube Storage Shelf", "alex", "Shelf", 30, "GOOD", 20),
    ("Wall Art Set", "alex", "Decor", 8, "GOOD", 13),
    ("Decorative Vase Set", "maya", "Decor", 15, "NEW", 22),
    ("Framed Prints Bundle", "sam", "Decor", 11, "FAIR", 18),
]

# The remaining Space -> ItemType combinations (Kitchen/Entire House/
# Assorted) that would otherwise still have zero bundle-eligible ACTIVE
# inventory even after the Living Room list above.
OTHER_SPECS = [
    ("Compact Monitor", "jamie", "Monitor", 40, "GOOD", 16),
    ("Curved Ultrawide Monitor", "sam", "Monitor", 150, "LIKE_NEW", 24),
    ("Bluetooth Speaker", "maya", "Speaker", 20, "GOOD", 14),
    ("Bookshelf Speaker Pair", "alex", "Speaker", 65, "LIKE_NEW", 22),
    ("3-Drawer Dresser", "sam", "Dresser", 35, "FAIR", 18),
    ("Tall Dresser", "jamie", "Dresser", 70, "GOOD", 26),
    ("Countertop Microwave", "alex", "Microwave", 22, "GOOD", 12),
    ("Compact Microwave", "maya", "Microwave", 38, "LIKE_NEW", 20),
]

# (type_name, category_name)
NEW_ITEM_TYPES = [
    ("Coffee Table", "Furniture"),
    ("Curtains", "Home Decor"),
    ("Shelf", "Home Decor"),
    ("Decor", "Home Decor"),
]

DEMO_SELLERS = [
    ("alex", "Alex"),
    ("jamie", "Jamie"),
    ("sam", "Sam"),
    ("maya", "Maya"),
]


class Command(BaseCommand):
    help = (
        "Adds extra bundle-eligible listings across every Move-In Bundle "
        "space, and flips demo sellers to campus-access-eligible for local "
        "testing. Local development only."
    )

    @transaction.atomic
    def handle(self, *args, **options):
        users = self._seed_users()
        item_types = self._seed_item_types()
        added = 0
        added += self._seed_listings(LIVING_ROOM_SPECS, users, item_types)
        added += self._seed_listings(OTHER_SPECS, users, item_types)
        verified = self._verify_demo_sellers(users)

        self.stdout.write(
            self.style.SUCCESS(
                f"Added {added} bundle-eligible listing(s). "
                f"{verified} demo seller(s) are campus-access-eligible "
                f"(password: {LOCAL_PASSWORD!r}, local development only)."
            )
        )

    def _seed_users(self):
        """get_or_create, matching seed_demo_data's own username/defaults -
        this command is safe to run before or after seed_demo_data."""
        users = {}
        for username, display_name in DEMO_SELLERS:
            user, created = User.objects.get_or_create(
                username=username,
                defaults={
                    "email": f"{username}@example.invalid",
                    "display_name": display_name,
                    "email_verified": False,
                },
            )
            if created:
                user.set_unusable_password()
                user.save()
            users[username] = user

        demo_seller, created = User.objects.get_or_create(
            username=DEMO_USERNAME,
            defaults={
                "email": "featured-demo@example.invalid",
                "display_name": "MoveOn Demo",
            },
        )
        if created:
            demo_seller.set_unusable_password()
            demo_seller.save()
        users[DEMO_USERNAME] = demo_seller
        return users

    def _seed_item_types(self):
        item_types = {}
        for type_name, category_name in NEW_ITEM_TYPES:
            category, _ = ItemCategory.objects.get_or_create(
                category_name=category_name
            )
            item_type, _ = ItemType.objects.get_or_create(
                category=category, item_type_name=type_name
            )
            item_types[type_name] = item_type

        # Reuse whatever taxonomy seed_demo_data already created for the
        # types this command adds inventory to but doesn't own.
        for type_name in (
            "Sofa",
            "Television",
            "Rug",
            "Lamp",
            "Monitor",
            "Speaker",
            "Dresser",
            "Microwave",
        ):
            if type_name in item_types:
                continue
            item_type = ItemType.objects.filter(item_type_name=type_name).first()
            if item_type is not None:
                item_types[type_name] = item_type
        return item_types

    def _seed_listings(self, specs, users, item_types):
        today = date.today()
        added = 0
        for title, username, type_name, price, condition, move_out_days in specs:
            item_type = item_types.get(type_name)
            if item_type is None:
                # seed_demo_data hasn't created this base type yet (e.g. run
                # standalone before it) - skip rather than fail; re-running
                # this command after seed_demo_data will pick it up.
                continue
            price = Decimal(price)
            _, created = Listing.objects.get_or_create(
                title=title,
                seller=users[username],
                defaults={
                    "item_type": item_type,
                    "description": f"{title} in {condition.replace('_', ' ').title()} condition.",
                    "condition": condition,
                    "listing_price": price,
                    "retail_price": (price * Decimal("1.5")).quantize(Decimal("0.01")),
                    "benchmark_price": (price * Decimal("1.1")).quantize(Decimal("0.01")),
                    "benchmark_low": (price * Decimal("0.85")).quantize(Decimal("0.01")),
                    "benchmark_high": (price * Decimal("1.25")).quantize(Decimal("0.01")),
                    "move_out_date": today + timedelta(days=move_out_days),
                    "minimum_price": (price * Decimal("0.7")).quantize(Decimal("0.01")),
                    "bundle_eligible": True,
                    "fulfillment_option": Listing.Fulfillment.PICKUP,
                    "status": Listing.Status.ACTIVE,
                },
            )
            added += int(created)
        return added

    def _verify_demo_sellers(self, users):
        """Local-dev-only: makes each demo seller campus-access-eligible
        (has_campus_access requires an @illinois.edu email, email_verified,
        and email_verified_at) with a known password, so a developer can
        actually log in as a bundle seller and accept/decline requests.

        Two separate .save() calls are required: User.save() resets
        email_verified/email_verified_at to False/None whenever `email`
        changes on an existing row (marketplace/models.py), so setting the
        new email and the verified flags in the same call would silently
        clobber the flags right back off."""
        verified = 0
        for username, user in users.items():
            local_email = f"{username}.demo@illinois.edu"
            if user.email != local_email:
                user.email = local_email
                user.save()
            user.email_verified = True
            user.email_verified_at = timezone.now()
            user.set_password(LOCAL_PASSWORD)
            user.save()
            verified += 1
        return verified
