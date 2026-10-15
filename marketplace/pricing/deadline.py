"""Seller-approved, fixed-window deadline markdowns. No automatic price application."""

from datetime import timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from marketplace.models import DeadlineNotification, Listing, PriceRecommendation, Transaction


POLICY_VERSION = "deadline-power-v2"
NOTIFICATION_DAYS = frozenset({30, 21, 14, 7, 3})
CENT = Decimal("0.01")


def money(value):
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


def configured_gamma(*, urgent=False):
    setting = "MOVEON_URGENT_DEADLINE_GAMMA" if urgent else "MOVEON_DEADLINE_GAMMA"
    gamma = Decimal(str(getattr(settings, setting, "1.2" if urgent else "2")))
    if not gamma.is_finite() or gamma <= 1 or gamma > 99:
        raise ValueError(f"{setting} must be greater than 1 and at most 99")
    if urgent and gamma >= configured_gamma():
        raise ValueError("MOVEON_URGENT_DEADLINE_GAMMA must be below MOVEON_DEADLINE_GAMMA")
    return gamma


def curve_price(start_price, floor, start_date, move_out_date, day, gamma):
    start_price, floor, gamma = Decimal(start_price), Decimal(floor), Decimal(gamma)
    if (not all(value.is_finite() for value in (start_price, floor, gamma))
            or start_price <= 0 or floor <= 0 or floor > start_price or gamma <= 1):
        raise ValueError("Invalid deadline price, floor, or exponent")
    duration = (move_out_date - start_date).days
    if duration <= 0:
        raise ValueError("The original selling window must be positive")
    remaining = max(0, min(duration, (move_out_date - day).days))
    ratio = Decimal(remaining) / Decimal(duration)
    # Complementary power curve: reductions grow as elapsed time grows.
    return money(floor + (start_price - floor) * (1 - (1 - ratio) ** gamma))


def expire_pending(listing, *, at=None):
    now = at or timezone.now()
    PriceRecommendation.objects.filter(
        listing=listing, status=PriceRecommendation.Status.PENDING
    ).update(status=PriceRecommendation.Status.EXPIRED, responded_at=now)


def schedule_floor(listing):
    return (listing.urgent_minimum_price if listing.sell_no_matter_what
            else listing.minimum_price)


def can_start_schedule(listing, day, base_price):
    floor = schedule_floor(listing)
    return (listing.status == Listing.Status.ACTIVE and listing.move_out_date
            and listing.move_out_date > day and listing.minimum_price is not None
            and base_price is not None and floor is not None
            and Decimal("0") < floor <= listing.minimum_price <= base_price
            and listing.listing_price > 0)


def reset_schedule(listing, *, day=None, start=True, baseline=None):
    """Invalidate the old window, optionally preserving an approved original base."""
    day = day or timezone.localdate()
    base_price = (listing.deadline_base_price or
                  (baseline.deadline_start_price if baseline and baseline.deadline_start_date else listing.listing_price))
    start_date = (min(baseline.deadline_start_date, listing.move_out_date - timedelta(days=30))
                  if baseline and baseline.deadline_start_date and listing.move_out_date else
                  min(day, listing.move_out_date - timedelta(days=30)) if listing.move_out_date else None)
    listing.deadline_revision += 1
    listing.deadline_start_date = None
    listing.deadline_end_date = None
    listing.deadline_start_price = None
    listing.deadline_floor = None
    listing.deadline_urgent_floor = None
    listing.deadline_gamma = None
    listing.deadline_policy_version = ""
    listing.deadline_below_floor_opt_in = False
    if start and can_start_schedule(listing, day, base_price):
        # A listing entering the final 30 days joins the existing 30-day
        # reference window, so its first proposal reflects time remaining.
        listing.deadline_start_date = start_date
        listing.deadline_end_date = listing.move_out_date
        listing.deadline_start_price = base_price
        listing.deadline_floor = listing.minimum_price
        listing.deadline_urgent_floor = listing.urgent_minimum_price if listing.sell_no_matter_what else None
        listing.deadline_gamma = configured_gamma(urgent=listing.sell_no_matter_what)
        listing.deadline_policy_version = POLICY_VERSION
        listing.deadline_below_floor_opt_in = listing.sell_no_matter_what
    if listing.pk:
        expire_pending(listing)
        now = timezone.now()
        DeadlineNotification.objects.filter(
            listing=listing, resolved_at__isnull=True,
        ).update(resolved_at=now, read_at=now)


