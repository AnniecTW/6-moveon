"""Authenticated, participant-scoped Messaging page and JSON endpoints."""

import json
import logging
import re
import uuid
from decimal import Decimal
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
from .models import Conversation, DealProposal, Message, MessageImage

PAGE_SIZE = 30
MAX_IMAGE_BYTES = 10 * 1024 * 1024
IMAGE_FORMATS = {"JPEG": ("image/jpeg", ".jpg"), "PNG": ("image/png", ".png"),
                 "WEBP": ("image/webp", ".webp"), "GIF": ("image/gif", ".gif")}
logger = logging.getLogger(__name__)
PRICE_PATTERN = re.compile(r"^(?:0|[1-9][0-9]{0,5})(?:\.[0-9]{1,2})?$")
ACTIVE_TRANSACTION_STATUSES = [Transaction.Status.PENDING_PICKUP, Transaction.Status.COMPLETED]


class DealConflict(Exception):
    def __init__(self, message, code):
        super().__init__(message)
        self.code = code


class IdempotentRetry(Exception):
    def __init__(self, proposal_id):
        self.proposal_id = proposal_id


def conflict_response(exc):
    return error(str(exc), 409, exc.code)


def proposal_data(proposal):
    return {
        "id": str(proposal.pk),
        "agreedPrice": f"{proposal.agreed_price:.2f}",
        "status": proposal.status,
        "createdAt": proposal.created_at.isoformat(),
        "updatedAt": proposal.updated_at.isoformat(),
        "replacesProposalId": str(proposal.replaces_id) if proposal.replaces_id else None,
        "transactionId": str(proposal.transaction_id) if proposal.transaction_id else None,
    }


def parse_offer_payload(request):
    payload = data(request)
    if payload is None or payload.get("sellerConfirmed") is not True:
        return None
    raw_price = payload.get("agreedPrice")
    if isinstance(raw_price, bool) or not isinstance(raw_price, (str, int)):
        return None
    raw_price = str(raw_price)
    if not PRICE_PATTERN.fullmatch(raw_price):
        return None
    price = Decimal(raw_price)
    if not Decimal("0.01") <= price <= Decimal("999999.99"):
        return None
    try:
        key = uuid.UUID(payload.get("clientRequestId"))
    except (ValueError, TypeError, AttributeError):
        return None
    return price, key


def pending_bundle_request(conversation):
    return BundleItem.objects.filter(
        bundle__buyer_id=conversation.buyer_id,
        listing_id=conversation.listing_id,
        item_status=BundleItem.ItemStatus.REQUESTED,
    ).exists()


def active_transaction_exists(listing_id):
    return Transaction.objects.filter(
        listing_id=listing_id, status__in=ACTIVE_TRANSACTION_STATUSES
    ).exists()


def touch_available_listing(listing_id):
    # A write before checking offer state serializes quote writes with both sale paths on SQLite.
    if not Listing.objects.filter(pk=listing_id, status=Listing.Status.ACTIVE).update(
        updated_at=timezone.now()
    ):
        raise DealConflict("This listing is unavailable.", "listing_unavailable")


def reserve_listing(listing_id):
    # Status alone changes; Listing.clean() only guards owner changes.
    if not Listing.objects.filter(pk=listing_id, status=Listing.Status.ACTIVE).update(
        status=Listing.Status.RESERVED, updated_at=timezone.now()
    ):
        raise DealConflict("This listing is unavailable.", "listing_unavailable")


def invalidate_other_offers(listing_id, *, except_proposal_id=None):
    offers = DealProposal.objects.filter(
        conversation__listing_id=listing_id, status=DealProposal.Status.AWAITING_BUYER
    )
    if except_proposal_id:
        offers = offers.exclude(pk=except_proposal_id)
    offers.update(status=DealProposal.Status.UNAVAILABLE, updated_at=timezone.now())


def offer_result(request, proposal_id, status=200):
    proposal = DealProposal.objects.get(pk=proposal_id)
    conversation = participant(request, proposal.conversation_id)
    current = conversation_data(conversation, request.user)
    return JsonResponse({
        "proposal": proposal_data(proposal),
        "dealProposals": current["dealProposals"],
        "trade": current["trade"],
        "listing": current["listing"],
    }, status=status)


