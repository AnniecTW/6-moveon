"""Read-only public listing data, using the same filters as marketplace browsing."""

import json
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from django.core.paginator import EmptyPage, Paginator
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET
import requests

from .browse import filtered_listings
from .forms import BrowseForm

SUPPORTED_CURRENCIES = {"USD", "CAD", "EUR", "GBP"}
FRANKFURTER_RATES_URL = "https://api.frankfurter.dev/v2/rates"


def _display_amount(amount, rate):
    if amount is None:
        return None
    return str((amount * rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


@require_GET
def listings(request):
    form = BrowseForm(request.GET)
    if not form.is_valid():
        return JsonResponse({"error": "Invalid filters.", "fields": form.errors.get_json_data()}, status=400)
    try:
        number = int(request.GET.get("page", "1"))
        if number < 1:
            raise ValueError
    except ValueError:
        return JsonResponse({"error": "Page must be a positive integer."}, status=400)
    paginator = Paginator(filtered_listings(form), 20)
    try:
        page = paginator.page(number)
    except EmptyPage:
        return JsonResponse({"error": "Page not found."}, status=404)
    return JsonResponse({
        "count": paginator.count,
        "page": page.number,
        "pages": paginator.num_pages,
        "results": [{
            "id": item.pk,
            "listing_id": str(item.listing_id),
            "title": item.title,
            "price": str(item.listing_price),
            "condition": item.condition,
            "category": {"id": item.item_type.category_id, "name": item.item_type.category.category_name},
            "url": request.build_absolute_uri(item.get_absolute_url()),
        } for item in page],
    }, json_dumps_params={"indent": 2})


@require_GET
def converted_listings(request):
    """Return currently browsable listings with prices converted from USD."""
    currency = request.GET.get("currency", "USD").upper()
    if currency not in SUPPORTED_CURRENCIES:
        return JsonResponse({"error": "Unsupported currency."}, status=400)

    form = BrowseForm(request.GET)
    if not form.is_valid():
        return JsonResponse(
            {"error": "Invalid filters.", "fields": form.errors.get_json_data()},
            status=400,
        )
    listings = list(filtered_listings(form))

    rate = Decimal("1")
    rate_date = None
    if currency != "USD" and listings:
        try:
            response = requests.get(
                FRANKFURTER_RATES_URL,
                params={"base": "USD", "quotes": currency},
                timeout=5,
            )
            response.raise_for_status()
            rate_rows = response.json()
            rate_row = next(
                (
                    row for row in rate_rows
                    if isinstance(row, dict)
                    and row.get("base") == "USD"
                    and row.get("quote") == currency
                ),
                None,
            ) if isinstance(rate_rows, list) else None
            if rate_row is None:
                raise ValueError("Exchange rate missing from response.")
            rate = Decimal(str(rate_row["rate"]))
            rate_date = rate_row["date"]
            if not rate.is_finite() or rate <= 0:
                raise ValueError("Exchange rate is invalid.")
        except requests.Timeout:
            return JsonResponse(
                {"error": "Exchange rate service timed out."}, status=504
            )
        except (
            requests.RequestException,
            InvalidOperation,
            KeyError,
            TypeError,
            ValueError,
        ):
            return JsonResponse(
                {"error": "Exchange rate service is unavailable."}, status=502
            )

    return JsonResponse({
        "base_currency": "USD",
        "currency": currency,
        "rate": str(rate),
        "rate_date": rate_date,
        "results": [
            {
                "id": item.pk,
                "listing_price": _display_amount(item.listing_price, rate),
                "retail_price": _display_amount(item.retail_price, rate),
            }
            for item in listings
        ],
    })


@require_GET
def listings_documentation(request):
    """Small readable example page that displays the public endpoint response."""
    response = listings(request)
    try:
        payload = json.loads(response.content)
    except (ValueError, UnicodeDecodeError):
        payload = {}
    return render(request, "marketplace/listing_api.html", {
        "query": request.GET.get("q", ""),
        "category": request.GET.get("category", ""),
        "json_response": json.dumps(payload, ensure_ascii=False, indent=2),
        "json_status": response.status_code,
        "json_content_type": response["Content-Type"],
    }, status=response.status_code)
