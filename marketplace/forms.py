"""Forms used by the marketplace browse and listing workflows."""

from django import forms
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q

from .models import ItemCategory, ItemType, Listing, ListingImage
from .validation import database_for

SORT_CHOICES = [
    ("newest", "Newest"),
    ("price-asc", "Price: low to high"),
    ("price-desc", "Price: high to low"),
    ("popular", "Popular"),
]

FULFILLMENT_FILTER_CHOICES = [
    (Listing.Fulfillment.PICKUP, Listing.Fulfillment.PICKUP.label),
    (Listing.Fulfillment.DELIVERY, Listing.Fulfillment.DELIVERY.label),
]


class BrowseForm(forms.Form):
    q = forms.CharField(required=False, max_length=200, label="Search")
    category = forms.MultipleChoiceField(
        required=False, widget=forms.CheckboxSelectMultiple
    )
    item_type = forms.MultipleChoiceField(
        required=False, widget=forms.CheckboxSelectMultiple
    )
    condition = forms.MultipleChoiceField(
        required=False,
        choices=Listing.Condition.choices,
        widget=forms.CheckboxSelectMultiple,
    )
    fulfillment = forms.MultipleChoiceField(
        required=False,
        choices=FULFILLMENT_FILTER_CHOICES,
        widget=forms.CheckboxSelectMultiple,
    )
    min_price = forms.DecimalField(
        required=False, min_value=0, max_value=999999.99, decimal_places=2
    )
    max_price = forms.DecimalField(
        required=False, min_value=0, max_value=999999.99, decimal_places=2
    )
    bundle = forms.BooleanField(required=False, label="Bundle eligible only")
    sort = forms.ChoiceField(required=False, choices=SORT_CHOICES)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["category"].choices = list(
            ItemCategory.objects.values_list("pk", "category_name")
        )
        types = ItemType.objects.select_related("category")
        self.item_types = list(types)
        self.fields["item_type"].choices = [
            (str(t.pk), t.item_type_name) for t in self.item_types
        ]
        self.fields["sort"].widget.attrs["form"] = "filter-form"
        for name in ("min_price", "max_price"):
            self.fields[name].widget.attrs.update(
                {"step": "0.01", "placeholder": "Any"}
            )

    def clean(self):
        data = super().clean()
        low, high = data.get("min_price"), data.get("max_price")
        if low is not None and high is not None and low > high:
            self.add_error(
                "max_price", "Maximum price must be at least the minimum price."
            )
        return data




class SellerSettingsForm(forms.Form):
    """Session-backed seller preferences until a profile model is introduced."""

    PAYMENT_CHOICES = [
        ("meetup", "Arrange payment at meet-up"),
        ("external", "External payment app (not connected)"),
    ]
    DELIVERY_CHOICES = [
        ("pickup", "Pickup only"),
        ("local", "Local delivery available"),
        ("either", "Pickup or local delivery"),
    ]

    payment_preference = forms.ChoiceField(choices=PAYMENT_CHOICES)
    primary_meetup = forms.CharField(max_length=120, required=False)
    alternate_meetup = forms.CharField(max_length=120, required=False)
    delivery_preference = forms.ChoiceField(choices=DELIVERY_CHOICES)
    delivery_notes = forms.CharField(max_length=240, required=False)
    notify_inquiries = forms.BooleanField(required=False)
    notify_bundles = forms.BooleanField(required=False)
    notify_pricing = forms.BooleanField(required=False)
    notify_moveout = forms.BooleanField(required=False)
    notify_transactions = forms.BooleanField(required=False)

    def clean(self):
        data = super().clean()
        if data.get("delivery_preference") != "pickup" and not data.get(
            "delivery_notes"
        ):
            self.add_error(
                "delivery_notes",
                "Add a short delivery area or availability note.",
            )
        return data
