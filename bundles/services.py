"""
Bundle-tier generation service for the AI Bundle Builder.

generate_bundle_tiers() classifies eligible listings, per requested
ItemType, into Budget / Best Value / Premium tiers. It never decides a
price - the bundle price is simply the sum of the chosen listings'
listing_price (see bundles/views.py). If GEMINI_API_KEY isn't configured,
or the call fails/returns something unusable, it falls back to a plain
price-based heuristic (cheapest/median/priciest) so the wizard always
produces a usable bundle.
"""

import json
import logging
from datetime import date

from django.conf import settings
from django.db.models import Avg

from marketplace.models import Listing, PriceRecommendation, Transaction

from .models import Bundle

logger = logging.getLogger(__name__)

GEMINI_MODEL_NAME = "gemini-3.6-flash"

TIERS = ["BUDGET", "BEST_VALUE", "PREMIUM"]


def generate_bundle_tiers(space, item_type_ids, buyer):
    """
    space: a Bundle.Space value (e.g. "LIVING_ROOM").
    item_type_ids: iterable of ItemType ids the buyer requested.
    buyer: the User building this bundle - their own listings are excluded
    from candidates, since a buyer can't message/buy their own listing
    (Conversation/Transaction both enforce this; excluding it here means
    the bundle never gets built with an impossible pick in the first place).

    Returns {"tiers": {...}, "missing_categories": [item_type_id, ...],
    "source": "llm" | "heuristic" | None}. "tiers" maps each tier name to
    {"items": {item_type_id: listing_id}, "rationale": str}.
    """
    candidates_by_type = _eligible_candidates(item_type_ids, buyer)
    missing_categories = [
        item_type_id
        for item_type_id in item_type_ids
        if not candidates_by_type.get(item_type_id)
    ]
    usable_by_type = {
        item_type_id: listings
        for item_type_id, listings in candidates_by_type.items()
        if listings
    }

    if not usable_by_type:
        return {"tiers": {}, "missing_categories": missing_categories, "source": None}

    api_key = getattr(settings, "GEMINI_API_KEY", "")
    if api_key:
        try:
            prompt = _build_prompt(space, usable_by_type)
            raw = _call_gemini(prompt, api_key)
            tiers = _validate_and_normalize(raw, usable_by_type)
            if tiers is not None:
                return {
                    "tiers": tiers,
                    "missing_categories": missing_categories,
                    "source": "llm",
                }
            logger.warning(
                "Gemini bundle response failed validation; falling back to heuristic."
            )
        except Exception:
            logger.exception(
                "Gemini bundle generation failed; falling back to heuristic."
            )

    return {
        "tiers": _heuristic_tiers(usable_by_type),
        "missing_categories": missing_categories,
        "source": "heuristic",
    }


def _eligible_candidates(item_type_ids, buyer):
    listings = (
        Listing.objects.filter(
            item_type_id__in=item_type_ids,
            status=Listing.Status.ACTIVE,
            bundle_eligible=True,
        )
        .exclude(seller=buyer)
        .select_related("item_type")
    )

    by_type = {item_type_id: [] for item_type_id in item_type_ids}
    for listing in listings:
        by_type[listing.item_type_id].append(listing)
    return by_type


def _recent_average_sale_price(item_type_id):
    return Transaction.objects.filter(
        listing__item_type_id=item_type_id,
        status=Transaction.Status.COMPLETED,
    ).aggregate(avg_price=Avg("agreed_price"))["avg_price"]


def _latest_price_recommendation(listing):
    return (
        PriceRecommendation.objects.filter(listing=listing)
        .order_by("-generated_at")
        .first()
    )


def _candidate_payload(listing, recent_average_sale_price):
    payload = {
        "listing_id": listing.id,
        "title": listing.title,
        "price": float(listing.listing_price),
        "condition": listing.condition,
        "description": listing.description or "",
    }
    if listing.move_out_date:
        payload["days_until_move_out"] = (listing.move_out_date - date.today()).days
    if listing.benchmark_price is not None:
        payload["benchmark_price"] = float(listing.benchmark_price)
    if listing.benchmark_low is not None:
        payload["benchmark_low"] = float(listing.benchmark_low)
    if listing.benchmark_high is not None:
        payload["benchmark_high"] = float(listing.benchmark_high)
    if recent_average_sale_price is not None:
        payload["recent_average_sale_price_same_category"] = float(
            recent_average_sale_price
        )
    latest_recommendation = _latest_price_recommendation(listing)
    if latest_recommendation is not None:
        payload["latest_price_recommendation_status"] = latest_recommendation.status
    return payload


