import uuid

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.db.models.signals import post_delete
from django.core.exceptions import ValidationError
from django.dispatch import receiver
from django.urls import reverse

from .validation import ValidatedSaveModel, database_for, participant_errors


class User(AbstractUser):
    """
    Represents one unified student account on MoveOn.

    There are no separate Buyer/Seller accounts — a single account can
    create listings, buy listings, build bundles, and message other
    users. Buyer/seller are contextual roles, not separate models.

    Extends Django's AbstractUser to keep all standard authentication
    behavior (password hashing, permissions, is_active/is_staff/etc.)
    while adding the university-specific fields the marketplace needs.
    """

    class AccountStatus(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        SUSPENDED = "SUSPENDED", "Suspended"

    email = models.EmailField(unique=True)
    email_verified = models.BooleanField(default=False)
    email_verified_at = models.DateTimeField(null=True, blank=True)
    google_subject = models.CharField(max_length=255, unique=True, null=True, blank=True)
    display_name = models.CharField(max_length=150)
    account_status = models.CharField(
        max_length=20,
        choices=AccountStatus.choices,
        default=AccountStatus.ACTIVE,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["display_name"]

    def __str__(self):
        return self.display_name or self.username

    def save(self, *args, **kwargs):
        update_fields = kwargs.get("update_fields")
        if self.pk and (update_fields is None or "email" in update_fields):
            previous = type(self).objects.filter(pk=self.pk).values_list("email", flat=True).first()
            if previous is not None and previous.lower() != self.email.lower():
                self.email_verified = False
                self.email_verified_at = None
                if update_fields is not None:
                    kwargs["update_fields"] = set(update_fields) | {"email_verified", "email_verified_at"}
                EmailVerification.objects.filter(user_id=self.pk).delete()
        return super().save(*args, **kwargs)


class EmailVerification(models.Model):
    """One outstanding campus email challenge per account."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="email_challenge"
    )
    request_id = models.UUIDField()
    code_digest = models.CharField(max_length=64)
    expires_at = models.DateTimeField()
    sent_at = models.DateTimeField()
    attempts = models.PositiveSmallIntegerField(default=0)


class ItemCategory(models.Model):
    """
    Represents a broad marketplace category, such as Furniture or
    Electronics. Exists to group related ItemTypes (e.g. Sofa, Desk)
    under a shared, browsable taxonomy.
    """

    category_name = models.CharField(max_length=100, unique=True)

    class Meta:
        ordering = ["category_name"]

    def __str__(self):
        return self.category_name


class ItemType(models.Model):
    """
    Represents a specific kind of item within a broader ItemCategory,
    e.g. "Sofa" or "Desk" under "Furniture". Listings and bundle
    requests reference this specific level, not the broad category.
    """

    category = models.ForeignKey(
        ItemCategory, on_delete=models.PROTECT, related_name="item_types"
    )
    item_type_name = models.CharField(max_length=100)

    class Meta:
        ordering = ["category", "item_type_name"]
        constraints = [
            models.UniqueConstraint(
                fields=["category", "item_type_name"],
                name="unique_item_type_per_category",
            )
        ]

    def __str__(self):
        return f"{self.category.category_name} / {self.item_type_name}"


class Listing(ValidatedSaveModel):
    """
    Represents one item a student has posted for sale. Central object
    of the marketplace: sellers create these, buyers browse/purchase
    them, and bundles/price recommendations reference them.
    """

    class Condition(models.TextChoices):
        NEW = "NEW", "New"
        LIKE_NEW = "LIKE_NEW", "Like New"
        GOOD = "GOOD", "Good"
        FAIR = "FAIR", "Fair"
        POOR = "POOR", "Poor"

    class Fulfillment(models.TextChoices):
        PICKUP = "PICKUP", "Pickup"
        DELIVERY = "DELIVERY", "Delivery"
        BOTH = "BOTH", "Pickup / Delivery"

    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        ACTIVE = "ACTIVE", "Active"
        RESERVED = "RESERVED", "Reserved"
        SOLD = "SOLD", "Sold"
        INACTIVE = "INACTIVE", "Inactive"

    class PricingPlan(models.TextChoices):
        BALANCED = "BALANCED", "Balanced"
        MAXIMIZE_VALUE = "MAXIMIZE_VALUE", "Maximize Value"
        SELL_BEFORE_MOVE = "SELL_BEFORE_MOVE", "Sell Before I Move"

    listing_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    MAX_IMAGES = 8


    seller = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="listings"
    )
    item_type = models.ForeignKey(
        ItemType, on_delete=models.PROTECT, related_name="listings"
    )
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    image_url = models.URLField(blank=True)
    condition = models.CharField(max_length=20, choices=Condition.choices)
    listing_price = models.DecimalField(max_digits=8, decimal_places=2)
    retail_price = models.DecimalField(
        max_digits=8, decimal_places=2, null=True, blank=True
    )
    benchmark_price = models.DecimalField(
        max_digits=8, decimal_places=2, null=True, blank=True
    )
    benchmark_low = models.DecimalField(
        max_digits=8, decimal_places=2, null=True, blank=True
    )
    benchmark_high = models.DecimalField(
        max_digits=8, decimal_places=2, null=True, blank=True
    )
    move_out_date = models.DateField(null=True, blank=True)
    minimum_price = models.DecimalField(
        max_digits=8, decimal_places=2, null=True, blank=True
    )
    bundle_eligible = models.BooleanField(default=False)
    sell_no_matter_what = models.BooleanField(default=False)
    fulfillment_option = models.CharField(max_length=20, choices=Fulfillment.choices)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.DRAFT
    )
    pricing_plan = models.CharField(max_length=20, choices=PricingPlan.choices, blank=True, default="")
    views = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def clean(self):
        super().clean()
        if not self._state.adding and self.pk:
            database = database_for(self)
            previous_owner = (
                type(self)
                .objects.using(database)
                .filter(pk=self.pk)
                .values_list("seller_id", flat=True)
                .first()
            )
            if previous_owner != self.seller_id and (
                self.transactions.using(database).exists()
                or self.conversations.using(database).exists()
                or self.bundle_items.using(database)
                .filter(conversations__isnull=False)
                .exists()
            ):
                raise ValidationError(
                    {
                        "seller": "The owner cannot change after a transaction or conversation references this listing."
                    }
                )

    @property
    def cover_image_url(self):
        prefetched_images = getattr(self, "_prefetched_objects_cache", {}).get("images")
        if prefetched_images is None:
            image = self.images.order_by("position", "id").first()
        else:
            image = prefetched_images[0] if prefetched_images else None
        return image.url if image else self.image_url or ""

    def get_absolute_url(self):
        return reverse("listing-detail-url", kwargs={"primary_key": self.pk})

    def __str__(self):
        return self.title


class ListingImage(ValidatedSaveModel):
    """A user-uploaded or externally hosted image attached to a listing."""

    listing = models.ForeignKey(
        Listing,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="images",
    )
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="listing_images",
    )
    image = models.ImageField(upload_to="listing_images/%Y/%m/", blank=True)
    external_url = models.URLField(blank=True)
    position = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["position", "id"]

    def clean(self):
        super().clean()
        has_image = bool(self.image)
        has_external_url = bool((self.external_url or "").strip())
        if has_image == has_external_url:
            raise ValidationError(
                "Provide exactly one of an uploaded image or an external image URL."
            )

    @property
    def url(self):
        return self.image.url if self.image else self.external_url

    def __str__(self):
        return f"Image {self.pk} for {self.listing or 'unattached listing'}"


@receiver(post_delete, sender=ListingImage)
def delete_listing_image_file(sender, instance, **kwargs):
    if instance.image:
        instance.image.storage.delete(instance.image.name)


class WatchlistItem(models.Model):
    """A listing saved to a user's persistent marketplace watchlist."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="watchlist_items",
    )
    listing = models.ForeignKey(
        Listing,
        on_delete=models.CASCADE,
        related_name="watchlist_entries",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "listing"],
                name="unique_listing_per_user_watchlist",
            )
        ]

    def __str__(self):
        return f"{self.user}: {self.listing.title}"


