from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import (
    AISearchLog,
    ItemCategory,
    ItemType,
    Listing,
    ListingImage,
    PriceRecommendation,
    Transaction,
    User,
    WatchlistItem,
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
    readonly_fields = ("views",)
    class ListingImageInline(admin.TabularInline):
        model = ListingImage
        extra = 0
        readonly_fields = ("url",)
        fields = ("image", "external_url", "position", "uploaded_by", "url")

    list_display = (
        "title",
        "views",
        "seller",
        "item_type",
        "listing_price",
        "status",
        "bundle_eligible",
        "created_at",
    )
    list_filter = ("status", "condition", "bundle_eligible", "fulfillment_option")
    search_fields = ("title", "description")
    inlines = (ListingImageInline,)


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


@admin.register(WatchlistItem)
class WatchlistItemAdmin(admin.ModelAdmin):
    list_display = ("user", "listing", "created_at")
    search_fields = ("user__username", "listing__title")


@admin.register(AISearchLog)
class AISearchLogAdmin(admin.ModelAdmin):
    """Read-only: logs are evidence for the analytics dashboard, not editable data."""

    list_display = ("created_at", "mode", "query", "state", "result_count", "total_ms",
                    "llm_model", "llm_error", "embedding_error", "is_simulated")
    list_filter = ("mode", "state", "is_simulated", "llm_error", "embedding_error")
    search_fields = ("query",)
    date_hierarchy = "created_at"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
