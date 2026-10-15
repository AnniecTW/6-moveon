"""Forms used by the marketplace browse and listing workflows."""

from decimal import Decimal

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


class ItemTypeSelect(forms.Select):
    """Expose category IDs to filter the existing item-type control in the UI."""

    def __init__(self, *args, category_ids=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.category_ids = category_ids or {}

    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(name, value, label, selected, index, subindex, attrs)
        category_id = self.category_ids.get(str(value))
        if category_id is not None:
            option["attrs"]["data-category-id"] = category_id
        return option


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
    category = forms.ModelChoiceField(
        queryset=ItemCategory.objects.all(), required=False,
        widget=forms.Select(attrs={"aria-label": "Category"}),
    )
    match_choice = forms.CharField(required=False, widget=forms.HiddenInput)
    pricing_decision = forms.ChoiceField(
        choices=[("EDITED", "Set my price"), ("ACCEPTED", "Use recommendation"),
                 ("DECLINED", "Decline recommendation")],
        required=False, widget=forms.HiddenInput,
    )
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
        self._pricing_original = (
            tuple(getattr(self.instance, field) for field in
                  ("listing_price", "deadline_base_price", "minimum_price", "urgent_minimum_price", "move_out_date", "sell_no_matter_what",
                   "status", "deadline_revision")) if self.instance.pk else None
        )
        self.fields["item_type"].widget = ItemTypeSelect(
            category_ids={str(pk): category_id for pk, category_id in
                          ItemType.objects.values_list("pk", "category_id")}
        )
        self.fields["item_type"].label_from_instance = lambda kind: kind.item_type_name
        self.fields["item_type"].widget.choices = self.fields["item_type"].choices
        if not self.is_bound and self.instance.pk:
            self.initial["category"] = self.instance.item_type.category_id
            self.initial["match_choice"] = self.instance.valuation_metadata.get(
                "semantic_match_choice", "UNREVIEWED"
            )
            self.initial["deadline_base_price"] = (
                self.instance.deadline_base_price or self.instance.deadline_start_price
                or self.instance.listing_price
            )
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
            "category",
            "match_choice",
            "brand",
            "listing_price",
            "condition",
            "item_type",
            "fulfillment_option",
            "fulfillment_pickup",
            "fulfillment_delivery",
            "description",
            "minimum_price",
            "urgent_minimum_price",
            "deadline_base_price",
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
            "urgent_minimum_price": forms.NumberInput(
                attrs={"min": "0.01", "step": "0.01", "placeholder": "Only for Sell no matter what"}
            ),
            "deadline_base_price": forms.NumberInput(
                attrs={"min": "0.01", "step": "0.01", "placeholder": "Original listing price"}
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
        from .pricing.initial import recommend
        from .pricing.semantic import suggestion_source

        item_type = self.cleaned_data.get("item_type")
        if item_type is not None:
            records, profile = suggestion_source()
            result = recommend(
                records, category=item_type.category.category_name,
                item_type=item_type.item_type_name,
                condition=self.cleaned_data.get("condition"),
                brand=self.cleaned_data.get("brand", ""),
            )
            suggested = result["suggested_listing_price"]
            match_choice = self.cleaned_data.get("match_choice", "")
            decision = self.cleaned_data.get("pricing_decision") or "EDITED"
            if suggested is None:
                decision = "ABSTAINED"
            elif decision == "ACCEPTED":
                if listing.minimum_price is not None and suggested < listing.minimum_price:
                    decision = "FLOOR_PROTECTED"
                else:
                    listing.listing_price = suggested
            listing.benchmark_price = result["benchmark_price"]
            listing.benchmark_low = result["range_low"]
            listing.benchmark_high = result["range_high"]
            listing.valuation_metadata = {
                **{key: str(value) if isinstance(value, Decimal) else value
                   for key, value in result.items()},
                "data_version": profile["sha256"],
                "seller_decision": decision,
                "seller_chosen_price": str(listing.listing_price),
                "semantic_match_choice": match_choice or "UNREVIEWED",
            }
        if commit:
            self._save_listing_and_images(listing)
        return listing

    def _save_listing_and_images(self, listing):
        database = database_for(listing)
        image_ids = self.cleaned_data.get("image_ids", [])
        with transaction.atomic(using=database):
            from .pricing.deadline import reset_schedule
            previous = (Listing.objects.using(database).select_for_update().filter(pk=listing.pk).first()
                        if listing.pk else None)
            if previous is not None:
                current = tuple(getattr(previous, field) for field in
                                ("listing_price", "deadline_base_price", "minimum_price", "urgent_minimum_price", "move_out_date", "sell_no_matter_what",
                                 "status", "deadline_revision"))
                if current != self._pricing_original:
                    raise ValidationError("This listing changed while you were editing. Reload it before saving.")
                listing.deadline_revision = previous.deadline_revision
            if listing.deadline_base_price is None:
                listing.deadline_base_price = (
                    previous.deadline_base_price or previous.deadline_start_price or previous.listing_price
                    if previous else listing.listing_price
                )
            changed = previous is not None and any(
                getattr(previous, field) != getattr(listing, field)
                for field in ("listing_price", "deadline_base_price", "minimum_price", "urgent_minimum_price", "move_out_date", "sell_no_matter_what")
            )
            publishing = previous is not None and previous.status == Listing.Status.DRAFT and listing.status == Listing.Status.ACTIVE
            active_schedule = (previous is not None and previous.deadline_start_date is not None
                               and listing.status == Listing.Status.ACTIVE)
            resume_unscheduled = (previous is not None and previous.status == Listing.Status.ACTIVE
                                  and listing.status == Listing.Status.ACTIVE
                                  and previous.deadline_start_date is None)
            restart = (publishing or (listing.status == Listing.Status.ACTIVE and changed)
                       or resume_unscheduled)
            # Editing an active plan recalculates its curve without replacing
            # the original starting price with the current asking price.
            if restart or changed or (previous is not None and previous.status == Listing.Status.ACTIVE and listing.status != Listing.Status.ACTIVE):
                reset_schedule(listing, start=bool(restart),
                               baseline=previous if active_schedule else None)
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
            if restart and listing.deadline_start_date is not None:
                from .pricing.deadline import evaluate_listing, notify_trigger
                recommendation = evaluate_listing(listing.pk)
                if recommendation is not None:
                    notify_trigger(listing.pk, recommendation.pk)

    def clean(self):
        cleaned_data = super().clean()
        category = cleaned_data.get("category")
        item_type = cleaned_data.get("item_type")
        if category and item_type and category.pk != item_type.category_id:
            self.add_error("item_type", "Choose an item type in the selected category.")
        match_choice = cleaned_data.get("match_choice", "")
        if match_choice and match_choice not in ("NONE", "UNREVIEWED", f"TYPE:{getattr(item_type, 'pk', '')}"):
            self.add_error("match_choice", "Choose a valid item-type suggestion.")
        price = cleaned_data.get("listing_price")
        floor = cleaned_data.get("minimum_price")
        urgent_floor = cleaned_data.get("urgent_minimum_price")
        entered_base = cleaned_data.get("deadline_base_price")
        if entered_base is not None and entered_base <= 0:
            self.add_error("deadline_base_price", "Enter a positive markdown base price.")
        base = (cleaned_data.get("deadline_base_price") or self.instance.deadline_base_price
                or self.instance.deadline_start_price
                or (self.instance.listing_price if self.instance.pk else price))
        if base is not None and floor is not None and floor > base:
            self.add_error("deadline_base_price", "Markdown base price must be at least your Minimum Price.")
        if urgent_floor is not None and (urgent_floor <= 0 or floor is not None and urgent_floor > floor):
            self.add_error("urgent_minimum_price", "Enter a positive urgent minimum no higher than your normal minimum.")
        if cleaned_data.get("sell_no_matter_what") and urgent_floor is None:
            self.add_error("urgent_minimum_price", "Choose the lowest price you would accept for Sell no matter what.")
        if cleaned_data.get("sell_no_matter_what") and floor is None:
            self.add_error("minimum_price", "Set your normal minimum before enabling Sell no matter what.")
        if price is not None and floor is not None and floor > price:
            existing_below_floor_unchanged = (
                self.instance.pk
                and self.instance.minimum_price == floor
                and self.instance.listing_price == price
            )
            if not existing_below_floor_unchanged:
                self.add_error("minimum_price", "Minimum price cannot exceed your listing price.")
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