def available(listing):
    if listing.status != Listing.Status.ACTIVE:
        return False
    if Transaction.objects.filter(listing=listing).exclude(status=Transaction.Status.CANCELLED).exists():
        return False
    from messaging.models import DealProposal
    return not DealProposal.objects.filter(
        conversation__listing=listing, status=DealProposal.Status.AWAITING_BUYER
    ).exists()


def target_for(listing, day):
    if (not listing.deadline_start_date or not listing.deadline_end_date
            or not listing.deadline_start_price or not listing.deadline_floor
            or not listing.deadline_gamma or listing.deadline_policy_version != POLICY_VERSION
            or listing.move_out_date != listing.deadline_end_date
            or listing.sell_no_matter_what != listing.deadline_below_floor_opt_in
            or day < listing.deadline_start_date or day > listing.deadline_end_date
            or listing.minimum_price != listing.deadline_floor
            or (listing.deadline_base_price is not None
                and listing.deadline_base_price != listing.deadline_start_price)
            or (listing.sell_no_matter_what and (listing.urgent_minimum_price is None
                or listing.urgent_minimum_price != listing.deadline_urgent_floor))):
        return None
    try:
        floor = (listing.deadline_urgent_floor if listing.sell_no_matter_what
                 and listing.deadline_urgent_floor is not None else listing.deadline_floor)
        target = curve_price(listing.deadline_start_price, floor,
                             listing.deadline_start_date, listing.deadline_end_date,
                             day, listing.deadline_gamma)
    except (ValueError, InvalidOperation):
        return None
    target = min(target, listing.listing_price)
    return target, target < listing.deadline_floor


@transaction.atomic
def evaluate_listing(listing_id, *, day=None):
    day = day or timezone.localdate()
    listing = Listing.objects.select_for_update().get(pk=listing_id)
    if not available(listing):
        expire_pending(listing)
        return None
    if (listing.deadline_start_date is None and can_start_schedule(
            listing, day, listing.deadline_base_price or listing.listing_price)):
        # Recover older active listings that have valid settings but no plan.
        if listing.deadline_base_price is None:
            listing.deadline_base_price = listing.listing_price
        reset_schedule(listing, day=day)
        listing.save()
    calculated = target_for(listing, day)
    if calculated is None:
        expire_pending(listing)
        return None
    target, below_floor = calculated
    pending = PriceRecommendation.objects.filter(
        listing=listing, status=PriceRecommendation.Status.PENDING
    ).first()
    if pending and (pending.schedule_date != day or pending.schedule_revision != listing.deadline_revision
                    or pending.previous_price != listing.listing_price or pending.recommended_price != target):
        expire_pending(listing)
        pending = None
    if target >= listing.listing_price:
        return None
    if pending:
        return pending
    if PriceRecommendation.objects.filter(
        listing=listing, schedule_date=day, schedule_revision=listing.deadline_revision,
        previous_price=listing.listing_price, recommended_price=target
    ).exists():
        return None
    days = (listing.deadline_end_date - day).days
    reason = f"{days} day(s) until move-out."
    if below_floor:
        reason += " Below the normal minimum; separate approval is required."
    return PriceRecommendation.objects.create(
        listing=listing, previous_price=listing.listing_price,
        recommended_price=target, rationale=reason,
        policy_version=listing.deadline_policy_version,
        schedule_revision=listing.deadline_revision, schedule_date=day,
        below_floor=below_floor,
    )


@transaction.atomic
def notify_trigger(listing_id, recommendation_id, *, day=None):
    """Create one MoveOn inbox reminder for an exact remaining-day milestone."""
    day = day or timezone.localdate()
    listing = Listing.objects.select_for_update().get(pk=listing_id)
    remaining = (listing.move_out_date - day).days if listing.move_out_date else None
    if remaining not in NOTIFICATION_DAYS or not available(listing):
        return None
    recommendation = PriceRecommendation.objects.filter(
        pk=recommendation_id, listing=listing,
        status=PriceRecommendation.Status.PENDING,
        schedule_date=day, schedule_revision=listing.deadline_revision,
        previous_price=listing.listing_price,
    ).first()
    if recommendation is None or target_for(listing, day) != (
        recommendation.recommended_price, recommendation.below_floor
    ):
        return None
    notification, _ = DeadlineNotification.objects.get_or_create(
        listing=listing, schedule_revision=listing.deadline_revision,
        trigger_days=remaining,
        defaults={
            "seller": listing.seller,
            "recommendation": recommendation,
            "suggested_price_snapshot": recommendation.recommended_price,
        },
    )
    return notification


