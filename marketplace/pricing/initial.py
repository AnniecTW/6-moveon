"""Historical observed-price comparables for an initial listing benchmark.

The MerRec ``buy_comp`` price is not a verified transaction price. This
module deliberately abstains rather than extrapolating to unsupported types.
"""

from __future__ import annotations

import csv
import hashlib
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from statistics import median


SOURCE_PATH = Path(__file__).resolve().parents[2] / "experiments/merrec-pricing/data/stable_pricing_items_v1.csv"
POLICY_VERSION = "initial-v1.3"
SOURCE_KIND = "UNVERIFIED_BUY_COMP_OBSERVED_PRICE"
CENT = Decimal("0.01")
MIN_EXACT = 8  # Provisional support policy, not a statistical law.
MIN_TYPE_ONLY = 10
SUPPORTED_CONDITIONS = {"NEW", "LIKE_NEW", "GOOD", "FAIR", "POOR"}


def normalize(value: str | None) -> str:
    return " ".join((value or "").casefold().split())


def condition_key(value: str | None) -> str:
    return normalize(value).replace(" ", "_").upper()


def money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def percentile(values: list[Decimal], fraction: Decimal) -> Decimal:
    """Linear-interpolated observed quantile; not a predictive interval."""
    ordered = sorted(values)
    position = Decimal(len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


@dataclass(frozen=True)
class Observation:
    item_id: str
    observed_at: datetime
    price: Decimal
    category: str
    item_type: str
    condition: str
    brand: str
    name: str
    source_shard: str


def load_source(path: Path = SOURCE_PATH) -> tuple[list[Observation], dict]:
    """Filter invalid/flagged rows and deduplicate by the earliest item event."""
    counters = {"source_rows": 0, "ineligible": 0, "price_flagged": 0,
                "invalid": 0, "duplicate_item_id": 0}
    records: dict[str, Observation] = {}
    raw = path.read_bytes()
    with path.open(encoding="utf-8-sig", newline="") as source:
        for row in csv.DictReader(source):
            counters["source_rows"] += 1
            if row["training_eligibility"] != "INCLUDE":
                counters["ineligible"] += 1
                continue
            if row["price_risk_flags"].strip():
                counters["price_flagged"] += 1
                continue
            try:
                price = Decimal(row["price"])
                observed_at = datetime.fromisoformat(row["stime"].replace("Z", "+00:00"))
                condition = condition_key(row["item_condition_name"])
                item_id = row["item_id"].strip()
                if (not price.is_finite() or price <= 0 or not item_id or
                    not row["moveon_category"].strip() or not row["moveon_item_type"].strip() or
                    condition not in SUPPORTED_CONDITIONS or observed_at.tzinfo is None):
                    raise ValueError("invalid price, category, type, condition, or timestamp")
            except (ValueError, KeyError, ArithmeticError):
                counters["invalid"] += 1
                continue
            observation = Observation(
                item_id=item_id, observed_at=observed_at, price=price,
                category=normalize(row["moveon_category"]),
                item_type=normalize(row["moveon_item_type"]),
                condition=condition, brand=normalize(row["brand_name"]),
                name=normalize(row["name"]), source_shard=row["source_shard"],
            )
            if item_id in records:
                counters["duplicate_item_id"] += 1
                if records[item_id].observed_at <= observed_at:
                    continue
            records[item_id] = observation
    counters["eligible_rows"] = len(records)
    counters["sha256"] = hashlib.sha256(raw).hexdigest()
    return sorted(records.values(), key=lambda record: (record.observed_at, record.item_id)), counters


def recommend(
    records: list[Observation], *, category: str, item_type: str,
    condition: str, brand: str = "",
) -> dict:
    """Return a qualified historical benchmark or an explicit abstention.

    The seller's listing price is intentionally absent from the inputs.
    """
    category, item_type, brand = map(normalize, (category, item_type, brand))
    condition = condition_key(condition)
    base = {"method": "ABSTAIN", "benchmark_price": None,
            "suggested_listing_price": None, "range_low": None, "range_high": None,
            "range_kind": None, "evidence_grade": "INSUFFICIENT",
            "comparable_count": 0, "source_price_kind": SOURCE_KIND,
            "policy_version": POLICY_VERSION, "condition_factor": None,
            "explanation": "No sufficiently matched historical observations are available. Set your own price."}
    if (condition and condition not in SUPPORTED_CONDITIONS) or not category or not item_type:
        return base
    same_type = [r for r in records if r.category == category and r.item_type == item_type]
    exact_condition = [r for r in same_type if r.condition == condition] if condition else []
    if not same_type:
        base["explanation"] = (
            f"No {category.title()} / {item_type.title()} observations exist in the "
            "2023 research sample. Set your own price; nearby categories are not "
            "reliable substitutes."
        )
        return base
    brand_exact = [r for r in exact_condition if brand and r.brand == brand]
    chosen: list[Observation] = []
    method = ""
    factor = None
    factor_target: list[Observation] = []
    factor_base: list[Observation] = []
    if not condition and len(same_type) >= MIN_TYPE_ONLY:
        chosen, method = same_type, "TYPE_MEDIAN_UNADJUSTED"
    elif len(brand_exact) >= MIN_EXACT:
        chosen, method = brand_exact, "BRAND_CONDITION_MEDIAN"
    elif brand and len(exact_condition) >= MIN_EXACT:
        # A brand-specific reference can be adjusted only with an observed
        # same-type condition ratio supported on both sides.
        reference = [r for r in same_type if r.brand == brand and r.condition == "NEW"]
        new_type = [r for r in same_type if r.condition == "NEW"]
        if condition != "NEW" and len(reference) >= MIN_EXACT and len(new_type) >= MIN_EXACT:
            denominator = Decimal(median(r.price for r in new_type))
            factor = Decimal(median(r.price for r in exact_condition)) / denominator
            chosen, method = reference, "BRAND_CONDITION_FACTOR"
            factor_target, factor_base = exact_condition, new_type
        else:
            chosen, method = exact_condition, "TYPE_CONDITION_MEDIAN"
    elif len(exact_condition) >= MIN_EXACT:
        chosen, method = exact_condition, "TYPE_CONDITION_MEDIAN"
    elif condition in {"NEW", "LIKE_NEW", "GOOD"} and len(same_type) >= MIN_TYPE_ONLY:
        chosen, method = same_type, "TYPE_MEDIAN_UNADJUSTED"
    if not chosen:
        # Show the observed median as a clearly flagged reference when the
        # usual support policy is not met. Never infer a condition discount.
        if exact_condition:
            chosen, method = exact_condition, "SPARSE_CONDITION_MEDIAN"
        else:
            chosen, method = same_type, "SPARSE_TYPE_MEDIAN"
    sparse = method.startswith("SPARSE_")
    prices = [r.price for r in chosen]
    benchmark = Decimal(median(prices))
    low = percentile(prices, Decimal("0.25")) if not sparse else None
    high = percentile(prices, Decimal("0.75")) if not sparse else None
    if factor is not None:
        benchmark, low, high = benchmark * factor, low * factor, high * factor
    benchmark = money(benchmark)
    if benchmark <= 0:
        return base
    earliest = min(r.observed_at.date() for r in chosen)
    latest = max(r.observed_at.date() for r in chosen)
    if sparse:
        count = len(chosen)
        match_detail = (
            f"{condition.replace('_', ' ').title()} condition" if method == "SPARSE_CONDITION_MEDIAN"
            else "all conditions because no supported condition-specific estimate is available"
        )
        warning = (
            f"Only {count} historical {'item is' if count == 1 else 'items are'} available "
            f"for reference ({match_detail}). This price may not be reliable. "
            "These are 2023 US-wide observed prices, not verified sales or current UIUC prices."
        )
        base.update({
            "method": method, "benchmark_price": benchmark,
            "suggested_listing_price": benchmark, "range_low": None,
            "range_high": None, "range_kind": None,
            "evidence_grade": "VERY_LOW", "comparable_count": count,
            "comparable_item_ids": [r.item_id for r in chosen],
            "source_shards": sorted({r.source_shard for r in chosen}),
            "observed_from": earliest.isoformat(),
            "observed_through": latest.isoformat(),
            "warning": warning,
            "explanation": f"Provisional median of {count} observed prices for {item_type.title()}. {warning}",
        })
        return base
    detail = ("a same-item-type condition ratio applied to a same-brand New median"
              if factor is not None else
              "the item-type median across all conditions; select a condition for a more specific check"
              if method == "TYPE_MEDIAN_UNADJUSTED" and not condition else
              "the item-type median without a condition adjustment"
              if method == "TYPE_MEDIAN_UNADJUSTED" else
              "the median of matched item-type and condition observations")
    base.update({
        "method": method, "benchmark_price": benchmark,
        "suggested_listing_price": benchmark, "range_low": money(low),
        "range_high": money(high), "range_kind": "OBSERVED_IQR",
        # 2023 nonlocal and unverified source caps every result at LOW.
        "evidence_grade": "LOW", "comparable_count": len(chosen),
        "condition_factor": str(factor) if factor is not None else None,
        "comparable_item_ids": [r.item_id for r in chosen],
        "source_shards": sorted({r.source_shard for r in chosen}),
        "factor_target_item_ids": [r.item_id for r in factor_target],
        "factor_base_item_ids": [r.item_id for r in factor_base],
        "observed_from": earliest.isoformat(),
        "observed_through": latest.isoformat(),
        "explanation": (f"Based on {len(chosen)} historical MerRec observations: {detail}. "
                        "The range is the observed middle 50%, not a prediction interval. "
                        "These 2023 US-wide prices are not verified sales or current UIUC prices."),
    })
    return base
