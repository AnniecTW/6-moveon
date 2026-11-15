"""Record one AISearchLog row per search request that has a query.

Logging must never break search: database errors are logged and swallowed.
"""

import logging

from django.db import DatabaseError

from .models import AISearchLog

logger = logging.getLogger(__name__)

# Structured browse filters; the analytics question is which ones shoppers combine with search.
FILTER_FIELDS = ("category", "item_type", "condition", "fulfillment", "min_price", "max_price", "bundle")


def _ms(seconds):
    return None if seconds is None else max(0, round(seconds * 1000))


def record_search(request, context, *, elapsed_seconds):
    """Store the search described by ``browse_context``'s result; return the row or None."""
    query = request.GET.get("q", "").strip()[:200]
    if not query:
        return None
    search = context.get("ai_search_metrics") or {}
    llm = context.get("ai_llm_metrics") or {}
    try:
        return AISearchLog.objects.create(
            user=request.user if request.user.is_authenticated else None,
            mode=context["search_mode"],
            query=query,
            filters_used=[name for name in FILTER_FIELDS
                          if any(value.strip() for value in request.GET.getlist(name))],
            state=context.get("ai_search_state", ""),
            result_count=len(context["listings"]),
            candidate_count=search.get("candidate_count"),
            retrieved_count=search.get("retrieved_count"),
            total_ms=_ms(elapsed_seconds),
            embedding_ms=_ms(search.get("embedding_seconds")),
            embedding_model=search.get("embedding_model", ""),
            embedding_texts_sent=search.get("embedding_texts_sent"),
            embedding_chars=search.get("embedding_chars"),
            embedding_error=search.get("embedding_error", ""),
            llm_ms=_ms(llm.get("seconds")),
            llm_model=llm.get("model", ""),
            prompt_tokens=llm.get("prompt_tokens"),
            completion_tokens=llm.get("completion_tokens"),
            reasoning_tokens=llm.get("reasoning_tokens"),
            llm_error=llm.get("error", ""),
        )
    except DatabaseError:
        logger.exception("Could not record search analytics.")
        return None
