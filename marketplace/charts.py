"""Private chart data and Vega-Lite specs for the profile dashboard."""

import json
import subprocess
import sys
from decimal import Decimal
from functools import wraps
from urllib.parse import urlencode

from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core import signing
from django.db.models import Count, F, Q, Sum
from django.http import HttpResponse, JsonResponse
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from .auth_backend import has_campus_access
from .models import Listing, Transaction

_RENDER_TOKEN_SALT = "profile-chart-render"
_RENDER_SCRIPT = (
    "import json,sys,vl_convert as vlc; "
    "spec=json.load(sys.stdin); "
    "sys.stdout.buffer.write(vlc.vegalite_to_png(" 
    "vl_spec=spec,allowed_base_urls=[sys.argv[1]]))"
)


def chart_data_access_required(view):
    """Allow the owner session or a short-lived token issued by a PNG view."""
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        user = request.user
        if not (user.is_authenticated and has_campus_access(user)):
            try:
                payload = signing.loads(
                    request.GET.get("render_token", ""),
                    salt=_RENDER_TOKEN_SALT,
                    max_age=60,
                )
            except signing.BadSignature:
                return JsonResponse({"error": "Chart access denied."}, status=403)
            if not isinstance(payload, dict):
                return JsonResponse({"error": "Chart access denied."}, status=403)
            user = get_user_model().objects.filter(
                pk=payload.get("user_id"),
                is_active=True,
                account_status="ACTIVE",
                email_verified=True,
                email_verified_at__isnull=False,
                email__iendswith="@illinois.edu",
            ).first()
            if user is None:
                return JsonResponse({"error": "Chart access denied."}, status=403)
        request.chart_user = user
        return view(request, *args, **kwargs)
    return wrapped


