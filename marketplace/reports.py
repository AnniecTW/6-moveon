"""Listing reports and CSV/JSON exports.

Exports and the report share the browse filters (`BrowseForm`), so users can
download exactly what they are looking at on the home page; with no filters
they get every active listing.
"""

import csv

from django.db.models import Avg, Count, Max, Min
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_GET

from .browse import filtered_listings
from .forms import BrowseForm
from .models import Listing

COLUMNS = [
    "id",
    "listing_id",
    "title",
    "category",
    "item_type",
    "condition",
    "status",
    "listing_price",
    "retail_price",
    "fulfillment_option",
    "bundle_eligible",
    "seller",
    "views",
    "created_at",
]


def _export_queryset(request):
    """Active listings matching the query string, newest first (ties by id)."""
    form = BrowseForm(request.GET)
    listings = filtered_listings(form)
    if not form.is_valid():
        return form, listings
    return form, listings.order_by("-created_at", "pk")


def _timestamp():
    return timezone.localtime().strftime("%Y-%m-%d_%H-%M")


def _safe_cell(value):
    """Stop spreadsheet apps from running user text such as '=SUM(...)' as a formula."""
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + value
    return value


def _row(listing):
    return {
        "id": listing.pk,
        "listing_id": str(listing.listing_id),
        "title": listing.title,
        "category": listing.item_type.category.category_name,
        "item_type": listing.item_type.item_type_name,
        "condition": listing.get_condition_display(),
        "status": listing.get_status_display(),
        "listing_price": str(listing.listing_price),
        "retail_price": str(listing.retail_price) if listing.retail_price is not None else "",
        "fulfillment_option": listing.get_fulfillment_option_display(),
        "bundle_eligible": listing.bundle_eligible,
        "seller": listing.seller.display_name or listing.seller.username,
        "views": listing.views,
        "created_at": timezone.localtime(listing.created_at).isoformat(),
    }


@require_GET
def listings_csv(request):
    form, listings = _export_queryset(request)
    if not form.is_valid():
        return HttpResponse("Invalid filters.", status=400, content_type="text/plain")
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = (
        f'attachment; filename="listings_{_timestamp()}.csv"'
    )
    writer = csv.writer(response)
    writer.writerow(COLUMNS)
    for listing in listings:
        row = _row(listing)
        writer.writerow([_safe_cell(row[column]) for column in COLUMNS])
    return response


@require_GET
def listings_json(request):
    form, listings = _export_queryset(request)
    if not form.is_valid():
        return JsonResponse(
            {"error": "Invalid filters.", "fields": form.errors.get_json_data()},
            status=400,
        )
    rows = [_row(listing) for listing in listings]
    response = JsonResponse(
        {
            "generated_at": timezone.now().isoformat(),
            "record_count": len(rows),
            "listings": rows,
        },
        json_dumps_params={"indent": 2},
    )
    response["Content-Disposition"] = (
        f'attachment; filename="listings_{_timestamp()}.json"'
    )
    return response


@require_GET
def listing_report(request):
    form, listings = _export_queryset(request)
    valid = form.is_valid()
    # Re-query by pk so the grouped counts ignore any annotations on `listings`.
    base = Listing.objects.filter(pk__in=listings.values("pk")) if valid else Listing.objects.none()
    stats = (Count("pk"), Avg("listing_price"), Min("listing_price"), Max("listing_price"))
    by_category = (
        base.order_by()
        .values("item_type__category__category_name")
        .annotate(total=stats[0], average=stats[1], lowest=stats[2], highest=stats[3])
        .order_by("item_type__category__category_name")
    )
    condition_labels = dict(Listing.Condition.choices)
    by_condition = [
        {**row, "label": condition_labels.get(row["condition"], row["condition"])}
        for row in base.order_by()
        .values("condition")
        .annotate(total=stats[0], average=stats[1])
        .order_by("condition")
    ]
    totals = base.aggregate(total=Count("pk"), average=Avg("listing_price"))
    return render(
        request,
        "marketplace/reports.html",
        {
            "by_category": by_category,
            "by_condition": by_condition,
            "total_listings": totals["total"],
            "average_price": totals["average"],
            "query_string": request.GET.urlencode(),
            "generated_at": timezone.localtime(),
        },
    )