class PriceRecommendation(models.Model):
    """
    Represents one AI-generated price-change suggestion for a listing,
    typically as its move-out date approaches. Kept separate from the
    listing's static benchmark fields so a history of suggestions can
    exist without overwriting the listing itself.
    """

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        ACCEPTED = "ACCEPTED", "Accepted"
        DECLINED = "DECLINED", "Declined"
        MODIFIED = "MODIFIED", "Modified"
        EXPIRED = "EXPIRED", "Expired"

    listing = models.ForeignKey(
        Listing, on_delete=models.CASCADE, related_name="price_recommendations"
    )
    previous_price = models.DecimalField(max_digits=8, decimal_places=2)
    recommended_price = models.DecimalField(max_digits=8, decimal_places=2)
    applied_price = models.DecimalField(
        max_digits=8, decimal_places=2, null=True, blank=True
    )
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING
    )
    generated_at = models.DateTimeField(auto_now_add=True)
    responded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-generated_at"]

    def __str__(self):
        return (
            f"{self.listing.title}: {self.previous_price} -> {self.recommended_price}"
        )


class Transaction(ValidatedSaveModel):
    """
    Records one purchase/reservation lifecycle for a listing: who
    bought it, from whom, at what price, and its pickup/completion
    status. Payment processing itself is out of scope — this only
    tracks the marketplace-side agreement and state.
    """

    class Status(models.TextChoices):
        PENDING_PICKUP = "PENDING_PICKUP", "Pending Pickup"
        COMPLETED = "COMPLETED", "Completed"
        CANCELLED = "CANCELLED", "Cancelled"

    transaction_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    conversation = models.ForeignKey("messaging.Conversation", on_delete=models.SET_NULL, null=True, blank=True, related_name="transactions")
    listing = models.ForeignKey(
        Listing, on_delete=models.PROTECT, related_name="transactions"
    )
    buyer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="purchases"
    )
    seller = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="sales"
    )
    bundle = models.ForeignKey(
        "bundles.Bundle",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="transactions",
    )
    bundle_item = models.ForeignKey(
        "bundles.BundleItem",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="transactions",
    )
    agreed_price = models.DecimalField(max_digits=8, decimal_places=2)
    benchmark_price_snapshot = models.DecimalField(
        max_digits=8, decimal_places=2, null=True, blank=True
    )
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING_PICKUP
    )
    meetup_datetime = models.DateTimeField(null=True, blank=True)
    meetup_location = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(buyer=models.F("seller")),
                name="transaction_distinct_participants",
            )
        ]

    def clean(self):
        super().clean()
        owner_id = (
            Listing.objects.using(database_for(self))
            .filter(pk=self.listing_id)
            .values_list("seller_id", flat=True)
            .first()
            if self.listing_id
            else None
        )
        errors = participant_errors(self.buyer_id, self.seller_id, owner_id)
        if self.conversation_id:
            conversation = self.conversation
            if conversation.listing_id != self.listing_id:
                errors["conversation"] = "The conversation must reference this listing."
            elif conversation.buyer_id != self.buyer_id:
                errors["conversation"] = "The conversation must reference this buyer."
            elif conversation.seller_id != self.seller_id:
                errors["conversation"] = "The conversation must reference this seller."
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return f"Transaction #{self.pk}: {self.listing.title}"
