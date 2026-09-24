from django.urls import path

from marketplace import views
from marketplace.views import (
    ListingCreateView,
    ListingDetailView,
    ListingListView,
    ListingPreviewView,
    ListingUpdateView,
    listing_image_upload,
    listing_publish,
)

urlpatterns = [
    path("profile/listings/", views.seller_listings_view, name="seller-listings"),
    path("profile/settings/", views.seller_settings_view, name="seller-settings"),
    path("profile/pickups/", views.buyer_pickups_view, name="buyer-pickups"),
    path("profile/saved-bundles/", views.buyer_bundles_view, name="buyer-bundles"),
    path(
        "profile/purchase-history/",
        views.buyer_purchase_history_view,
        name="buyer-purchase-history",
    ),
    path(
        "profile/purchase-history/download/",
        views.buyer_purchase_history_csv,
        name="buyer-purchase-history-csv",
    ),
    path("profile/watchlist/", views.buyer_watchlist_view, name="buyer-watchlist"),
    path("listings/new/", ListingCreateView.as_view(), name="listing-create-url"),
    path(
        "listings/<int:primary_key>/preview/",
        ListingPreviewView.as_view(),
        name="listing-preview-url",
    ),
    path(
        "listings/<int:primary_key>/publish/",
        listing_publish,
        name="listing-publish-url",
    ),
    path(
        "listings/<int:primary_key>/edit/",
        ListingUpdateView.as_view(),
        name="listing-update-url",
    ),
    path("listings/images/upload/", listing_image_upload, name="listing_image_upload"),
    path("listings/", ListingListView.as_view(), name="listing-list-url"),
    path(
        "listings/<int:primary_key>/",
        ListingDetailView.as_view(),
        name="listing-detail-url",
    ),
]
