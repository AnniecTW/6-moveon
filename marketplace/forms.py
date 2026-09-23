"""Forms used by the marketplace browse and listing workflows."""

from django import forms
from .models import ItemCategory, ItemType, Listing

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


class ListingCreateForm(forms.ModelForm):
    """Validate the seller-facing fields used to create a listing."""

    title = forms.CharField(max_length=80)
    fulfillment_option = forms.CharField(
        required=False,
        widget=forms.HiddenInput,
    )
    fulfillment_pickup = forms.BooleanField(label="Pickup", required=False)
    fulfillment_delivery = forms.BooleanField(label="Delivery", required=False)
    description = forms.CharField(
        max_length=1000,
        required=False,
        widget=forms.Textarea(attrs={"rows": 5}),
    )

    class Meta:
        model = Listing
        fields = [
            "image_url",
            "title",
            "listing_price",
            "condition",
            "item_type",
            "fulfillment_option",
            "fulfillment_pickup",
            "fulfillment_delivery",
            "description",
            "minimum_price",
            "move_out_date",
            "bundle_eligible",
            "sell_no_matter_what",
        ]
        widgets = {
            "image_url": forms.URLInput(
                attrs={"placeholder": "Paste a photo URL", "type": "url"}
            ),
            "listing_price": forms.NumberInput(
                attrs={"min": "0", "step": "0.01", "placeholder": "Enter your price"}
            ),
            "minimum_price": forms.NumberInput(
                attrs={"min": "0", "step": "0.01", "placeholder": "Enter minimum price"}
            ),
            "move_out_date": forms.DateInput(attrs={"type": "date"}),
        }

    def clean(self):
        cleaned_data = super().clean()
        pickup = cleaned_data.get("fulfillment_pickup")
        delivery = cleaned_data.get("fulfillment_delivery")

        if not pickup and not delivery:
            raise forms.ValidationError(
                "Select pickup, delivery, or both fulfillment options."
            )
        if pickup and delivery:
            cleaned_data["fulfillment_option"] = Listing.Fulfillment.BOTH
        elif pickup:
            cleaned_data["fulfillment_option"] = Listing.Fulfillment.PICKUP
        else:
            cleaned_data["fulfillment_option"] = Listing.Fulfillment.DELIVERY
        return cleaned_data
