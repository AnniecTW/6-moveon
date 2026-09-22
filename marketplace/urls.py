from django.urls import path

from marketplace.views import ListingCreateView, ListingDetailView, ListingListView

urlpatterns = [
    path("listings/new/", ListingCreateView.as_view(), name="listing-create-url"),
    path("listings/", ListingListView.as_view(), name="listing-list-url"),
    path(
        "listings/<int:primary_key>/",
        ListingDetailView.as_view(),
        name="listing-detail-url",
    ),
]
