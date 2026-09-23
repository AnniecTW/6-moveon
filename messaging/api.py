"""Authenticated, participant-scoped Messaging page and JSON endpoints."""

import json
import uuid
from functools import wraps

from django.core.exceptions import ValidationError
from django.db import IntegrityError, OperationalError, transaction
from django.db.models import Q
from django.http import FileResponse, JsonResponse
from django.http import Http404
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods, require_POST
from PIL import Image, UnidentifiedImageError

from bundles.models import Bundle, BundleItem
from marketplace.auth_backend import has_campus_access
from marketplace.models import Listing, Transaction
from .models import Conversation, Message, MessageImage

PAGE_SIZE = 30
MAX_IMAGE_BYTES = 10 * 1024 * 1024
IMAGE_FORMATS = {"JPEG": ("image/jpeg", ".jpg"), "PNG": ("image/png", ".png"),
                 "WEBP": ("image/webp", ".webp"), "GIF": ("image/gif", ".gif")}


def error(message, status=400, code="invalid_request"):
    return JsonResponse({"error": message, "code": code}, status=status)


def api_guard(view):
    @wraps(view)
    def guarded(request, *args, **kwargs):
        try:
            response = view(request, *args, **kwargs)
            if response.status_code == 405:
                return error("Method not allowed.", 405, "method_not_allowed")
            return response
        except (Http404, ValueError, ValidationError):
            return error("Resource not found.", 404, "not_found")
        except OperationalError:
            return error("Messaging is busy. Please retry.", 503, "temporarily_unavailable")
    return guarded


def data(request):
    try:
        value = json.loads(request.body)
    except (ValueError, UnicodeDecodeError):
        return None
    return value if isinstance(value, dict) else None


def participant(request, conversation_id):
    return get_object_or_404(
        Conversation.objects.select_related("listing", "buyer", "seller").filter(
            Q(buyer=request.user) | Q(seller=request.user)), pk=conversation_id,
    )


def image_url(image):
    return reverse("messaging_attachment", args=[image.pk])


def message_data(message, user):
    return {
        "id": str(message.pk), "mine": message.sender_id == user.pk,
        "text": message.body_text,
        "clientRequestId": str(message.client_request_id) if message.client_request_id else None,
        "images": [image_url(image) for image in message.images.all()],
        "timestamp": message.sent_at.isoformat(), "status": "sent",
    }


def request_data(item):
    return {
        "requestId": str(item.pk), "bundleId": str(item.bundle_id),
        "bundleLabel": item.bundle.get_space_display() + " bundle",
        "itemCount": item.bundle.bundle_items.count(),
        "requestedPrice": float(item.proposed_bundle_price if item.proposed_bundle_price is not None else item.listing_price_snapshot),
        "status": {
            BundleItem.ItemStatus.REQUESTED: "awaiting",
            BundleItem.ItemStatus.ACCEPTED: "accepted",
            BundleItem.ItemStatus.DECLINED: "declined",
        }[item.item_status],
    }


def conversation_data(conversation, user):
    listing = conversation.listing
    contact = conversation.seller if conversation.buyer_id == user.pk else conversation.buyer
    last = conversation.messages.order_by("-pk").prefetch_related("images").first()
    requests = BundleItem.objects.filter(
        bundle__buyer_id=conversation.buyer_id, listing_id=conversation.listing_id,
        item_status__in=[BundleItem.ItemStatus.REQUESTED, BundleItem.ItemStatus.ACCEPTED,
                         BundleItem.ItemStatus.DECLINED],
    ).select_related("bundle") if conversation.listing_id else BundleItem.objects.none()
    return {
        "id": str(conversation.pk),
        "role": "buyer" if conversation.buyer_id == user.pk else "seller",
        "listing": {
            "id": str(listing.pk) if listing else None,
            "title": listing.title if listing else conversation.listing_title_snapshot or "Deleted listing",
            "listedPrice": float(listing.listing_price) if listing else (
                float(conversation.listing_price_snapshot) if conversation.listing_price_snapshot is not None else None),
            "imageUrl": listing.image_url if listing else conversation.listing_image_snapshot or None,
            "available": bool(listing and listing.status == Listing.Status.ACTIVE),
            "unavailableReason": "Unavailable" if not listing or listing.status != Listing.Status.ACTIVE else "",
        },
        "contact": {"id": str(contact.pk), "displayName": contact.display_name or contact.username,
                    "avatarUrl": None},
        "unreadCount": conversation.messages.filter(is_read=False).exclude(sender=user).count(),
        "lastActivity": (conversation.last_message_at or conversation.created_at).isoformat(),
        "bundleRequests": [request_data(item) for item in requests],
        "messages": [message_data(last, user)] if last else [],
    }


