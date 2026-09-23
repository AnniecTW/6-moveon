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
    path("account/", views.account_view, name="account"),
    path("account/logout/", views.account_logout_view, name="account_logout"),
    path("account/verify/", views.account_verify_view, name="account_verify"),
    path("account/verify/resend/", views.account_verify_resend_view, name="account_verify_resend"),
    path("account/forgot/", views.CampusPasswordResetView.as_view(), name="password_reset"),
    path("account/forgot/sent/", views.password_reset_done_view, name="password_reset_done"),
    path("account/reset/<uidb64>/<token>/", views.CampusPasswordResetConfirmView.as_view(), name="password_reset_confirm"),
    path("account/google/", views.account_google_view, name="account_google"),
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
]
