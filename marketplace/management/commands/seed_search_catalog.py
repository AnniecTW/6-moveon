"""Add the A6 evaluation catalogue to a live database so AI search has stock.

The 40 listings in llm-test/listings.json are the ones the A9 evaluation and
the Gemini threshold calibration were measured on, so search quality on the
deployed site matches the reported numbers. Titles and descriptions are kept
exactly as evaluated; the listings belong to one inactive demo seller with no
usable password, so nobody can sign in as it.

Safe on a database with real data: listings are matched by their A6
``listing_id`` (never by primary key), re-running adds nothing, and existing
categories and item types are reused case-insensitively.

    python manage.py seed_search_catalog            # add the catalogue
    python manage.py seed_search_catalog --remove   # take it out again
"""

import json
import uuid
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import make_password
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import ProtectedError

from marketplace.management.commands.evaluate_ai import A6_ITEM_TYPES
from marketplace.models import ItemCategory, ItemType, Listing

User = get_user_model()

CATALOG_PATH = Path(settings.BASE_DIR) / "llm-test" / "listings.json"
DEMO_USERNAME = "moveon-catalog-demo"
DEMO_EMAIL = "catalog-demo@example.invalid"
DEMO_DISPLAY_NAME = "MoveOn demo seller"


def load_catalog(path=CATALOG_PATH):
    return json.loads(path.read_text(encoding="utf-8"))["results"]


class Command(BaseCommand):
    help = "Add (or --remove) the 40-listing A6 catalogue owned by an inactive demo seller."

    def add_arguments(self, parser):
        parser.add_argument("--remove", action="store_true",
                            help="Delete the catalogue listings and the demo seller.")

    @transaction.atomic
    def handle(self, *args, **options):
        rows = load_catalog()
        identifiers = [uuid.UUID(row["listing_id"]) for row in rows]
        if options["remove"]:
            self._remove(identifiers)
        else:
            self._add(rows)
        active = Listing.objects.filter(status=Listing.Status.ACTIVE).count()
        self.stdout.write(f"Active listings now: {active}.")

    def _seller(self):
        seller = User.objects.filter(username=DEMO_USERNAME).first()
        if seller is None:
            if User.objects.filter(email__iexact=DEMO_EMAIL).exists():
                raise CommandError("Another account already uses the demo email; nothing written.")
            return User.objects.create(
                username=DEMO_USERNAME, email=DEMO_EMAIL, display_name=DEMO_DISPLAY_NAME,
                password=make_password(None), is_active=False,
            )
        if (seller.email.lower() != DEMO_EMAIL or seller.is_active or seller.has_usable_password()
                or seller.is_staff or seller.is_superuser or seller.email_verified
                or seller.google_subject):
            raise CommandError(f"'{DEMO_USERNAME}' exists but is not the inactive demo seller; "
                               "nothing written.")
        return seller

    @staticmethod
    def _item_type(category_name, type_name):
        category = (ItemCategory.objects.filter(category_name__iexact=category_name).first()
                    or ItemCategory.objects.create(category_name=category_name))
        return (ItemType.objects.filter(category=category, item_type_name__iexact=type_name).first()
                or ItemType.objects.create(category=category, item_type_name=type_name))

    def _add(self, rows):
        seller = self._seller()
        added = 0
        for row in rows:
            identifier = uuid.UUID(row["listing_id"])
            existing = Listing.objects.filter(listing_id=identifier).first()
            if existing is not None:
                if existing.seller_id != seller.pk:
                    raise CommandError(f"Listing {identifier} belongs to another seller; "
                                       "nothing written.")
                continue
            Listing(
                listing_id=identifier, seller=seller,
                item_type=self._item_type(row["category"]["name"], A6_ITEM_TYPES[row["id"]]),
                title=row["title"], description=row["description"], condition=row["condition"],
                listing_price=Decimal(row["price"]), status=Listing.Status.ACTIVE,
                fulfillment_option=Listing.Fulfillment.PICKUP,
            ).save()
            added += 1
        self.stdout.write(self.style.SUCCESS(
            f"Added {added} catalogue listings ({len(rows) - added} already present), "
            f"sold by inactive '{DEMO_USERNAME}'."
        ))

    def _remove(self, identifiers):
        seller = User.objects.filter(username=DEMO_USERNAME, email__iexact=DEMO_EMAIL).first()
        if seller is None:
            self.stdout.write("No demo catalogue to remove.")
            return
        deleted = kept = 0
        for listing in Listing.objects.filter(seller=seller, listing_id__in=identifiers):
            try:
                with transaction.atomic():
                    listing.delete()
                deleted += 1
            except ProtectedError:
                # A sale or bundle request points at it: hide it instead.
                Listing.objects.filter(pk=listing.pk).update(status=Listing.Status.INACTIVE)
                kept += 1
        if not seller.listings.exists():
            try:
                with transaction.atomic():
                    seller.delete()
            except ProtectedError:
                pass
        message = f"Removed {deleted} catalogue listings."
        if kept:
            message += f" {kept} referenced by sales or bundles were set to inactive instead."
        self.stdout.write(self.style.SUCCESS(message))