@require_GET
def page(request):
    return render(request, "messaging/page.html", {
        "campus_access": has_campus_access(request.user),
        "messaging_config": {
            "conversations": reverse("messaging_conversations"),
            "create": reverse("messaging_create"),
            "messages": reverse("messaging_messages", args=["__id__"]),
            "read": reverse("messaging_read", args=["__id__"]),
            "decision": reverse("messaging_request_decision", args=["__id__"]),
            "upload": reverse("messaging_upload"),
            "attachment": reverse("messaging_attachment", args=["__id__"]),
            "account": reverse("account"), "home": reverse("home"),
        },
    })


@require_GET
def conversations(request):
    qs = Conversation.objects.filter(Q(buyer=request.user) | Q(seller=request.user)).select_related(
        "buyer", "seller", "listing"
    )
    role = request.GET.get("role")
    if role == "buying":
        qs = qs.filter(buyer=request.user)
    elif role == "selling":
        qs = qs.filter(seller=request.user)
    elif role not in (None, "", "all"):
        return error("Invalid filter.")
    term = request.GET.get("q", "").strip()[:200]
    if term:
        qs = qs.filter(
            Q(listing__title__icontains=term) | Q(listing_title_snapshot__icontains=term) |
            Q(buyer=request.user, seller__display_name__icontains=term) |
            Q(seller=request.user, buyer__display_name__icontains=term)
        )
    qs = qs.order_by("-last_message_at", "-created_at", "-pk")
    return JsonResponse({"conversations": [conversation_data(c, request.user) for c in qs]})


@require_GET
def unread(request):
    count = Message.objects.filter(
        Q(conversation__buyer=request.user) | Q(conversation__seller=request.user),
        is_read=False,
    ).exclude(sender=request.user).count()
    response = JsonResponse({"unreadCount": count})
    response["Cache-Control"] = "private, no-store"
    return response


@require_POST
def create(request):
    payload = data(request)
    if payload is None:
        return error("Invalid JSON.")
    try:
        listing_id = int(payload.get("listingId"))
    except (ValueError, TypeError):
        return error("Invalid listing.")
    listing = get_object_or_404(Listing.objects.select_related("seller"), pk=listing_id)
    if listing.seller_id == request.user.pk:
        return error("You cannot message yourself.")
    with transaction.atomic():
        conversation = Conversation.objects.filter(buyer=request.user, seller=listing.seller, listing=listing).first()
        if conversation is None:
            if listing.status != Listing.Status.ACTIVE:
                return error("This listing is unavailable.", 409, "listing_unavailable")
            try:
                conversation = Conversation.objects.create(buyer=request.user, seller=listing.seller, listing=listing)
            except IntegrityError:
                conversation = Conversation.objects.get(buyer=request.user, seller=listing.seller, listing=listing)
    return JsonResponse(conversation_data(conversation, request.user))


@require_http_methods(["GET", "POST"])
def messages(request, conversation_id):
    conversation = participant(request, conversation_id)
    if request.method == "GET":
        qs = conversation.messages.select_related("sender").prefetch_related("images")
        for parameter, lookup in (("before", "pk__lt"), ("after", "pk__gt")):
            raw = request.GET.get(parameter)
            if raw:
                try:
                    boundary = int(raw)
                except ValueError:
                    return error("Invalid message cursor.")
                qs = qs.filter(**{lookup: boundary})
        after = bool(request.GET.get("after"))
        rows = list(qs.order_by("pk" if after else "-pk")[:PAGE_SIZE + 1])
        has_more = len(rows) > PAGE_SIZE
        batch = rows[:PAGE_SIZE] if after else list(reversed(rows[:PAGE_SIZE]))
        return JsonResponse({"messages": [message_data(m, request.user) for m in batch],
                             "hasMore": has_more,
                             "nextBefore": str(batch[0].pk) if has_more and batch and not after else None,
                             "nextAfter": str(batch[-1].pk) if has_more and batch and after else None})
    payload = data(request)
    if payload is None:
        return error("Invalid JSON.")
    text = payload.get("text", "")
    ids = payload.get("imageIds", [])
    if not isinstance(text, str) or len(text) > 10000 or not isinstance(ids, list) or len(ids) > 3 or len(ids) != len(set(map(str, ids))):
        return error("Invalid message or attachment count.")
    try:
        ids = [str(uuid.UUID(value)) for value in ids]
    except (TypeError, ValueError, AttributeError):
        return error("Invalid attachment ID.")
    text = text.strip()
    if not text and not ids:
        return error("Enter a message or attach an image.")
    try:
        key = uuid.UUID(payload["clientRequestId"])
    except (KeyError, TypeError, ValueError, AttributeError):
        return error("A client request ID is required.")
    with transaction.atomic():
        existing = Message.objects.filter(conversation=conversation, sender=request.user, client_request_id=key).prefetch_related("images").first()
        if existing:
            return JsonResponse(message_data(existing, request.user))
        images = list(MessageImage.objects.select_for_update().filter(pk__in=ids,
            conversation=conversation, uploader=request.user, message__isnull=True))
        if len(images) != len(ids):
            return error("An attachment is unavailable or belongs to another conversation.", 409, "invalid_attachment")
        message = Message.objects.create(conversation=conversation, sender=request.user,
                                         body_text=text, client_request_id=key)
        MessageImage.objects.filter(pk__in=[image.pk for image in images]).update(message=message)
        conversation.last_message_at = message.sent_at
        conversation.save(update_fields=["last_message_at"])
        message = Message.objects.prefetch_related("images").get(pk=message.pk)
    return JsonResponse(message_data(message, request.user), status=201)


