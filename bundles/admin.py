from django.contrib import admin

from .models import Bundle, BundleCategory, BundleItem


@admin.register(Bundle)
class BundleAdmin(admin.ModelAdmin):
    list_display = ("buyer", "space", "selected_tier", "status", "created_at")
    list_filter = ("space", "selected_tier", "status")


@admin.register(BundleCategory)
class BundleCategoryAdmin(admin.ModelAdmin):
    list_display = ("bundle", "item_type")


@admin.register(BundleItem)
class BundleItemAdmin(admin.ModelAdmin):
    list_display = (
        "bundle",
        "listing",
        "item_status",
        "listing_price_snapshot",
        "final_price",
    )
    list_filter = ("item_status",)
