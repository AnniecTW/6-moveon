"""Conservative, seller-bounded bundle price proposals."""

from decimal import Decimal


POLICY_VERSION = "bundle-market-gap-v1"
ZERO = Decimal("0.00")


def propose(listing):
    """Use the current ask as the baseline, including any approved markdown."""
    ask = Decimal(listing.listing_price).quantize(Decimal("0.01"))
    floor = Decimal(listing.minimum_price).quantize(Decimal("0.01")) if listing.minimum_price is not None else None
    cap = Decimal(listing.bundle_discount_cap).quantize(Decimal("0.01")) if listing.bundle_discount_cap is not None else None
    benchmark = Decimal(listing.benchmark_price).quantize(Decimal("0.01")) if listing.benchmark_price is not None else None
    metadata = listing.valuation_metadata or {}
    supported = metadata.get("evidence_grade") == "LOW" and benchmark is not None and benchmark > 0
    capacity = ZERO
    if (listing.bundle_eligible and floor is not None and cap is not None
            and floor > 0 and cap > 0):
        capacity = max(ZERO, min(ask - floor, cap))
    market_gap = max(ZERO, ask - benchmark) if supported else ZERO
    discount = min(capacity, market_gap)
    price = ask - discount
    details = {
        "policy_version": POLICY_VERSION,
        "listing_price": str(ask),
        "minimum_price": str(floor) if floor is not None else None,
        "bundle_discount_cap": str(cap) if cap is not None else None,
        "benchmark_price": str(benchmark) if benchmark is not None else None,
        "evidence_grade": metadata.get("evidence_grade", "UNKNOWN"),
        "benchmark_supported": supported,
        "market_gap": str(market_gap),
        "eligible_capacity": str(capacity),
        "proposed_discount": str(discount),
        "price": str(price),
    }
    return price, details


def still_valid(item, listing):
    """A seller must reapprove if the ask, terms, or evidence changed."""
    price, details = propose(listing)
    if not item.discount_calculation:
        return (listing.bundle_eligible and item.listing_price_snapshot == listing.listing_price
                and item.proposed_bundle_price == listing.listing_price)
    return (item.listing_price_snapshot == listing.listing_price
            and item.proposed_bundle_price == price
            and item.discount_calculation == details
            and listing.bundle_eligible)