def _build_prompt(space, candidates_by_type):
    categories_payload = []
    for item_type_id, listings in candidates_by_type.items():
        recent_average_sale_price = _recent_average_sale_price(item_type_id)
        categories_payload.append(
            {
                "item_type_id": item_type_id,
                "item_type_name": listings[0].item_type.item_type_name,
                "candidates": [
                    _candidate_payload(listing, recent_average_sale_price)
                    for listing in listings
                ],
            }
        )

    space_label = dict(Bundle.Space.choices).get(space, space)

    instructions = (
        "You are helping classify secondhand marketplace listings into three "
        "bundle tiers for a campus resale app called MoveOn. For EACH category "
        "below, pick exactly one candidate listing for each of three tiers: "
        "BUDGET (a cheaper, lower-band option), PREMIUM (a pricier, higher-band "
        "option), and BEST_VALUE (your holistic judgment of the best "
        "price-to-condition/quality tradeoff - this is NOT necessarily the "
        "median price; it could equal the cheapest option if it is also in "
        "great condition). Use each candidate's price, condition, free-text "
        "description, days_until_move_out (lower means more urgent to sell), "
        "benchmark price range, recent_average_sale_price_same_category (if "
        "present), and latest_price_recommendation_status (if present) to "
        "inform your judgment - read the description for nuance the numbers "
        "alone don't capture. If a category has fewer than 3 good distinct "
        "options, you may reuse the same listing_id for more than one tier in "
        "that category. You are NOT deciding any price, only which listing "
        "fits which tier. Also write one short (20 words or fewer) rationale "
        "sentence per tier describing that tier's overall bundle pick."
    )

    output_schema = (
        "Respond with ONLY a JSON object of exactly this shape (item_type_id "
        "and listing_id as the integers given below, no extra keys, no prose "
        "outside the JSON):\n"
        '{"BUDGET": {"items": {"<item_type_id>": <listing_id>, ...}, '
        '"rationale": "<short sentence>"}, '
        '"BEST_VALUE": {"items": {...}, "rationale": "..."}, '
        '"PREMIUM": {"items": {...}, "rationale": "..."}}'
    )

    return (
        f"{instructions}\n\n{output_schema}\n\n"
        f"Space being furnished: {space_label}\n\n"
        f"Categories and candidates (JSON):\n{json.dumps(categories_payload, indent=2)}"
    )


GEMINI_TIMEOUT_SECONDS = 10


def _call_gemini(prompt, api_key):
    import google.generativeai as genai

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(GEMINI_MODEL_NAME)
    response = model.generate_content(
        prompt,
        generation_config=genai.GenerationConfig(response_mime_type="application/json"),
        # The SDK's default request_options retries transient/429 errors
        # with its own multi-attempt backoff (observed taking 30-40s on a
        # rate-limited key before finally raising). That fights the whole
        # point of the heuristic fallback below - a slow or unavailable
        # Gemini should fail fast so the buyer still gets a bundle quickly,
        # not eventually. One bounded attempt, no library retries.
        request_options={"timeout": GEMINI_TIMEOUT_SECONDS, "retry": None},
    )
    return json.loads(response.text)


def _validate_and_normalize(raw, candidates_by_type):
    """Never trust the model's ids blindly - only accept ones we actually sent."""
    if not isinstance(raw, dict):
        return None

    valid_ids_by_type = {
        item_type_id: {listing.id for listing in listings}
        for item_type_id, listings in candidates_by_type.items()
    }

    tiers = {}
    for tier in TIERS:
        tier_data = raw.get(tier)
        if not isinstance(tier_data, dict):
            return None
        items = tier_data.get("items")
        if not isinstance(items, dict):
            return None

        validated_items = {}
        for item_type_id_raw, listing_id_raw in items.items():
            try:
                item_type_id = int(item_type_id_raw)
                listing_id = int(listing_id_raw)
            except (TypeError, ValueError):
                continue
            if listing_id in valid_ids_by_type.get(item_type_id, set()):
                validated_items[item_type_id] = listing_id

        if not validated_items:
            return None

        tiers[tier] = {
            "items": validated_items,
            "rationale": str(tier_data.get("rationale") or "")[:280],
        }
    return tiers


def _heuristic_tiers(candidates_by_type):
    """Deliberately price-only - see bundles/services.py docstring and the
    design plan for why the fallback stays this simple while the LLM path
    uses condition/description/urgency/history."""
    tiers = {tier: {"items": {}, "rationale": ""} for tier in TIERS}
    for item_type_id, listings in candidates_by_type.items():
        ordered = sorted(listings, key=lambda listing: listing.listing_price)
        tiers["BUDGET"]["items"][item_type_id] = ordered[0].id
        tiers["PREMIUM"]["items"][item_type_id] = ordered[-1].id
        tiers["BEST_VALUE"]["items"][item_type_id] = ordered[len(ordered) // 2].id
    return tiers
