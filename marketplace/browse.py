"""Database querying and template context; independent of browser scripting."""

import re
import logging

from django.db import DatabaseError
from django.db.models import Q, Count
from .auth_backend import has_campus_access
from .featured import decorate_listing, featured_bundles
from .forms import BrowseForm
from .models import Listing
from .local_llm import InvalidListingIDsError, LocalLLMError, rank_listing_ids

ORDERING = {
    "newest": "-created_at",
    "price-asc": "listing_price",
    "price-desc": "-listing_price",
}
MAX_LOCAL_LLM_CANDIDATES = 40
SEARCH_STOP_WORDS = {
    "a", "an", "and", "are", "for", "i", "in", "is", "it", "me", "my",
    "of", "on", "or", "please", "recommend", "some", "the", "this", "to",
    "want", "with",
}
logger = logging.getLogger(__name__)


def filtered_listings(form, include_query=True):
    """One validated query implementation for HTML browsing and the public API."""
    listings = Listing.objects.filter(status=Listing.Status.ACTIVE).select_related(
        "seller", "item_type", "item_type__category"
    ).prefetch_related("images")
    if form.is_valid():
        values = form.cleaned_data
        if include_query:
            for term in values.get("q", "").split():
                listings = listings.filter(
                    Q(title__icontains=term)
                    | Q(description__icontains=term)
                    | Q(item_type__item_type_name__icontains=term)
                    | Q(seller__display_name__icontains=term)
                )
        for name, lookup in [
            ("category", "item_type__category_id__in"),
            ("item_type", "item_type_id__in"),
            ("condition", "condition__in"),
        ]:
            if values.get(name):
                listings = listings.filter(**{lookup: values[name]})
        fulfillment = values.get("fulfillment", [])
        if fulfillment:
            fulfillment_filter = Q(fulfillment_option__in=fulfillment)
            if any(
                option in fulfillment
                for option in (
                    Listing.Fulfillment.PICKUP,
                    Listing.Fulfillment.DELIVERY,
                )
            ):
                fulfillment_filter |= Q(
                    fulfillment_option=Listing.Fulfillment.BOTH
                )
            listings = listings.filter(fulfillment_filter)
        if values.get("bundle"):
            listings = listings.filter(bundle_eligible=True)
        for name, lookup in [
            ("min_price", "listing_price__gte"),
            ("max_price", "listing_price__lte"),
        ]:
            if values.get(name) is not None:
                listings = listings.filter(**{lookup: values[name]})
        if values.get("sort") == "popular":
            listings = listings.annotate(
                inquiry_count=Count("conversations", distinct=True)
            ).order_by("-inquiry_count", "-created_at", "pk")
        else:
            listings = listings.order_by(
                ORDERING.get(values.get("sort"), "-created_at"), "pk"
            )
    else:
        listings = listings.none()
    return listings


def _local_llm_candidates(form, query):
    """Prioritize text matches, then recent eligible listings, within a fixed cap."""
    eligible = filtered_listings(form, include_query=False).order_by(
        "-created_at", "pk"
    )
    fields = (
        "pk",
        "title",
        "description",
        "listing_price",
        "condition",
        "item_type__item_type_name",
        "item_type__category__category_name",
    )
    terms = [
        term
        for term in re.findall(r"[\w'-]{2,}", query.casefold())
        if term not in SEARCH_STOP_WORDS
    ][:20]

    matching_filter = Q()
    for term in terms:
        matching_filter |= (
            Q(title__icontains=term)
            | Q(description__icontains=term)
            | Q(item_type__item_type_name__icontains=term)
            | Q(item_type__category__category_name__icontains=term)
        )

    matched = (
        list(
            eligible.filter(matching_filter)
            .values(*fields)[:MAX_LOCAL_LLM_CANDIDATES]
        )
        if terms
        else []
    )
    matched_ids = [candidate["pk"] for candidate in matched]
    remaining = MAX_LOCAL_LLM_CANDIDATES - len(matched)
    recent = (
        list(eligible.exclude(pk__in=matched_ids).values(*fields)[:remaining])
        if remaining
        else []
    )

    candidates = matched + recent
    for candidate in candidates:
        candidate["category"] = " / ".join(
            (
                candidate.pop("item_type__category__category_name"),
                candidate.pop("item_type__item_type_name"),
            )
        )
    return candidates


def _random_filtered_listings(form):
    try:
        return list(filtered_listings(form, include_query=False).order_by("?")[:5])
    except DatabaseError:
        logger.exception("Local AI search fallback listing query failed.")
        return None