def matching_request(conversation_id, key, price, replaces_id):
    existing = DealProposal.objects.filter(
        conversation_id=conversation_id, client_request_id=key
    ).first()
    if existing and (existing.agreed_price != price or existing.replaces_id != replaces_id):
        raise DealConflict("This request ID was used for another offer.", "idempotency_conflict")
    return existing


def visible_proposal(request, proposal_id):
    return get_object_or_404(
        DealProposal.objects.select_related("conversation", "conversation__listing", "transaction")
        .filter(Q(conversation__buyer=request.user) | Q(conversation__seller=request.user)),
        pk=proposal_id,
    )


def unavailable_offers_if_needed(listing_id):
    # Also covers a listing made unavailable outside either Messaging sale path.
    with transaction.atomic():
        listing = Listing.objects.filter(pk=listing_id).values_list("status", flat=True).first()
        if listing != Listing.Status.ACTIVE or active_transaction_exists(listing_id):
            invalidate_other_offers(listing_id)


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
        Conversation.objects.select_related("listing", "buyer", "seller")
        .prefetch_related("listing__images", "deal_proposals")
        .filter(Q(buyer=request.user) | Q(seller=request.user)),
        pk=conversation_id,
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


def trade_data(conversation, user, requests, proposals):
    """Derive both inbox and detail state from transactions and this buyer's requests."""
    listing = conversation.listing
    role = "buyer" if conversation.buyer_id == user.pk else "seller"
    result = {
        "currentProposalId": None,
        "transaction": None,
        "summaryState": "negotiating",
        "detailState": "negotiating",
        "allowedActions": {"bundleRequestIds": [], "bundleDeclineRequestIds": [], "deal": []},
    }
    awaiting = [item for item in requests if item.item_status == BundleItem.ItemStatus.REQUESTED]
    if role == "seller":
        result["allowedActions"]["bundleDeclineRequestIds"] = [str(item.pk) for item in awaiting]
    if listing is None:
        result.update(summaryState="unavailable", detailState="unavailable")
        return result

    request_ids = {item.pk for item in requests}
    transactions = list(Transaction.objects.filter(
        listing=listing,
        status__in=ACTIVE_TRANSACTION_STATUSES,
    ))
    own_pending = [deal for deal in transactions if
                   deal.status == Transaction.Status.PENDING_PICKUP and
                   deal.buyer_id == conversation.buyer_id and
                   deal.seller_id == conversation.seller_id and
                   (deal.conversation_id == conversation.pk or
                    (deal.conversation_id is None and deal.bundle_item_id in request_ids))]
    if len(own_pending) > 1:
        logger.error("Multiple pending transactions match conversation %s", conversation.pk)
        result.update(summaryState="unavailable", detailState="unavailable")
        return result
    if own_pending:
        deal = own_pending[0]
        result.update(
            summaryState="pending_pickup", detailState="pending_pickup",
            transaction={
                "id": str(deal.pk),
                "source": "bundle" if deal.bundle_item_id else "deal",
                "status": deal.status,
                "agreedPrice": f"{deal.agreed_price:.2f}",
            },
        )
        return result
    if listing.status != Listing.Status.ACTIVE or transactions:
        if any(deal.buyer_id == conversation.buyer_id and
               deal.seller_id == conversation.seller_id and
               deal.conversation_id is None and deal.bundle_item_id is None
               for deal in transactions):
            logger.warning("Unlinked transaction cannot be attributed to conversation %s", conversation.pk)
        result.update(summaryState="unavailable", detailState="unavailable")
        return result

    current = next((proposal for proposal in proposals
                    if proposal.status == DealProposal.Status.AWAITING_BUYER), None)
    if role == "seller":
        result["allowedActions"]["bundleRequestIds"] = [str(item.pk) for item in awaiting]
    if current:
        result["currentProposalId"] = str(current.pk)
        if role == "buyer":
            result.update(summaryState="action_needed", detailState="review_deal")
            result["allowedActions"]["deal"] = ["confirm", "decline"]
        else:
            result["allowedActions"]["deal"] = ["withdraw"]
            if awaiting:
                result.update(summaryState="action_needed", detailState="review_bundle_request")
            else:
                result.update(summaryState="waiting", detailState="awaiting_buyer")
                result["allowedActions"]["deal"].append("edit")
    elif awaiting:
        result.update(
            summaryState="action_needed" if role == "seller" else "waiting",
            detailState="review_bundle_request" if role == "seller" else "waiting_for_seller",
        )
    elif proposals and proposals[-1].status == DealProposal.Status.DECLINED:
        result.update(summaryState="declined", detailState="deal_declined")
    elif any(item.item_status == BundleItem.ItemStatus.DECLINED for item in requests):
        result.update(summaryState="declined", detailState="bundle_declined")
    if role == "seller" and not awaiting and not current:
        result["allowedActions"]["deal"] = ["create"]
    return result


