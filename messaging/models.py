from django.conf import settings
from django.db import models
from django.core.exceptions import ValidationError
import uuid
from django.db.models.signals import post_delete
from django.dispatch import receiver

from bundles.models import BundleItem
from marketplace.models import Listing
from marketplace.validation import ValidatedSaveModel, database_for, participant_errors


class Conversation(ValidatedSaveModel):
    """
    Represents one buyer/seller message thread, contextualized by
    a Listing at creation, optionally with a matching BundleItem.
    Deleted listings leave their existing conversation history intact.
    MoveOn has a single
    unified inbox; buying/selling are filters over Conversation, not
    separate participant roles.
    """

    listing = models.ForeignKey(
        Listing,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="conversations",
    )
    bundle_item = models.ForeignKey(
        BundleItem,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="conversations",
    )
    buyer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="conversations_as_buyer",
    )
    seller = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="conversations_as_seller",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    last_message_at = models.DateTimeField(null=True, blank=True)
    listing_title_snapshot = models.CharField(max_length=200, blank=True)
    listing_price_snapshot = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    listing_image_snapshot = models.URLField(blank=True)

    class Meta:
        ordering = ["-last_message_at", "-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["buyer", "seller", "listing"],
                name="unique_conversation_per_listing",
            ),
            models.CheckConstraint(
                condition=~models.Q(buyer=models.F("seller")),
                name="conversation_distinct_participants",
            ),
        ]

    def clean(self):
        super().clean()
        database = database_for(self)
        owner_id = (
            Listing.objects.using(database)
            .filter(pk=self.listing_id)
            .values_list("seller_id", flat=True)
            .first()
            if self.listing_id
            else None
        )
        errors = participant_errors(self.buyer_id, self.seller_id, owner_id)
        if self.listing_id is None:
            previous = (
                None
                if self._state.adding
                else type(self)
                .objects.using(database)
                .filter(pk=self.pk)
                .values("listing_id", "bundle_item_id")
                .first()
            )
            if (
                previous is None
                or previous["listing_id"] is not None
                or previous["bundle_item_id"] != self.bundle_item_id
            ):
                errors["listing"] = (
                    "Select a listing to start a conversation. Existing listings cannot be cleared manually."
                )
        if self.bundle_item_id:
            item = (
                BundleItem.objects.using(database)
                .filter(pk=self.bundle_item_id)
                .values("listing_id", "listing__seller_id")
                .first()
            )
            if item:
                errors.update(
                    participant_errors(
                        self.buyer_id, self.seller_id, item["listing__seller_id"]
                    )
                )
                if (
                    self.listing_id is not None
                    and item["listing_id"] != self.listing_id
                ):
                    errors["bundle_item"] = (
                        "The bundle item must refer to the selected listing."
                    )
        if not self._state.adding and self.pk and self.buyer_id and self.seller_id:
            if (
                self.messages.using(database)
                .exclude(sender_id__in=[self.buyer_id, self.seller_id])
                .exists()
            ):
                errors["buyer"] = (
                    "Participants cannot be changed while existing messages belong to another sender."
                )
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return f"{self.buyer} <-> {self.seller}"

    def save(self, *args, **kwargs):
        if self._state.adding and self.listing_id:
            listing = self.listing
            self.listing_title_snapshot = listing.title
            self.listing_price_snapshot = listing.listing_price
            self.listing_image_snapshot = listing.image_url
        return super().save(*args, **kwargs)


class Message(ValidatedSaveModel):
    """
    Represents one chat message within a Conversation. Has no meaning
    outside its conversation, so it's deleted along with it.
    """

    conversation = models.ForeignKey(
        Conversation, on_delete=models.CASCADE, related_name="messages"
    )
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="sent_messages"
    )
    body_text = models.TextField(blank=True)
    is_read = models.BooleanField(default=False)
    sent_at = models.DateTimeField(auto_now_add=True)
    client_request_id = models.UUIDField(null=True, blank=True)

    class Meta:
        ordering = ["sent_at"]
        constraints = [
            models.UniqueConstraint(fields=["conversation", "sender", "client_request_id"], name="unique_message_client_request")
        ]

    def clean(self):
        super().clean()
        if self.conversation_id and self.sender_id:
            participants = (
                Conversation.objects.using(database_for(self))
                .filter(pk=self.conversation_id)
                .values("buyer_id", "seller_id")
                .first()
            )
            if participants and self.sender_id not in (
                participants["buyer_id"],
                participants["seller_id"],
            ):
                raise ValidationError(
                    {
                        "sender": "The sender must be a buyer or seller in this conversation."
                    }
                )

    def __str__(self):
        return f"{self.sender}: {self.body_text[:30]}"


class MessageImage(models.Model):
    """Private image uploaded for one conversation, then bound to one message."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name="images")
    uploader = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    message = models.ForeignKey(Message, null=True, blank=True, on_delete=models.CASCADE, related_name="images")
    file = models.FileField(upload_to="messaging/private/%Y/%m/%d/")
    content_type = models.CharField(max_length=30)
    created_at = models.DateTimeField(auto_now_add=True)


@receiver(post_delete, sender=MessageImage)
def delete_image_file(sender, instance, **kwargs):
    if instance.file:
        instance.file.delete(save=False)
