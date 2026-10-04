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

import hashlib
import json
import logging
import random
import time
from datetime import date

from django.conf import settings
from django.core.cache import cache
from django.db.models import Avg
from django.utils import timezone

from marketplace.models import Listing, Transaction

from .models import Bundle

logger = logging.getLogger(__name__)

GEMINI_MODEL_NAME = "gemini-3.6-flash"  # default if GEMINI_MODEL_CHAIN is unset

# Google returns 503 "high demand" per model, so one overloaded model must not
# sink the request: each model in settings.GEMINI_MODEL_CHAIN gets one attempt
# per sweep, with no SDK-level retries. Time is bounded by the budget below.
GEMINI_CALL_TIMEOUT_SECONDS = 20
GEMINI_TOTAL_BUDGET_SECONDS = 30
GEMINI_CACHE_SECONDS = 600
MAX_CANDIDATES_PER_CATEGORY = 5
MAX_DESCRIPTION_CHARS = 160

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
        prompt_candidates = {
            item_type_id: _limit_candidates(listings)
            for item_type_id, listings in usable_by_type.items()
        }
        cache_key = _cache_key(space, prompt_candidates)
        cached = cache.get(cache_key)
        if cached is not None:
            logger.info("Bundle tiers served from cache (model=%s).", cached["model"])
            return {
                "tiers": cached["tiers"],
                "missing_categories": missing_categories,
                "source": "llm",
                "model": cached["model"],
                "cached": True,
            }
        try:
            prompt = _build_prompt(space, prompt_candidates)
            outcome = _generate_with_fallback(prompt, api_key, prompt_candidates)
        except Exception:
            logger.exception("Gemini bundle generation crashed; using heuristic.")
            outcome = None
        if outcome is not None:
            tiers, model = outcome
            cache.set(
                cache_key, {"tiers": tiers, "model": model}, GEMINI_CACHE_SECONDS
            )
            return {
                "tiers": tiers,
                "missing_categories": missing_categories,
                "source": "llm",
                "model": model,
                "cached": False,
            }
        logger.warning("All Gemini models failed; serving heuristic tiers.")

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


def _candidate_payload(listing, recent_average_sale_price):
    payload = {
        "listing_id": listing.id,
        "title": listing.title,
        "price": float(listing.listing_price),
        "condition": listing.condition,
        "description": (listing.description or "")[:MAX_DESCRIPTION_CHARS],
        "listed_days_ago": (timezone.now() - listing.created_at).days,
    }
    if listing.move_out_date:
        payload["days_until_move_out"] = (listing.move_out_date - date.today()).days
    if listing.retail_price is not None:
        payload["retail_price"] = float(listing.retail_price)
    if listing.benchmark_price is not None:
        payload["benchmark_price"] = float(listing.benchmark_price)
    if recent_average_sale_price is not None:
        payload["recent_average_sale_price_same_category"] = float(
            recent_average_sale_price
        )
    return payload


def _limit_candidates(listings):
    """Keep the prompt small: at most N candidates, evenly spread by price so
    the cheapest and priciest stay in and the tiers still have real choices."""
    if len(listings) <= MAX_CANDIDATES_PER_CATEGORY:
        return listings
    ordered = sorted(listings, key=lambda listing: listing.listing_price)
    n, k = len(ordered), MAX_CANDIDATES_PER_CATEGORY
    return [ordered[round(i * (n - 1) / (k - 1))] for i in range(k)]


def _cache_key(space, candidates_by_type):
    parts = [space]
    for item_type_id in sorted(candidates_by_type):
        for listing in candidates_by_type[item_type_id]:
            parts.append(
                f"{item_type_id}:{listing.id}:{listing.listing_price}:"
                f"{listing.updated_at.isoformat()}"
            )
    return "bundle-tiers:" + hashlib.sha256("|".join(parts).encode()).hexdigest()


def _generate_with_fallback(prompt, api_key, candidates_by_type):
    """Try each model in the chain once per sweep, moving on immediately on any
    failure (503/429/timeout/bad output). Returns (tiers, model) or None."""
    chain = list(getattr(settings, "GEMINI_MODEL_CHAIN", None) or [GEMINI_MODEL_NAME])
    deadline = time.monotonic() + GEMINI_TOTAL_BUDGET_SECONDS
    for sweep in range(2):
        for model in chain:
            remaining = deadline - time.monotonic()
            if remaining <= 1:
                return None
            started = time.monotonic()
            try:
                raw = _call_gemini(
                    prompt, api_key, model, min(GEMINI_CALL_TIMEOUT_SECONDS, remaining)
                )
                tiers = _validate_and_normalize(raw, candidates_by_type)
                if tiers is not None:
                    logger.info(
                        "Gemini %s succeeded in %.1fs (sweep %d).",
                        model, time.monotonic() - started, sweep + 1,
                    )
                    return tiers, model
                logger.warning("Gemini %s returned an invalid bundle response.", model)
            except Exception as exc:
                logger.warning(
                    "Gemini %s failed after %.1fs: %s: %s",
                    model, time.monotonic() - started, type(exc).__name__, exc,
                )
        if sweep == 0:
            time.sleep(random.uniform(0.5, 1.5))
    return None


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
        "You help build secondhand furniture/decor bundles for MoveOn, a campus "
        "resale app. For EACH category below, choose exactly one candidate "
        "listing for each of three tiers:\n"
        "- BUDGET: the lowest total cost that is still acceptable. Avoid "
        "candidates whose description reveals damage or defects.\n"
        "- PREMIUM: the best overall quality (condition, description, closeness "
        "to retail) even if it costs more.\n"
        "- BEST_VALUE: the best quality per dollar. This is NOT automatically "
        "the median price; judge it from condition, description, price versus "
        "retail/benchmark, and urgency.\n"
        "Rules: read each description for details the numbers miss, and treat a "
        "condition label that contradicts the description as untrustworthy. "
        "days_until_move_out is how urgent the seller is (lower means more "
        "urgent). Within one tier, prefer items whose style and color suit each "
        "other so the room looks coherent. When a category has 3 or more "
        "candidates, the three tiers should use different listings; reuse a "
        "listing across tiers only when fewer than 3 candidates exist. You never "
        "decide any price. For each tier also write one rationale of at most 20 "
        "words explaining that tier's overall bundle."
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
        f"Categories and candidates (JSON):\n{json.dumps(categories_payload, separators=(",", ":"))}"
    )


def _call_gemini(prompt, api_key, model_name, timeout):
    import google.generativeai as genai

    genai.configure(api_key=api_key)
    response = genai.GenerativeModel(model_name).generate_content(
        prompt,
        generation_config=genai.GenerationConfig(response_mime_type="application/json"),
        # No SDK retries: its built-in backoff retried 503s for minutes. Failure
        # handling lives in _generate_with_fallback, which tries other models.
        request_options={"timeout": timeout, "retry": None},
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
