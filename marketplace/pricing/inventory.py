"""Current marketplace asking-price references alongside the research guide."""

from decimal import Decimal
from statistics import median

from marketplace.models import Listing

from .initial import Observation, money, normalize, percentile, recommend


LIVE_POLICY_VERSION = "initial-live-asks-v1"
LIVE_SOURCE_KIND = "MOVEON_ACTIVE_ASKING_PRICE"
MIN_LOCAL_SELLERS_TO_PREFER = 3


def active_observations(*, exclude_listing_id=None):
    """Add public active inventory to type discovery without changing the CSV."""
    listings = Listing.objects.filter(status=Listing.Status.ACTIVE).select_related(
        "item_type__category"
    ).order_by("-created_at", "-pk")
    if exclude_listing_id is not None:
        listings = listings.exclude(pk=exclude_listing_id)
    return [Observation(
        item_id=f"moveon:{listing.pk}", observed_at=listing.created_at,
        price=listing.listing_price,
        category=normalize(listing.item_type.category.category_name),
        item_type=normalize(listing.item_type.item_type_name),
        condition=listing.condition, brand=normalize(listing.brand),
        name=normalize(listing.title), source_shard="moveon-active",
    ) for listing in listings if listing.listing_price > 0]


def recommend_for_item_type(records, item_type, *, condition="", brand="",
                            exclude_listing_id=None):
    """Prefer sufficient live peers; otherwise retain the research guide."""
    historical = recommend(
        records, category=item_type.category.category_name,
        item_type=item_type.item_type_name, condition=condition, brand=brand,
    )
    listings = Listing.objects.filter(
        item_type=item_type, status=Listing.Status.ACTIVE,
    ).order_by("-created_at", "-pk")
    if exclude_listing_id is not None:
        listings = listings.exclude(pk=exclude_listing_id)
    candidates = list(listings)
    exact_candidates = [listing for listing in candidates if listing.condition == condition]
    # Repeated posts by one seller should not dominate the reference median.
    by_seller = {}
    for listing in exact_candidates or candidates:
        if listing.seller_id not in by_seller and listing.listing_price > 0:
            by_seller[listing.seller_id] = listing
    chosen = list(by_seller.values())
    if not chosen:
        if historical["benchmark_price"] is None:
            historical["explanation"] += (
                " No active MoveOn listings of this item type are available yet. "
                "Draft and inactive listings are excluded."
            )
        return historical
    if historical["benchmark_price"] is not None and len(chosen) < MIN_LOCAL_SELLERS_TO_PREFER:
        return historical

    prices = [Decimal(listing.listing_price) for listing in chosen]
    benchmark = money(Decimal(median(prices)))
    same_condition = bool(exact_candidates)
    count = len(chosen)
    basis = "same condition" if same_condition else "mixed conditions"
    warning = (
        f"Based on {count} current MoveOn asking price{'s' if count != 1 else ''} "
        f"from different sellers ({basis}). This is a provisional comparison, "
        "not a completed sale or a verified market value. Item details may differ."
    )
    return {
        "method": "LIVE_SAME_CONDITION_MEDIAN" if same_condition else "LIVE_TYPE_MEDIAN",
        "benchmark_price": benchmark, "suggested_listing_price": benchmark,
        "range_low": money(percentile(prices, Decimal("0.25"))) if count >= 3 else None,
        "range_high": money(percentile(prices, Decimal("0.75"))) if count >= 3 else None,
        "range_kind": "ACTIVE_ASK_IQR" if count >= 3 else None,
        "evidence_grade": "VERY_LOW", "comparable_count": count,
        "source_price_kind": LIVE_SOURCE_KIND,
        "policy_version": LIVE_POLICY_VERSION,
        "condition_factor": None,
        "comparable_item_ids": [f"moveon:{listing.pk}" for listing in chosen],
        "observed_from": min(listing.created_at.date() for listing in chosen).isoformat(),
        "observed_through": max(listing.created_at.date() for listing in chosen).isoformat(),
        "warning": warning,
        "explanation": warning,
    }