@require_POST
def mark_read(request, conversation_id):
    conversation = participant(request, conversation_id)
    payload = data(request)
    ids = payload.get("messageIds") if payload else None
    if not isinstance(ids, list) or len(ids) > 100 or any(not str(i).isdigit() for i in ids):
        return error("Supply displayed message IDs.")
    count = conversation.messages.filter(pk__in=ids, is_read=False).exclude(sender=request.user).update(is_read=True)
    return JsonResponse({"readCount": count,
                         "unreadCount": conversation.messages.filter(is_read=False).exclude(sender=request.user).count()})


@require_POST
def upload(request):
    conversation = participant(request, request.POST.get("conversationId"))
    file = request.FILES.get("file")
    if not file or file.size > MAX_IMAGE_BYTES or file.size == 0:
        return error("Choose an image of 10MB or less.")
    try:
        file.seek(0)
        with Image.open(file) as image:
            if image.width * image.height > 20_000_000:
                return error("Image dimensions are too large.")
            image.verify()
            format_name = image.format
        if format_name not in IMAGE_FORMATS:
            return error("Use JPEG, PNG, WebP, or GIF.")
        file.seek(0)
        with Image.open(file) as image:
            image.load()
        file.seek(0)
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        return error("The file is not a valid image.")
    content_type, suffix = IMAGE_FORMATS[format_name]
    file.name = f"{uuid.uuid4().hex}{suffix}"
    image = MessageImage.objects.create(conversation=conversation, uploader=request.user,
                                        file=file, content_type=content_type)
    return JsonResponse({"id": str(image.pk), "url": image_url(image)}, status=201)


@require_http_methods(["GET", "DELETE"])
def attachment(request, image_id):
    image = get_object_or_404(MessageImage, pk=image_id,
        conversation__in=Conversation.objects.filter(Q(buyer=request.user) | Q(seller=request.user)))
    if image.message_id is None and image.uploader_id != request.user.pk:
        return error("Resource not found.", 404, "not_found")
    if request.method == "DELETE":
        if image.uploader_id != request.user.pk or image.message_id is not None:
            return error("This image cannot be removed.", 403, "forbidden")
        image.delete()
        return JsonResponse({"removed": True})
    response = FileResponse(image.file.open("rb"), content_type=image.content_type)
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    return response


@require_POST
def request_decision(request, request_id):
    payload = data(request)
    decision = payload.get("decision") if payload else None
    if decision not in ("accepted", "declined"):
        return error("Choose accept or decline.")
    with transaction.atomic():
        item = get_object_or_404(BundleItem.objects.select_for_update().select_related("bundle", "listing"),
                                 pk=request_id, listing__seller=request.user)
        if not Conversation.objects.filter(buyer=item.bundle.buyer, seller=request.user,
                                           listing=item.listing).exists():
            return error("Request conversation not found.", 404, "not_found")
        target = BundleItem.ItemStatus.ACCEPTED if decision == "accepted" else BundleItem.ItemStatus.DECLINED
        if item.item_status == target:
            return JsonResponse(request_data(item))
        if item.item_status != BundleItem.ItemStatus.REQUESTED:
            return error("This request has already been handled.", 409, "stale_request")
        listing = Listing.objects.select_for_update().get(pk=item.listing_id)
        if decision == "accepted":
            if listing.status != Listing.Status.ACTIVE or Transaction.objects.filter(
                listing=listing, status__in=[Transaction.Status.PENDING_PICKUP, Transaction.Status.COMPLETED]
            ).exists():
                return error("This listing is unavailable.", 409, "listing_unavailable")
            price = item.proposed_bundle_price if item.proposed_bundle_price is not None else item.listing_price_snapshot
            Transaction.objects.create(listing=listing, buyer=item.bundle.buyer, seller=request.user,
                bundle=item.bundle, bundle_item=item, agreed_price=price,
                benchmark_price_snapshot=listing.benchmark_price)
            item.final_price = price
            listing.status = Listing.Status.RESERVED
            listing.save(update_fields=["status", "updated_at"])
        item.item_status = target
        item.responded_at = timezone.now()
        item.save(update_fields=["item_status", "responded_at", "final_price"])
        bundle = item.bundle
        states = list(bundle.bundle_items.values_list("item_status", flat=True))
        if states and all(s == BundleItem.ItemStatus.ACCEPTED for s in states):
            bundle.status = Bundle.Status.CONFIRMED
        elif BundleItem.ItemStatus.ACCEPTED in states:
            bundle.status = Bundle.Status.PARTIALLY_ACCEPTED
        else:
            bundle.status = Bundle.Status.REQUESTS_SENT
        bundle.save(update_fields=["status", "updated_at"])
    return JsonResponse(request_data(item))