def _render_png(request, spec_view, data_route):
    spec_response = spec_view(request)
    spec = json.loads(spec_response.content)
    token = signing.dumps({"user_id": request.user.pk}, salt=_RENDER_TOKEN_SALT)
    data_url = request.build_absolute_uri(reverse(data_route))
    spec["data"]["url"] = f"{data_url}?{urlencode({'render_token': token})}"
    try:
        result = subprocess.run(
            [sys.executable, "-c", _RENDER_SCRIPT, request.build_absolute_uri("/")],
            input=json.dumps(spec).encode("utf-8"),
            capture_output=True,
            check=True,
            timeout=30,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return JsonResponse({"error": "Chart rendering failed."}, status=502)
    return HttpResponse(result.stdout, content_type="image/png")


def listing_inquiry_data(user):
    """Count each conversation once, even when it contains many unread messages."""
    unread = Q(conversations__messages__isnull=True) | Q(
        conversations__messages__sender_id=F("conversations__buyer_id"),
        conversations__messages__is_read=False,
    )
    rows = list(
        Listing.objects.filter(seller=user)
        .exclude(status=Listing.Status.SOLD)
        .annotate(
            total=Count("conversations", distinct=True),
            unanswered=Count("conversations", filter=unread, distinct=True),
        )
        .filter(total__gt=0)
        .order_by("-total", "title", "pk")
        .values("title", "total", "unanswered")[:6]
    )
    maximum = max((row["total"] for row in rows), default=1)
    for row in rows:
        row["answered"] = row["total"] - row["unanswered"]
        row["total_percent"] = round(row["total"] / maximum * 100)
        row["answered_percent"] = round(row["answered"] / row["total"] * 100)
        row["unanswered_percent"] = 100 - row["answered_percent"]
    return rows


@chart_data_access_required
@require_GET
@never_cache
def earned_spent_data(request):
    user = request.chart_user
    purchases = Transaction.objects.filter(buyer=user).exclude(
        status=Transaction.Status.CANCELLED
    )
    sales = Transaction.objects.filter(
        seller=user, status=Transaction.Status.COMPLETED
    )
    spent = purchases.aggregate(total=Sum("agreed_price"))["total"] or Decimal("0")
    earned = sales.aggregate(total=Sum("agreed_price"))["total"] or Decimal("0")
    return JsonResponse([
        {"activity": "Total Spent", "amount": float(spent)},
        {"activity": "Total Earned", "amount": float(earned)},
    ], safe=False)


@chart_data_access_required
@require_GET
@never_cache
def earned_spent_timeline_data(request):
    user = request.chart_user
    transactions = list(
        Transaction.objects.filter(
            Q(buyer=user) & ~Q(status=Transaction.Status.CANCELLED)
            | Q(seller=user, status=Transaction.Status.COMPLETED)
        ).order_by("completed_at", "created_at", "pk")
    )
    by_date = {}
    for item in transactions:
        happened_at = item.completed_at or item.created_at
        day = happened_at.date().isoformat()
        totals = by_date.setdefault(day, {
            "Total Spent": Decimal("0"),
            "Total Earned": Decimal("0"),
        })
        if item.buyer_id == user.pk:
            totals["Total Spent"] += item.agreed_price
        if (
            item.seller_id == user.pk
            and item.status == Transaction.Status.COMPLETED
        ):
            totals["Total Earned"] += item.agreed_price

    cumulative = {"Total Spent": Decimal("0"), "Total Earned": Decimal("0")}
    rows = []
    for day in sorted(by_date):
        for activity in cumulative:
            cumulative[activity] += by_date[day][activity]
            rows.append({
                "date": day,
                "activity": activity,
                "amount": float(cumulative[activity]),
            })
    return JsonResponse(rows, safe=False)


@chart_data_access_required
@require_GET
@never_cache
def listing_inquiry_chart_data(request):
    return JsonResponse(listing_inquiry_data(request.chart_user), safe=False)


@login_required
@require_GET
@never_cache
def earned_spent_spec(request):
    return JsonResponse({
        "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
        "data": {"url": request.build_absolute_uri(reverse("profile-earned-spent-data"))},
        "mark": {"type": "bar", "cornerRadiusEnd": 3},
        "encoding": {
            "x": {
                "field": "amount",
                "type": "quantitative",
                "title": "Amount ($)",
                "scale": {"zero": True},
                "axis": {"grid": False, "tickMinStep": 10},
            },
            "y": {
                "field": "activity",
                "type": "nominal",
                "title": None,
                "axis": {"grid": False},
            },
            "color": {
                "field": "activity",
                "type": "nominal",
                "scale": {
                    "domain": ["Total Spent", "Total Earned"],
                    "range": ["#85877f", "#4d8069"],
                },
                "legend": None,
            },
            "tooltip": [
                {"field": "activity", "type": "nominal", "title": "Activity"},
                {"field": "amount", "type": "quantitative", "format": "$,.2f"},
            ],
        },
        "width": "container",
        "height": 240,
        "autosize": {"type": "fit", "contains": "padding"},
    })


@login_required
@require_GET
@never_cache
def earned_spent_timeline_spec(request):
    return JsonResponse({
        "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
        "data": {
            "url": request.build_absolute_uri(
                reverse("profile-earned-spent-timeline-data")
            )
        },
        "mark": {"type": "line", "point": True, "strokeWidth": 3},
        "encoding": {
            "x": {
                "field": "date",
                "type": "temporal",
                "title": "Date",
                "axis": {"grid": False},
            },
            "y": {
                "field": "amount",
                "type": "quantitative",
                "title": "Cumulative amount ($)",
                "axis": {"grid": False, "format": "$,.0f"},
            },
            "color": {
                "field": "activity",
                "type": "nominal",
                "title": "Activity",
                "scale": {
                    "domain": ["Total Spent", "Total Earned"],
                    "range": ["#85877f", "#4d8069"],
                },
                "legend": {"orient": "top"},
            },
            "tooltip": [
                {"field": "date", "type": "temporal", "title": "Date"},
                {"field": "activity", "type": "nominal", "title": "Activity"},
                {
                    "field": "amount",
                    "type": "quantitative",
                    "title": "Cumulative total",
                    "format": "$,.2f",
                },
            ],
        },
        "width": "container",
        "height": 180,
        "autosize": {"type": "fit", "contains": "padding"},
    })


@login_required
@require_GET
@never_cache
def listing_inquiry_spec(request):
    return JsonResponse({
        "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
        "data": {"url": request.build_absolute_uri(reverse("profile-listing-inquiry-data"))},
        "transform": [{"fold": ["answered", "unanswered"], "as": ["response", "inquiries"]}],
        "mark": {"type": "bar", "cornerRadiusEnd": 3},
        "encoding": {
            "x": {
                "field": "inquiries",
                "type": "quantitative",
                "title": "Inquiries",
                "scale": {"zero": True},
                "stack": "zero",
                "axis": {"grid": False, "format": "d", "tickMinStep": 1},
            },
            "y": {
                "field": "title",
                "type": "nominal",
                "title": "Listing",
                "sort": {"field": "total", "op": "max", "order": "descending"},
                "axis": {"grid": False},
            },
            "color": {
                "field": "response",
                "type": "nominal",
                "title": "Response",
                "scale": {
                    "domain": ["answered", "unanswered"],
                    "range": ["#4d8069", "#c75b5b"],
                },
            },
            "order": {"field": "response", "sort": ["answered", "unanswered"]},
            "tooltip": [
                {"field": "title", "type": "nominal", "title": "Listing"},
                {"field": "total", "type": "quantitative", "title": "Total inquiries"},
                {"field": "response", "type": "nominal", "title": "Response"},
                {"field": "inquiries", "type": "quantitative", "title": "Count"},
            ],
        },
        "width": "container",
        "height": 280,
        "autosize": {"type": "fit", "contains": "padding"},
    })


@login_required
@require_GET
@never_cache
def earned_spent_png(request):
    return _render_png(
        request, earned_spent_spec, "profile-earned-spent-data"
    )


@login_required
@require_GET
@never_cache
def earned_spent_timeline_png(request):
    return _render_png(
        request,
        earned_spent_timeline_spec,
        "profile-earned-spent-timeline-data",
    )


@login_required
@require_GET
@never_cache
def listing_inquiry_png(request):
    return _render_png(
        request, listing_inquiry_spec, "profile-listing-inquiry-data"
    )
