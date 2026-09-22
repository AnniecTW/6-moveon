"""
URL configuration for moveon project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

from django.contrib import admin
from django.urls import path
from marketplace import views

urlpatterns = [
    path("", views.listing_render_view, name="home"),
    path("admin/", admin.site.urls),
    path("listings/manual/", views.listing_manual_view, name="listing_manual"),
    path("listings/render/", views.listing_render_view, name="listing_render"),
    path(
        "listings/cbv-base/", views.ListingBaseView.as_view(), name="listing_cbv_base"
    ),
    path(
        "listings/cbv-generic/",
        views.ListingListView.as_view(),
        name="listing_cbv_generic",
    ),
    path("seller/listings/", views.seller_listings_view, name="seller-listings"),
    path("seller/insights/", views.seller_insights_view, name="seller-insights"),
    path(
        "seller/pricing-and-moveout/",
        views.seller_pricing_view,
        name="seller-pricing",
    ),
    path("seller/settings/", views.seller_settings_view, name="seller-settings"),
    path("buyer/pickups/", views.buyer_pickups_view, name="buyer-pickups"),
    path("buyer/saved-bundles/", views.buyer_bundles_view, name="buyer-bundles"),
    path(
        "buyer/purchase-history/",
        views.buyer_purchase_history_view,
        name="buyer-purchase-history",
    ),
    path(
        "buyer/purchase-history/download/",
        views.buyer_purchase_history_csv,
        name="buyer-purchase-history-csv",
    ),
    path("buyer/watchlist/", views.buyer_watchlist_view, name="buyer-watchlist"),
]
