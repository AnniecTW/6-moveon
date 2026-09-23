"""Small, idempotent bridge from an assembled Bundle to Messaging."""

import uuid

from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.views.decorators.http import require_POST

from marketplace.models import Listing
from messaging.models import Conversation, Message
from .models import Bundle, BundleItem


@require_POST
def send_requests(request, bundle_id):
    with transaction.atomic():
        bundle = get_object_or_404(Bundle.objects.select_for_update(), pk=bundle_id, buyer=request.user)
        items = list(bundle.bundle_items.select_related("listing__seller").order_by("pk"))
        if len(items) < 3:
            return JsonResponse({"error": "Add at least three items before sending requests.",
                                 "code": "too_few_items"}, status=400)
        if bundle.status == Bundle.Status.DRAFT:
            if any(item.item_status != BundleItem.ItemStatus.SELECTED or
                   item.listing.status != Listing.Status.ACTIVE or
                   item.listing.seller_id == request.user.pk for item in items):
                return JsonResponse({"error": "A selected listing is unavailable.",
                                     "code": "listing_unavailable"}, status=409)
            for item in items:
                listing = item.listing
                conversation, _ = Conversation.objects.get_or_create(
                    buyer=request.user, seller=listing.seller, listing=listing,
                )
                if conversation.bundle_item_id is None:
                    conversation.bundle_item = item
                    conversation.save(update_fields=["bundle_item"])
                price = item.proposed_bundle_price if item.proposed_bundle_price is not None else item.listing_price_snapshot
                key = uuid.uuid5(uuid.NAMESPACE_URL, f"moveon-bundle-request-{item.pk}")
                message, _ = Message.objects.get_or_create(
                    conversation=conversation, sender=request.user, client_request_id=key,
                    defaults={"body_text": (
                        f"Hi! I'd like to buy your {listing.title} for ${price} "
                        f"as part of a {bundle.get_space_display()} bundle."
                    )},
                )
                if conversation.last_message_at is None or conversation.last_message_at < message.sent_at:
                    conversation.last_message_at = message.sent_at
                    conversation.save(update_fields=["last_message_at"])
                item.item_status = BundleItem.ItemStatus.REQUESTED
                item.save(update_fields=["item_status"])
            bundle.status = Bundle.Status.REQUESTS_SENT
            bundle.save(update_fields=["status", "updated_at"])
        conversation_ids = list(Conversation.objects.filter(
            buyer=request.user, listing_id__in=[item.listing_id for item in items]
        ).values_list("pk", flat=True))
    first_id = conversation_ids[0] if conversation_ids else None
    url = reverse("messages") + (f"?conversation={first_id}" if first_id else "")
    return JsonResponse({"messagesUrl": url, "conversationIds": conversation_ids,
                         "bundleStatus": bundle.status})
