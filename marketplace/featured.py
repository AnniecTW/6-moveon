"""Editorial scene coordinates and demo identity; all displayed prices come from Listings."""

from decimal import Decimal, ROUND_HALF_UP
from django.templatetags.static import static
from .models import Listing
from .scene_contours import contour_geometry

DEMO_USERNAME = "moveon-featured-demo"
SCENES = [
    {
        "slug": "living-room",
        "title": "Living Room Starter Bundle",
        "image": "living-room-clean.png",
        "alt": "Living room with rocking chair, coffee table and throw pillow",
        "items": [
            {
                "title": "Rocking Chair",
                "asset": "rocking-chair.png",
                "type": "Chair",
                "original": "140",
                "price": "95",
            },
            {
                "title": "Coffee Table",
                "asset": "coffee-table.png",
                "type": "Table",
                "original": "55",
                "price": "40",
            },
            {
                "title": "Throw Pillow",
                "asset": "gray-pillow.png",
                "type": "Pillow",
                "original": "18",
                "price": "12",
            },
        ],
    },
    {
        "slug": "study-nook",
        "title": "Study Nook Bundle",
        "image": "study-bundle.png",
        "alt": "Study nook with oak desk, brass lamp and bookshelf",
        "items": [
            {
                "title": "Oak Desk",
                "asset": "oak-desk.png",
                "type": "Desk",
                "original": "90",
                "price": "60",
            },
            {
                "title": "Desk Lamp",
                "asset": "desk-lamp.png",
                "type": "Lamp",
                "original": "34",
                "price": "22",
            },
            {
                "title": "Bookshelf",
                "asset": "bookshelf.png",
                "type": "Bookshelf",
                "original": "68",
                "price": "45",
            },
        ],
    },
]
ASSETS = {spec["title"]: spec["asset"] for scene in SCENES for spec in scene["items"]}


def discount_percent(original, sale):
    if original is None or original <= 0 or sale >= original:
        return None
    return ((original - sale) / original * 100).quantize(
        Decimal("0.1"), rounding=ROUND_HALF_UP
    )


def decorate_listing(item):
    item.display_image_url = item.cover_image_url
    if (
        not item.display_image_url
        and item.seller.username == DEMO_USERNAME
        and item.title in ASSETS
    ):
        item.display_image_url = static("img/reference/" + ASSETS[item.title])
    item.discount_percent = discount_percent(item.retail_price, item.listing_price)
    return item


def featured_bundles():
    listings = Listing.objects.filter(
        seller__username=DEMO_USERNAME,
        title__in=ASSETS,
        status=Listing.Status.ACTIVE,
        bundle_eligible=True,
    ).select_related("seller", "item_type", "item_type__category")
    listings = listings.prefetch_related("images")
    by_title = {item.title: decorate_listing(item) for item in listings}
    bundles = []
    for scene in SCENES:
        # Never advertise a complete bundle if one of its items is unavailable.
        if not all(spec["title"] in by_title for spec in scene["items"]):
            continue
        items = [
            {
                **spec,
                **contour_geometry(spec["asset"]),
                "listing": by_title[spec["title"]],
            }
            for spec in scene["items"]
        ]
        total = sum((item["listing"].listing_price for item in items), Decimal("0"))
        originals = [item["listing"].retail_price for item in items]
        original = (
            sum(originals, Decimal("0"))
            if all(v is not None for v in originals)
            else None
        )
        saved = max(original - total, Decimal("0")) if original is not None else None
        bundles.append(
            {
                **scene,
                "items": items,
                "total": total,
                "original": original,
                "saved": saved,
                "discount": discount_percent(original, total),
            }
        )
    return bundles
