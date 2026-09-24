"""Read-only public listing data, using the same filters as marketplace browsing."""

import json

from django.core.paginator import EmptyPage, Paginator
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET

from .browse import filtered_listings
from .forms import BrowseForm


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
