"""Database querying and template context; independent of browser scripting."""

from django.db.models import Q, Count
from .auth_backend import has_campus_access
from .featured import decorate_listing, featured_bundles
from .forms import BrowseForm
from .models import Listing

ORDERING = {
    "newest": "-created_at",
    "price-asc": "listing_price",
    "price-desc": "-listing_price",
}


def browse_context(request):
    form = BrowseForm(request.GET)
    listings = Listing.objects.filter(status=Listing.Status.ACTIVE).select_related(
        "seller", "item_type", "item_type__category"
    )
    chips = []
    if form.is_valid():
        values = form.cleaned_data
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
            listings = listings.filter(fulfillment_option__in=fulfillment)
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
    else:
        listings = listings.none()
    return {
        "listings": [decorate_listing(item) for item in listings],
        "filter_form": form,
        "filter_chips": chips,
        "featured_bundles": featured_bundles(),
        "campus_access": request.user.is_authenticated and has_campus_access(request.user),
    }
