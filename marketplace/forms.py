"""Validated GET parameters shared by every browse view."""
from django import forms
from .models import ItemCategory, ItemType, Listing

SORT_CHOICES = [
    ("newest", "Newest"), ("price-asc", "Price: low to high"),
    ("price-desc", "Price: high to low"), ("popular", "Popular"),
]

class BrowseForm(forms.Form):
    q = forms.CharField(required=False, max_length=200, label="Search")
    category = forms.MultipleChoiceField(required=False, widget=forms.CheckboxSelectMultiple)
    item_type = forms.MultipleChoiceField(required=False, widget=forms.CheckboxSelectMultiple)
    condition = forms.MultipleChoiceField(
        required=False, choices=Listing.Condition.choices, widget=forms.CheckboxSelectMultiple)
    fulfillment = forms.MultipleChoiceField(
        required=False, choices=Listing.Fulfillment.choices, widget=forms.CheckboxSelectMultiple)
    min_price = forms.DecimalField(required=False, min_value=0, max_value=999999.99, decimal_places=2)
    max_price = forms.DecimalField(required=False, min_value=0, max_value=999999.99, decimal_places=2)
    bundle = forms.BooleanField(required=False, label="Bundle eligible only")
    sort = forms.ChoiceField(required=False, choices=SORT_CHOICES)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["category"].choices = list(ItemCategory.objects.values_list("pk", "category_name"))
        types = ItemType.objects.select_related("category")
        self.item_types = list(types)
        self.fields["item_type"].choices = [(str(t.pk), t.item_type_name) for t in self.item_types]
        self.fields["sort"].widget.attrs["form"] = "filter-form"
        for name in ("min_price", "max_price"):
            self.fields[name].widget.attrs.update({"step": "0.01", "placeholder": "Any"})

    def clean(self):
        data = super().clean()
        low, high = data.get("min_price"), data.get("max_price")
        if low is not None and high is not None and low > high:
            self.add_error("max_price", "Maximum price must be at least the minimum price.")
        return data
