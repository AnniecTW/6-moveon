from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import (
    ItemCategory,
    ItemType,
    Listing,
    PriceRecommendation,
    Transaction,
    User,
)


@admin.register(User)
class MoveOnUserAdmin(UserAdmin):
    readonly_fields = UserAdmin.readonly_fields + ("email_verified", "email_verified_at")
    fieldsets = UserAdmin.fieldsets + (
        (
            "MoveOn profile",
            {"fields": ("email_verified", "email_verified_at", "display_name", "account_status")},
        ),
    )
    # UserAdmin's own add_fieldsets is a *separate* minimal form used only on the
    # "+ Add user" creation page (username/password only). Without extending it too,
    # our required custom fields (email, display_name) would be skippable on creation
    # even though they're required everywhere else.
    add_fieldsets = UserAdmin.add_fieldsets + (
        (
            "MoveOn profile",
            {"fields": ("email", "display_name", "email_verified", "email_verified_at", "account_status")},
        ),
    )
    list_display = ("username", "display_name", "email", "account_status", "is_staff")
    list_filter = ("account_status", "is_staff", "is_superuser", "is_active")


@admin.register(ItemCategory)
class ItemCategoryAdmin(admin.ModelAdmin):
    list_display = ("category_name",)
    search_fields = ("category_name",)


@admin.register(ItemType)
class ItemTypeAdmin(admin.ModelAdmin):
    list_display = ("item_type_name", "category")
    list_filter = ("category",)
    search_fields = ("item_type_name",)


@admin.register(Listing)
class ListingAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "seller",
        "item_type",
        "listing_price",
        "status",
        "bundle_eligible",
        "created_at",
    )
    list_filter = ("status", "condition", "bundle_eligible", "fulfillment_option")
    search_fields = ("title", "description")


@admin.register(PriceRecommendation)
class PriceRecommendationAdmin(admin.ModelAdmin):
    list_display = (
        "listing",
        "previous_price",
        "recommended_price",
        "status",
        "generated_at",
    )
    list_filter = ("status",)


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = (
        "listing",
        "buyer",
        "seller",
        "agreed_price",
        "status",
        "created_at",
    )
    list_filter = ("status",)