def decide(recommendation_id, seller_id, action, *, chosen_price=None,
           below_floor_approved=False, day=None):
    try:
        return _decide(recommendation_id, seller_id, action,
                       chosen_price=chosen_price,
                       below_floor_approved=below_floor_approved, day=day)
    except StaleRecommendation:
        PriceRecommendation.objects.filter(
            pk=recommendation_id, listing__seller_id=seller_id,
            status=PriceRecommendation.Status.PENDING,
        ).update(status=PriceRecommendation.Status.EXPIRED, responded_at=timezone.now())
        raise


class StaleRecommendation(ValueError):
    pass


@transaction.atomic
def _decide(recommendation_id, seller_id, action, *, chosen_price=None,
            below_floor_approved=False, day=None):
    day = day or timezone.localdate()
    listing_id = PriceRecommendation.objects.values_list("listing_id", flat=True).get(pk=recommendation_id)
    listing = Listing.objects.select_for_update().get(pk=listing_id)
    recommendation = PriceRecommendation.objects.select_for_update().get(pk=recommendation_id)
    if listing.seller_id != seller_id:
        raise PermissionError("This recommendation belongs to another seller")
    if recommendation.status != PriceRecommendation.Status.PENDING:
        raise ValueError("This recommendation has already been handled")
    if (not available(listing) or recommendation.schedule_date != day
            or recommendation.schedule_revision != listing.deadline_revision
            or recommendation.policy_version != listing.deadline_policy_version
            or recommendation.previous_price != listing.listing_price
            or target_for(listing, day) != (recommendation.recommended_price, recommendation.below_floor)):
        raise StaleRecommendation("This recommendation is stale; request a new evaluation")
    if action == "decline":
        recommendation.status = PriceRecommendation.Status.DECLINED
    elif action in ("accept", "modify"):
        if action == "accept":
            applied = recommendation.recommended_price
        else:
            try:
                applied = money(chosen_price)
            except (InvalidOperation, TypeError, ValueError):
                raise ValueError("Enter a valid price") from None
        if not applied.is_finite() or applied < CENT or applied >= listing.listing_price:
            raise ValueError("The approved price must be positive and below the current price")
        lowest_allowed = (listing.urgent_minimum_price if listing.sell_no_matter_what
                          and listing.urgent_minimum_price is not None else listing.minimum_price)
        if applied < lowest_allowed:
            raise ValueError("The approved price cannot be below your chosen minimum")
        if applied < listing.minimum_price and not (listing.sell_no_matter_what and below_floor_approved):
            raise ValueError("Below-floor prices require separate explicit approval")
        if recommendation.below_floor and applied < listing.minimum_price and not below_floor_approved:
            raise ValueError("Confirm this below-floor price separately")
        # Conditional update guards against another price/status change, including on SQLite.
        changed = Listing.objects.filter(
            pk=listing.pk, status=Listing.Status.ACTIVE,
            listing_price=recommendation.previous_price,
            deadline_revision=recommendation.schedule_revision,
        ).update(listing_price=applied, updated_at=timezone.now())
        if changed != 1:
            raise ValueError("The listing changed; review the latest price")
        recommendation.applied_price = applied
        recommendation.status = (PriceRecommendation.Status.ACCEPTED if action == "accept"
                                 else PriceRecommendation.Status.MODIFIED)
    else:
        raise ValueError("Choose accept, decline, or modify")
    recommendation.responded_at = timezone.now()
    recommendation.save(update_fields=["status", "applied_price", "responded_at"])
    DeadlineNotification.objects.filter(
        listing=listing, schedule_revision=listing.deadline_revision,
        resolved_at__isnull=True,
    ).update(resolved_at=recommendation.responded_at,
             read_at=recommendation.responded_at)
    return recommendation
