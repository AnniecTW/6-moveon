"""Create the six reference items without overwriting edited listings."""

from decimal import Decimal
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from marketplace.featured import DEMO_USERNAME, SCENES
from marketplace.models import ItemCategory, ItemType, Listing


class Command(BaseCommand):
    help = "Adds six reference-photo demo listings used by the featured bundle scenes."

    @transaction.atomic
    def handle(self, *args, **options):
        seller, created = get_user_model().objects.get_or_create(
            username=DEMO_USERNAME,
            defaults={
                "email": "featured-demo@example.invalid",
                "display_name": "MoveOn Demo",
            },
        )
        if created:
            seller.set_unusable_password()
            seller.save()
        added = 0
        for scene in SCENES:
            for spec in scene["items"]:
                category, _ = ItemCategory.objects.get_or_create(
                    category_name="Home Decor"
                    if spec["type"] in ("Lamp", "Pillow")
                    else "Furniture"
                )
                item_type, _ = ItemType.objects.get_or_create(
                    category=category, item_type_name=spec["type"]
                )
                _, created = Listing.objects.get_or_create(
                    seller=seller,
                    title=spec["title"],
                    defaults={
                        "item_type": item_type,
                        "description": "Reference demo item from the "
                        + scene["title"]
                        + ".",
                        "listing_price": Decimal(spec["price"]),
                        "retail_price": Decimal(spec["original"]),
                        "condition": Listing.Condition.GOOD,
                        "status": Listing.Status.ACTIVE,
                        "bundle_eligible": True,
                        "fulfillment_option": (
                            Listing.Fulfillment.BOTH
                            if spec["title"] == "Rocking Chair"
                            else Listing.Fulfillment.DELIVERY
                            if spec["title"] == "Coffee Table"
                            else Listing.Fulfillment.PICKUP
                        ),
                    },
                )
                added += int(created)
        self.stdout.write(
            self.style.SUCCESS(
                f"Added {added} featured demo listings. Existing listings were preserved."
            )
        )
