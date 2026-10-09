from django.urls import path

from marketplace import views
from marketplace import api, charts, reports
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
    # Personal charts; the existing URL/name is retained for reverse compatibility.
    path("charts/", charts.personal_charts, name="a4-charts"),
    path("api/listings/demo/", api.listings_documentation, name="listing-api-demo"),
    # Internal listing data and external currency conversion.
    path("api/listings/", api.listings, name="listing-api"),
    path("api/listings/converted/", api.converted_listings, name="listing-currency-api"),
    # Database-backed chart data.
    path("api/profile/charts/earned-spent/", charts.earned_spent_data, name="profile-earned-spent-data"),
    path("api/profile/charts/earned-spent-timeline/", charts.earned_spent_timeline_data, name="profile-earned-spent-timeline-data"),
    path("api/profile/charts/listing-inquiries/", charts.listing_inquiry_chart_data, name="profile-listing-inquiry-data"),
    # Vega-Lite specifications and rendered images.
    path("vega-lite/earned-spent.json", charts.earned_spent_spec, name="vega-earned-spent-spec"),
    path("vega-lite/earned-spent-timeline.json", charts.earned_spent_timeline_spec, name="vega-earned-spent-timeline-spec"),
    path("vega-lite/listing-inquiries.json", charts.listing_inquiry_spec, name="vega-listing-inquiries-spec"),
    path("vega-lite/earned-spent.png", charts.earned_spent_png, name="vega-earned-spent-png"),
    path("vega-lite/earned-spent-timeline.png", charts.earned_spent_timeline_png, name="vega-earned-spent-timeline-png"),
    path("vega-lite/listing-inquiries.png", charts.listing_inquiry_png, name="vega-listing-inquiries-png"),
    # Campus-access reports and downloads.
    path("reports/", reports.listing_report, name="listing-report"),
    path("reports/listings.csv", reports.listings_csv, name="listing-export-csv"),
    path("reports/listings.json", reports.listings_json, name="listing-export-json"),
    # Marketplace pages and preserved account workflows.
    path("profile/inquiries.png", charts.listing_inquiry_png, name="listing-inquiry-chart"),
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
