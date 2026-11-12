"""Database querying and template context; independent of browser scripting."""

import logging

from django.db import DatabaseError
from django.db.models import Q, Count
from .auth_backend import has_campus_access
from .featured import decorate_listing, featured_bundles
from .forms import BrowseForm
from .models import Listing
from .local_llm import LocalLLMError, gate_listing_ids, rank_listing_ids
from .search_semantic import MIN_FALLBACK_SIMILARITY, SemanticSearchError, retrieve

ORDERING = {
    "newest": "-created_at",
    "price-asc": "listing_price",
    "price-desc": "-listing_price",
}
logger = logging.getLogger(__name__)
MAX_SEMANTIC_SCAN = 1000


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
    """Read all listings that satisfy structured filters for semantic retrieval."""
    eligible = filtered_listings(form, include_query=False).order_by("pk")
    fields = (
        "pk",
        "title",
        "description",
        "listing_price",
        "condition",
        "item_type__item_type_name",
        "item_type__category__category_name",
    )
    candidates = list(eligible.values(*fields)[:MAX_SEMANTIC_SCAN + 1])
    if len(candidates) > MAX_SEMANTIC_SCAN:
        raise SemanticSearchError("Too many eligible listings to search safely.")
    for candidate in candidates:
        candidate["category"] = " / ".join(
            (
                candidate.pop("item_type__category__category_name"),
                candidate.pop("item_type__item_type_name"),
            )
        )
    return candidates


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
            search_state = "no_results"
            try:
                candidates = _local_llm_candidates(form, query)
            except (DatabaseError, SemanticSearchError):
                logger.exception("Local AI search candidate query failed.")
                search_state = "unavailable"
                candidates = []
            if candidates:
                try:
                    retrieved = retrieve(query, candidates)
                except SemanticSearchError:
                    search_state = "unavailable"
                    retrieved = []
                if retrieved:
                    relevant_candidates = [item for item, _ in retrieved]
                    fallback_ids = [item["pk"] for item, score in retrieved
                                    if score >= MIN_FALLBACK_SIMILARITY]
                    fallback_ids = gate_listing_ids(
                        query, fallback_ids,
                        [{**item, "id": item["pk"]} for item in relevant_candidates],
                    )[:5]
                    try:
                        # Fallback above stays word-gated: it has no Llama check.
                        ranked_ids = rank_listing_ids(
                            query, relevant_candidates,
                            {item["pk"]: score for item, score in retrieved},
                        )
                        if ranked_ids:
                            search_state = "ai"
                        else:
                            ranked_ids = fallback_ids
                            search_state = "semantic_fallback_empty" if ranked_ids else "no_results"
                    except LocalLLMError:
                        logger.warning("Using semantic search results after Llama failure.")
                        ranked_ids = fallback_ids
                        search_state = "semantic_fallback_error" if ranked_ids else "unavailable"
                    if ranked_ids:
                        try:
                            ranked_listings = filtered_listings(form, include_query=False).filter(
                                pk__in=ranked_ids, status=Listing.Status.ACTIVE
                            )
                            listings_by_id = {item.pk: item for item in ranked_listings}
                            listings = [listings_by_id[pk] for pk in ranked_ids if pk in listings_by_id]
                            if not listings:
                                search_state = "no_results"
                        except DatabaseError:
                            logger.exception("Local AI search result query failed.")
                            search_state = "unavailable"
            if search_state in {"semantic_fallback_empty", "semantic_fallback_error"}:
                ai_search_fallback = True
                ai_search_fallback_title = "Showing semantic search matches."
                if search_state == "semantic_fallback_empty":
                    ai_search_fallback_message = (
                        "Llama did not select any listings. These items were found "
                        "by semantic similarity to your search."
                    )
                else:
                    ai_search_fallback_message = (
                        "Llama ranking could not be completed. These items were "
                        "found by semantic similarity to your search."
                    )
            elif search_state == "unavailable":
                listings = []
                ai_search_error = "AI search is unavailable right now. Please try again later."
            elif search_state == "no_results":
                listings = []
                ai_search_error = "No relevant listings found. Try another search or adjust your filters."
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