def conversation_data(conversation, user):
    listing = conversation.listing
    contact = conversation.seller if conversation.buyer_id == user.pk else conversation.buyer
    last = conversation.messages.order_by("-pk").prefetch_related("images").first()
    requests = list(BundleItem.objects.filter(
        bundle__buyer_id=conversation.buyer_id, listing_id=conversation.listing_id,
        item_status__in=[BundleItem.ItemStatus.REQUESTED, BundleItem.ItemStatus.ACCEPTED,
                         BundleItem.ItemStatus.DECLINED],
    ).select_related("bundle")) if conversation.listing_id else []
    proposals = list(conversation.deal_proposals.all())
    trade = trade_data(conversation, user, requests, proposals)
    return {
        "id": str(conversation.pk),
        "role": "buyer" if conversation.buyer_id == user.pk else "seller",
        "listing": {
            "id": str(listing.pk) if listing else None,
            "status": listing.status if listing else None,
            "title": listing.title if listing else conversation.listing_title_snapshot or "Deleted listing",
            "listedPrice": float(listing.listing_price) if listing else (
                float(conversation.listing_price_snapshot) if conversation.listing_price_snapshot is not None else None),
            "imageUrl": listing.cover_image_url if listing else conversation.listing_image_snapshot or None,
            "available": bool(listing and listing.status == Listing.Status.ACTIVE),
            "unavailableReason": "Unavailable" if not listing or listing.status != Listing.Status.ACTIVE else "",
        },
        "contact": {"id": str(contact.pk), "displayName": contact.display_name or contact.username,
                    "avatarUrl": None},
        "unreadCount": conversation.messages.filter(is_read=False).exclude(sender=user).count(),
        "lastActivity": (conversation.last_message_at or conversation.created_at).isoformat(),
        "bundleRequests": [request_data(item) for item in requests],
        "dealProposals": [proposal_data(proposal) for proposal in proposals],
        "trade": trade,
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
            "dealCreate": reverse("messaging_deal_proposals", args=["__id__"]),
            "dealRevise": reverse("messaging_deal_proposal", args=["__id__"]),
            "dealWithdraw": reverse("messaging_deal_withdraw", args=["__id__"]),
            "dealDecision": reverse("messaging_deal_decision", args=["__id__"]),
            "upload": reverse("messaging_upload"),
            "attachment": reverse("messaging_attachment", args=["__id__"]),
            "account": reverse("account"), "home": reverse("home"),
        },
    })


