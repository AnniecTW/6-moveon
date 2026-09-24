from django.urls import path

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
