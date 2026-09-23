from django.conf import settings
from django.db import models
from django.core.exceptions import ValidationError
import uuid

from marketplace.models import ItemType, Listing
from marketplace.validation import ValidatedSaveModel, database_for


class Bundle(models.Model):
    """
    Represents one Move-In Bundle a buyer is assembling for a single
    space (e.g. Living Room). Holds the buyer's requested item types
    (via BundleCategory) and the actual selected listings (via
    BundleItem) as the buyer builds/edits it.
    """

    class Space(models.TextChoices):
        BEDROOM = "BEDROOM", "Bedroom"
        KITCHEN = "KITCHEN", "Kitchen"
        LIVING_ROOM = "LIVING_ROOM", "Living Room"
        BATHROOM = "BATHROOM", "Bathroom"
        ENTIRE_HOUSE = "ENTIRE_HOUSE", "Entire House"
        ASSORTED = "ASSORTED", "Assorted"

    class Tier(models.TextChoices):
        BUDGET = "BUDGET", "Budget"
        BEST_VALUE = "BEST_VALUE", "Best Value"
        PREMIUM = "PREMIUM", "Premium"

    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        REQUESTS_SENT = "REQUESTS_SENT", "Requests Sent"
        PARTIALLY_ACCEPTED = "PARTIALLY_ACCEPTED", "Partially Accepted"
        CONFIRMED = "CONFIRMED", "Confirmed"
        CANCELLED = "CANCELLED", "Cancelled"

    bundle_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    buyer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="bundles"
    )
    space = models.CharField(max_length=20, choices=Space.choices)
    selected_tier = models.CharField(
        max_length=20, choices=Tier.choices, null=True, blank=True
    )
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.DRAFT
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self):
        return f"{self.buyer}: {self.get_space_display()} bundle"


class BundleCategory(models.Model):
    """
    Represents one item type the buyer wants included in a bundle
    (e.g. "Sofa"), captured before actual listings are chosen. Lets
    the buyer's requirements persist independently of which specific
    listings eventually fill them.
    """

    bundle = models.ForeignKey(
        Bundle, on_delete=models.CASCADE, related_name="requested_categories"
    )
    item_type = models.ForeignKey(
        ItemType, on_delete=models.PROTECT, related_name="bundle_categories"
    )
    bundle_item = models.ForeignKey(
        "BundleItem",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="category_requirements",
    )

    class Meta:
        verbose_name_plural = "Bundle categories"
        ordering = ["bundle", "item_type"]
        constraints = [
            models.UniqueConstraint(
                fields=["bundle", "item_type"], name="unique_item_type_per_bundle"
            )
        ]

    def __str__(self):
        return f"{self.bundle}: wants {self.item_type.item_type_name}"

    def clean(self):
        super().clean()
        if self.bundle_item_id:
            if self.bundle_item.bundle_id != self.bundle_id:
                raise ValidationError(
                    {"bundle_item": "The bundle item must belong to this bundle."}
                )
            if self.bundle_item.listing.item_type_id != self.item_type_id:
                raise ValidationError(
                    {"bundle_item": "The bundle item must match this requested item type."}
                )


class BundleItem(ValidatedSaveModel):
    """
    Represents one actual Listing selected into a bundle, fulfilling
    one of its requested BundleCategory item types. This is the
    working/final customized bundle contents.
    """

    class ItemStatus(models.TextChoices):
        SELECTED = "SELECTED", "Selected"
        REQUESTED = "REQUESTED", "Requested"
        ACCEPTED = "ACCEPTED", "Accepted"
        DECLINED = "DECLINED", "Declined"
        REPLACED = "REPLACED", "Replaced"

    bundle = models.ForeignKey(
        Bundle, on_delete=models.CASCADE, related_name="bundle_items"
    )
    listing = models.ForeignKey(
        Listing, on_delete=models.PROTECT, related_name="bundle_items"
    )
    listing_price_snapshot = models.DecimalField(max_digits=8, decimal_places=2)
    proposed_bundle_price = models.DecimalField(
        max_digits=8, decimal_places=2, null=True, blank=True
    )
    final_price = models.DecimalField(
        max_digits=8, decimal_places=2, null=True, blank=True
    )
    item_status = models.CharField(
        max_length=20, choices=ItemStatus.choices, default=ItemStatus.SELECTED
    )
    responded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["bundle", "listing"]
        constraints = [
            models.UniqueConstraint(
                fields=["bundle", "listing"], name="unique_listing_per_bundle"
            )
        ]

    def clean(self):
        super().clean()
        if not self._state.adding and self.pk:
            database = database_for(self)
            previous_listing = (
                type(self)
                .objects.using(database)
                .filter(pk=self.pk)
                .values_list("listing_id", flat=True)
                .first()
            )
            if (
                previous_listing != self.listing_id
                and self.conversations.using(database).exists()
            ):
                raise ValidationError(
                    {
                        "listing": "The listing cannot change while this bundle item is referenced by a conversation."
                    }
                )

    def __str__(self):
        return f"{self.bundle}: {self.listing.title}"
