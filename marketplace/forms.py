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


class ListingCreateForm(forms.ModelForm):
    """Validate the seller-facing fields used to create a listing."""

    title = forms.CharField(max_length=80)
    image_ids = forms.CharField(required=False, widget=forms.HiddenInput)
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

    def __init__(self, *args, user=None, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)
        if not self.is_bound and self.instance.pk:
            database = database_for(self.instance)
            image_ids = ListingImage.objects.using(database).filter(
                listing_id=self.instance.pk
            ).values_list("pk", flat=True)
            self.initial["image_ids"] = ",".join(str(image_id) for image_id in image_ids)

    class Meta:
        model = Listing
        fields = [
            "image_ids",
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
            "listing_price": forms.NumberInput(
                attrs={"min": "0", "step": "0.01", "placeholder": "Enter your price"}
            ),
            "minimum_price": forms.NumberInput(
                attrs={"min": "0", "step": "0.01", "placeholder": "Enter minimum price"}
            ),
            "move_out_date": forms.DateInput(attrs={"type": "date"}),
        }

    def clean_image_ids(self):
        raw_value = self.cleaned_data.get("image_ids", "")
        image_ids = []
        for raw_id in str(raw_value).split(","):
            raw_id = raw_id.strip()
            if not raw_id:
                continue
            try:
                image_id = int(raw_id)
            except (TypeError, ValueError):
                raise ValidationError("Choose valid uploaded images.")
            if image_id in image_ids:
                raise ValidationError("Each uploaded image can only be selected once.")
            image_ids.append(image_id)

        if len(image_ids) > Listing.MAX_IMAGES:
            raise ValidationError(
                f"A listing can have at most {Listing.MAX_IMAGES} images."
            )
        if not image_ids:
            return []
        if self.user is None or not getattr(self.user, "is_authenticated", False):
            raise ValidationError("You must be signed in to select uploaded images.")

        database = database_for(self.instance)
        images = ListingImage.objects.using(database).filter(pk__in=image_ids)
        by_id = {image.pk: image for image in images}
        if len(by_id) != len(image_ids):
            raise ValidationError("One or more selected images are unavailable.")
        for image_id in image_ids:
            image = by_id[image_id]
            if image.uploaded_by_id != self.user.pk:
                raise ValidationError("You can only use images you uploaded.")
            if image.listing_id not in (None, self.instance.pk):
                raise ValidationError("One or more selected images belong to another listing.")
        return image_ids

    def selected_images_for_display(self):
        """Return selected photos in the order submitted or initialized."""
        if self.is_bound:
            raw_value = self.data.get(self.add_prefix("image_ids"), "")
        else:
            raw_value = self.initial.get("image_ids", "")
        image_ids = []
        for raw_id in str(raw_value).split(","):
            try:
                image_id = int(raw_id.strip())
            except (TypeError, ValueError):
                continue
            if image_id > 0 and image_id not in image_ids:
                image_ids.append(image_id)
        if not image_ids:
            return []

        database = database_for(self.instance)
        image_query = ListingImage.objects.using(database).filter(
            pk__in=image_ids,
            uploaded_by_id=getattr(self.user, "pk", None),
        )
        if self.instance.pk:
            image_query = image_query.filter(
                Q(listing_id__isnull=True) | Q(listing_id=self.instance.pk)
            )
        else:
            image_query = image_query.filter(listing_id__isnull=True)
        by_id = {image.pk: image for image in image_query}
        return [
            {"id": image_id, "url": by_id[image_id].url}
            for image_id in image_ids
            if image_id in by_id
        ]

    def save(self, commit=True):
        listing = super().save(commit=False)
        if commit:
            self._save_listing_and_images(listing)
        return listing

    def _save_listing_and_images(self, listing):
        database = database_for(listing)
        image_ids = self.cleaned_data.get("image_ids", [])
        with transaction.atomic(using=database):
            listing.save(using=database)
            selected_images = list(
                ListingImage.objects.using(database)
                .select_for_update()
                .filter(pk__in=image_ids)
            )
            by_id = {image.pk: image for image in selected_images}
            if len(by_id) != len(image_ids):
                raise ValidationError("One or more selected images are unavailable.")

            ListingImage.objects.using(database).filter(
                listing_id=listing.pk
            ).exclude(pk__in=image_ids).delete()
            for position, image_id in enumerate(image_ids):
                image = by_id[image_id]
                image.listing_id = listing.pk
                image.position = position
                image.save(using=database, update_fields={"listing", "position"})

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


class SellerSettingsForm(forms.Form):
    """Display-only seller preferences; persistence is not implemented."""

    PAYMENT_CHOICES = [
        ("", ""),
        ("meetup", "Arrange payment at meet-up"),
        ("external", "External payment app (not connected)"),
    ]
    DELIVERY_CHOICES = [
        ("", ""),
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