@require_GET
def conversations(request):
    qs = (
        Conversation.objects.filter(Q(buyer=request.user) | Q(seller=request.user))
        .select_related("buyer", "seller", "listing")
        .prefetch_related("listing__images", "deal_proposals")
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
    response = JsonResponse({"conversations": [conversation_data(c, request.user) for c in qs]})
    response["Cache-Control"] = "private, no-store"
    return response


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
    listing = get_object_or_404(
        Listing.objects.select_related("seller").prefetch_related("images"),
        pk=listing_id,
    )
    if listing.seller_id == request.user.pk:
        return error("You cannot message yourself.")
    with transaction.atomic():
        conversation = Conversation.objects.filter(
            buyer=request.user,
            seller=listing.seller,
            listing=listing,
        ).first()
        if conversation is None:
            if listing.status != Listing.Status.ACTIVE:
                return error("This listing is unavailable.", 409, "listing_unavailable")
            try:
                with transaction.atomic():
                    conversation = Conversation.objects.create(
                        buyer=request.user,
                        seller=listing.seller,
                        listing=listing,
                    )
            except IntegrityError:
                conversation = Conversation.objects.get(
                    buyer=request.user,
                    seller=listing.seller,
                    listing=listing,
                )
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
def create_deal_proposal(request, conversation_id):
    parsed = parse_offer_payload(request)
    if parsed is None:
        return error("Enter a price from $0.01 to $999,999.99, confirm the sale, and provide a request ID.")
    price, key = parsed
    conversation = participant(request, conversation_id)
    if conversation.seller_id != request.user.pk:
        return error("Only the seller can submit an offer.", 403, "forbidden")
    try:
        existing = matching_request(conversation.pk, key, price, None)
        if existing:
            return offer_result(request, existing.pk)
        with transaction.atomic():
            touch_available_listing(conversation.listing_id)
            conversation = Conversation.objects.get(pk=conversation.pk)
            if conversation.seller_id != request.user.pk:
                raise DealConflict("The conversation changed.", "stale_conversation")
            existing = matching_request(conversation.pk, key, price, None)
            if existing:
                raise IdempotentRetry(existing.pk)
            if active_transaction_exists(conversation.listing_id):
                raise DealConflict("This listing is unavailable.", "listing_unavailable")
            if pending_bundle_request(conversation):
                raise DealConflict("Resolve the pending Bundle request before making an offer.",
                                   "bundle_request_pending")
            if DealProposal.objects.filter(conversation=conversation,
                    status=DealProposal.Status.AWAITING_BUYER).exists():
                raise DealConflict("An offer is already awaiting the buyer.", "offer_already_pending")
            proposal = DealProposal.objects.create(
                conversation=conversation, agreed_price=price, client_request_id=key,
            )
    except IdempotentRetry as exc:
        return offer_result(request, exc.proposal_id)
    except DealConflict as exc:
        return conflict_response(exc)
    except (IntegrityError, ValidationError):
        try:
            existing = matching_request(conversation.pk, key, price, None)
        except DealConflict as exc:
            return conflict_response(exc)
        if existing:
            return offer_result(request, existing.pk)
        if DealProposal.objects.filter(
            conversation=conversation, status=DealProposal.Status.AWAITING_BUYER
        ).exists():
            return error("An offer is already awaiting the buyer.", 409, "offer_already_pending")
        if not Listing.objects.filter(pk=conversation.listing_id,
                                      status=Listing.Status.ACTIVE).exists() or \
                active_transaction_exists(conversation.listing_id):
            return error("This listing is unavailable.", 409, "listing_unavailable")
        return error("The offer could not be saved. Retry with the same request ID.",
                     503, "offer_save_failed")
    return offer_result(request, proposal.pk, status=201)


@require_http_methods(["PATCH"])
def revise_deal_proposal(request, proposal_id):
    parsed = parse_offer_payload(request)
    if parsed is None:
        return error("Enter a price from $0.01 to $999,999.99, confirm the sale, and provide a request ID.")
    price, key = parsed
    previous = visible_proposal(request, proposal_id)
    conversation = previous.conversation
    if conversation.seller_id != request.user.pk:
        return error("Only the seller can revise an offer.", 403, "forbidden")
    try:
        existing = matching_request(conversation.pk, key, price, previous.pk)
        if existing:
            return offer_result(request, existing.pk)
        if previous.status != DealProposal.Status.AWAITING_BUYER:
            raise DealConflict("This offer is no longer current.", "stale_proposal")
        with transaction.atomic():
            touch_available_listing(conversation.listing_id)
            conversation = Conversation.objects.get(pk=conversation.pk)
            if conversation.seller_id != request.user.pk:
                raise DealConflict("The conversation changed.", "stale_conversation")
            existing = matching_request(conversation.pk, key, price, previous.pk)
            if existing:
                raise IdempotentRetry(existing.pk)
            if active_transaction_exists(conversation.listing_id):
                raise DealConflict("This listing is unavailable.", "listing_unavailable")
            if pending_bundle_request(conversation):
                raise DealConflict("Resolve the pending Bundle request before revising an offer.",
                                   "bundle_request_pending")
            changed = DealProposal.objects.filter(
                pk=previous.pk, conversation=conversation,
                status=DealProposal.Status.AWAITING_BUYER,
            ).update(status=DealProposal.Status.SUPERSEDED, updated_at=timezone.now())
            if changed != 1:
                raise DealConflict("This offer is no longer current.", "stale_proposal")
            proposal = DealProposal.objects.create(
                conversation=conversation, agreed_price=price, replaces=previous,
                client_request_id=key,
            )
    except IdempotentRetry as exc:
        return offer_result(request, exc.proposal_id)
    except DealConflict as exc:
        if exc.code == "listing_unavailable" and DealProposal.objects.filter(
            pk=previous.pk
        ).exclude(status=DealProposal.Status.AWAITING_BUYER).exists():
            return error("This offer is no longer current.", 409, "stale_proposal")
        return conflict_response(exc)
    except (IntegrityError, ValidationError):
        try:
            existing = matching_request(conversation.pk, key, price, previous.pk)
        except DealConflict as exc:
            return conflict_response(exc)
        if existing:
            return offer_result(request, existing.pk)
        if not DealProposal.objects.filter(
            pk=previous.pk, status=DealProposal.Status.AWAITING_BUYER
        ).exists():
            return error("This offer is no longer current.", 409, "stale_proposal")
        if not Listing.objects.filter(pk=conversation.listing_id,
                                      status=Listing.Status.ACTIVE).exists() or \
                active_transaction_exists(conversation.listing_id):
            return error("This listing is unavailable.", 409, "listing_unavailable")
        return error("The offer could not be saved. Retry with the same request ID.",
                     503, "offer_save_failed")
    return offer_result(request, proposal.pk, status=201)


@require_POST
def withdraw_deal_proposal(request, proposal_id):
    proposal = visible_proposal(request, proposal_id)
    if proposal.conversation.seller_id != request.user.pk:
        return error("Only the seller can withdraw an offer.", 403, "forbidden")
    try:
        with transaction.atomic():
            changed = DealProposal.objects.filter(
                pk=proposal.pk, status=DealProposal.Status.AWAITING_BUYER,
            ).update(status=DealProposal.Status.WITHDRAWN, updated_at=timezone.now())
            if changed != 1:
                raise DealConflict("This offer is no longer current.", "stale_proposal")
    except DealConflict as exc:
        return conflict_response(exc)
    return offer_result(request, proposal.pk)


@require_POST
def decide_deal_proposal(request, proposal_id):
    payload = data(request)
    decision = payload.get("decision") if payload else None
    if decision not in ("confirmed", "declined"):
        return error("Choose confirm or decline.")
    proposal = visible_proposal(request, proposal_id)
    conversation = proposal.conversation
    if conversation.buyer_id != request.user.pk:
        return error("Only the buyer can decide an offer.", 403, "forbidden")
    if decision == "confirmed" and proposal.status == DealProposal.Status.CONFIRMED:
        return offer_result(request, proposal.pk)
    if proposal.status == DealProposal.Status.UNAVAILABLE:
        if Listing.objects.filter(pk=conversation.listing_id,
                                  status=Listing.Status.ACTIVE).exists() and not \
                active_transaction_exists(conversation.listing_id):
            return error("This offer is no longer current.", 409, "stale_proposal")
        return error("This listing is unavailable.", 409, "listing_unavailable")
    if proposal.status != DealProposal.Status.AWAITING_BUYER:
        return error("This offer is no longer current.", 409, "stale_proposal")
    if decision == "declined":
        try:
            with transaction.atomic():
                changed = DealProposal.objects.filter(
                    pk=proposal.pk, status=DealProposal.Status.AWAITING_BUYER,
                ).update(status=DealProposal.Status.DECLINED, updated_at=timezone.now())
                if changed != 1:
                    raise DealConflict("This offer is no longer current.", "stale_proposal")
        except DealConflict as exc:
            return conflict_response(exc)
        return offer_result(request, proposal.pk)

    try:
        with transaction.atomic():
            reserve_listing(conversation.listing_id)
            proposal = DealProposal.objects.select_related("conversation", "transaction").get(pk=proposal.pk)
            conversation = proposal.conversation
            if conversation.buyer_id != request.user.pk:
                raise DealConflict("The conversation changed.", "stale_conversation")
            if proposal.status != DealProposal.Status.AWAITING_BUYER:
                raise DealConflict("This offer is no longer current.", "stale_proposal")
            if active_transaction_exists(conversation.listing_id):
                raise DealConflict("This listing is unavailable.", "listing_unavailable")
            listing = Listing.objects.get(pk=conversation.listing_id)
            deal = Transaction.objects.create(
                conversation=conversation, listing=listing, buyer_id=conversation.buyer_id,
                seller_id=conversation.seller_id, agreed_price=proposal.agreed_price,
                benchmark_price_snapshot=listing.benchmark_price,
                status=Transaction.Status.PENDING_PICKUP,
            )
            proposal.status = DealProposal.Status.CONFIRMED
            proposal.transaction = deal
            proposal.save(update_fields=["status", "transaction", "updated_at"])
            invalidate_other_offers(listing.pk, except_proposal_id=proposal.pk)
    except DealConflict as exc:
        latest = DealProposal.objects.get(pk=proposal.pk)
        if latest.status == DealProposal.Status.CONFIRMED and latest.transaction_id:
            return offer_result(request, latest.pk)
        if exc.code == "listing_unavailable":
            unavailable_offers_if_needed(conversation.listing_id)
        return conflict_response(exc)
    except (IntegrityError, ValidationError):
        return error("The transaction could not be saved. Retry the same offer.", 503,
                     "transaction_failed")
    return offer_result(request, proposal.pk)


@require_POST
def request_decision(request, request_id):
    payload = data(request)
    decision = payload.get("decision") if payload else None
    if decision not in ("accepted", "declined"):
        return error("Choose accept or decline.")
    item = get_object_or_404(BundleItem.objects.select_related("bundle", "listing"),
                             pk=request_id, listing__seller=request.user)
    if not Conversation.objects.filter(buyer=item.bundle.buyer, seller=request.user,
                                       listing=item.listing).exists():
        return error("Request conversation not found.", 404, "not_found")
    target = BundleItem.ItemStatus.ACCEPTED if decision == "accepted" else BundleItem.ItemStatus.DECLINED
    if item.item_status == target:
        return JsonResponse(request_data(item))
    if item.item_status != BundleItem.ItemStatus.REQUESTED:
        return error("This request has already been handled.", 409, "stale_request")
    try:
        with transaction.atomic():
            if decision == "accepted":
                reserve_listing(item.listing_id)
            item = get_object_or_404(
                BundleItem.objects.select_for_update().select_related("bundle", "listing"),
                pk=item.pk, listing__seller=request.user,
            )
            if not Conversation.objects.filter(buyer=item.bundle.buyer, seller=request.user,
                                               listing=item.listing).exists():
                raise Http404
            if item.item_status != BundleItem.ItemStatus.REQUESTED:
                raise DealConflict("This request has already been handled.", "stale_request")
            if decision == "accepted":
                if active_transaction_exists(item.listing_id):
                    raise DealConflict("This listing is unavailable.", "listing_unavailable")
                listing = Listing.objects.get(pk=item.listing_id)
                price = item.proposed_bundle_price if item.proposed_bundle_price is not None else item.listing_price_snapshot
                Transaction.objects.create(listing=listing, buyer=item.bundle.buyer, seller=request.user,
                    bundle=item.bundle, bundle_item=item, agreed_price=price,
                    benchmark_price_snapshot=listing.benchmark_price)
                item.final_price = price
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
            if decision == "accepted":
                invalidate_other_offers(item.listing_id)
    except DealConflict as exc:
        latest = BundleItem.objects.select_related("bundle").get(pk=item.pk)
        if latest.item_status == target:
            return JsonResponse(request_data(latest))
        return conflict_response(exc)
    except (IntegrityError, ValidationError):
        return error("The Bundle transaction could not be saved. Retry the request.",
                     503, "transaction_failed")
    return JsonResponse(request_data(item))
