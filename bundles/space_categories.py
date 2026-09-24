"""
Hardcoded Space -> ItemType-name mapping for the Move-In Bundle wizard's
category-selection step.

Per the Part-4 data-modeling handoff doc, a separate SpaceCategoryReference
table is intentionally not built - a plain Python mapping is enough, and it
keeps this list easy to read and edit as the product's taxonomy evolves.
"""

from marketplace.models import ItemType, Listing
from .models import Bundle

SPACE_ITEM_TYPES = {
    Bundle.Space.LIVING_ROOM: [
        "Sofa",
        "Television",
        "Rug",
        "Curtains",
        "Coffee Table",
        "Lamp",
        "Shelf",
        "Decor",
    ],
    Bundle.Space.BEDROOM: [
        "Dresser",
        "Lamp",
        "Rug",
        "Curtains",
        "Shelf",
        "Decor",
    ],
    Bundle.Space.KITCHEN: [
        "Microwave",
        "Shelf",
    ],
    Bundle.Space.BATHROOM: [
        "Shelf",
        "Decor",
    ],
    Bundle.Space.ENTIRE_HOUSE: [
        "Sofa",
        "Desk",
        "Chair",
        "Dresser",
        "Television",
        "Rug",
        "Curtains",
        "Coffee Table",
        "Lamp",
        "Shelf",
        "Decor",
        "Microwave",
    ],
    Bundle.Space.ASSORTED: [
        "Sofa",
        "Desk",
        "Chair",
        "Dresser",
        "Television",
        "Monitor",
        "Speaker",
        "Rug",
        "Curtains",
        "Coffee Table",
        "Lamp",
        "Shelf",
        "Decor",
        "Microwave",
    ],
}


def available_item_types_for_space(space):
    """
    Returns [(ItemType, is_available)] for the ItemType names mapped to
    `space`, in SPACE_ITEM_TYPES order. is_available is computed live from
    current inventory (status=ACTIVE, bundle_eligible=True) rather than
    stored, so it always reflects what a buyer could actually get right now.
    Item type names with no matching ItemType row yet are skipped.
    """
    type_names = SPACE_ITEM_TYPES.get(space, [])
    item_types = ItemType.objects.filter(item_type_name__in=type_names).select_related(
        "category"
    )
    by_name = {item_type.item_type_name: item_type for item_type in item_types}

    results = []
    for name in type_names:
        item_type = by_name.get(name)
        if item_type is None:
            continue
        is_available = Listing.objects.filter(
            item_type=item_type,
            status=Listing.Status.ACTIVE,
            bundle_eligible=True,
        ).exists()
        results.append((item_type, is_available))
    return results