def browse_context(request, use_local_llm=False):
    form = BrowseForm(request.GET)
    listings = filtered_listings(form)
    search_mode = request.GET.get("search_mode", "keyword")
    if search_mode not in {"keyword", "ai"}:
        search_mode = "keyword"
    ai_search_error = ""
    ai_search_fallback = False
    ai_search_fallback_title = ""
    ai_search_fallback_message = ""
    query = form.cleaned_data.get("q", "").strip() if form.is_valid() else ""
    if use_local_llm and search_mode == "ai" and query:
        if form.is_valid():
            listings = []
            fallback_kind = ""
            try:
                candidates = _local_llm_candidates(form, query)
            except DatabaseError:
                logger.exception("Local AI search candidate query failed.")
                fallback_kind = "unavailable"
                candidates = []
            if candidates:
                logger.debug(
                    "Local search candidates: %s",
                    [
                        {
                            "id": item["pk"],
                            "title": item["title"],
                            "category": item["category"],
                        }
                        for item in candidates
                    ],
                )
                try:
                    ranked_ids = rank_listing_ids(query, candidates)
                except InvalidListingIDsError:
                    logger.warning("Local AI search returned no valid candidate IDs.")
                    ranked_ids = []
                    fallback_kind = "no_results"
                except LocalLLMError:
                    ranked_ids = []
                    fallback_kind = "unavailable"
                if ranked_ids:
                    try:
                        ranked_listings = filtered_listings(
                            form, include_query=False
                        ).filter(
                            pk__in=ranked_ids,
                            status=Listing.Status.ACTIVE,
                        )
                        listings_by_id = {item.pk: item for item in ranked_listings}
                        listings = [
                            listings_by_id[listing_id]
                            for listing_id in ranked_ids
                            if listing_id in listings_by_id
                        ]
                    except DatabaseError:
                        logger.exception("Local AI search result query failed.")
                        fallback_kind = "unavailable"
                    if not listings and not fallback_kind:
                        fallback_kind = "no_results"
                    logger.debug(
                        "Local search displayed listings: %s",
                        [
                            {
                                "id": item.pk,
                                "title": item.title,
                                "category": item.item_type.category.category_name,
                            }
                            for item in listings
                        ],
                    )
                elif not fallback_kind:
                    fallback_kind = "no_results"
            if fallback_kind:
                fallback_listings = _random_filtered_listings(form)
                if fallback_listings is None:
                    ai_search_error = (
                        "AI search could not load listings right now. Please try again."
                    )
                elif not fallback_listings:
                    ai_search_error = (
                        "AI search could not be completed, and no listings match "
                        "your filters. Please adjust your filters and try again."
                    )
                else:
                    listings = fallback_listings
                    ai_search_fallback = True
                    if fallback_kind == "unavailable":
                        ai_search_fallback_title = "AI search couldn't be completed."
                        ai_search_fallback_message = (
                            "We're showing random available listings that match your "
                            "filters. They are not AI recommendations. Please try again later."
                        )
                    else:
                        ai_search_fallback_title = (
                            "No relevant listings found for this search."
                        )
                        ai_search_fallback_message = (
                            "Please update your search terms. The listings below are "
                            "randomly selected fallback items, not AI recommendations."
                        )
    chips = []
    if form.is_valid():
        for name in (
            "q",
            "category",
            "item_type",
            "condition",
            "fulfillment",
            "min_price",
            "max_price",
            "bundle",
        ):
            labels = dict(
                (str(k), str(v)) for k, v in getattr(form.fields[name], "choices", [])
            )
            for value in request.GET.getlist(name):
                if not value:
                    continue
                params = request.GET.copy()
                params.setlist(name, [v for v in params.getlist(name) if v != value])
                label = labels.get(value, value)
                if name == "bundle":
                    label = "Bundle eligible"
                elif name == "min_price":
                    label = "Min $" + value
                elif name == "max_price":
                    label = "Max $" + value
                chips.append({"label": label, "url": "?" + params.urlencode()})
    try:
        bundles = featured_bundles()
    except DatabaseError:
        if not (use_local_llm and search_mode == "ai"):
            raise
        logger.exception("Local AI search could not load featured bundles.")
        bundles = []
    return {
        "listings": [decorate_listing(item) for item in listings],
        "search_mode": search_mode,
        "local_llm_search_enabled": use_local_llm,
        "ai_search_error": ai_search_error,
        "ai_search_fallback": ai_search_fallback,
        "ai_search_fallback_title": ai_search_fallback_title,
        "ai_search_fallback_message": ai_search_fallback_message,
        "filter_form": form,
        "filter_chips": chips,
        "featured_bundles": bundles,
        "campus_access": request.user.is_authenticated and has_campus_access(request.user),
    }
