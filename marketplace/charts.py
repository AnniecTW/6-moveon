"""The profile's existing inquiry chart, aggregated and rendered on the server."""

from io import BytesIO
from threading import Lock
from textwrap import fill

from django.contrib.auth.decorators import login_required
from django.db.models import Count, F, Q
from django.http import HttpResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from matplotlib.ticker import MaxNLocator

from .models import Listing

_render_lock = Lock()  # Matplotlib rendering is not thread-safe.


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


@login_required
@require_GET
@never_cache
def listing_inquiry_chart(request):
    """Private PNG endpoint; no user ID parameter and no generated image on disk."""
    rows = listing_inquiry_data(request.user)
    with _render_lock:
        figure = Figure(figsize=(10, max(2.6, 1.4 + len(rows) * .55)), dpi=120,
                        facecolor="#ffffff", layout="constrained")
        try:
            axes = figure.subplots()
            positions = list(range(len(rows)))
            answered = [row["answered"] for row in rows]
            axes.barh(positions, answered, color="#678675", label="Awaiting Response")
            axes.barh(positions, [row["unanswered"] for row in rows], left=answered,
                      color="#d8ad8d", label="Unanswered")
            axes.set_yticks(positions, [fill(row["title"], 30) for row in rows])
            axes.invert_yaxis()
            axes.set_xlabel("Conversations")
            axes.set_ylabel("Listing")
            axes.xaxis.set_major_locator(MaxNLocator(integer=True))
            axes.set_xlim(0, max((row["total"] for row in rows), default=1) * 1.15)
            for index, row in enumerate(rows):
                axes.text(row["total"] + .02, index, str(row["total"]), va="center")
            if not rows:
                axes.text(.5, .5, "No inquiries for your listings yet.",
                          ha="center", va="center", transform=axes.transAxes)
            axes.spines[["top", "right"]].set_visible(False)
            axes.legend(loc="upper center", bbox_to_anchor=(.5, -.24), ncols=2, frameon=False)
            with BytesIO() as buffer:
                FigureCanvasAgg(figure).print_png(buffer)
                return HttpResponse(buffer.getvalue(), content_type="image/png")
        finally:
            figure.clear()
