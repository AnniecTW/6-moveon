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
from django.conf import settings
from django.conf.urls.static import static
from django.urls import include, path
from marketplace import views
from messaging import api as messaging_api
from bundles import messaging as bundle_messaging

urlpatterns = [
    path("messages/", messaging_api.page, name="messages"),
    path("api/messaging/bundles/<int:bundle_id>/send-requests/", messaging_api.api_guard(bundle_messaging.send_requests), name="bundle_send_requests"),
    path("api/messaging/conversations/", messaging_api.api_guard(messaging_api.conversations), name="messaging_conversations"),
    path("api/messaging/unread/", messaging_api.api_guard(messaging_api.unread), name="messaging_unread"),
    path("api/messaging/conversations/create/", messaging_api.api_guard(messaging_api.create), name="messaging_create"),
    path("api/messaging/conversations/<str:conversation_id>/messages/", messaging_api.api_guard(messaging_api.messages), name="messaging_messages"),
    path("api/messaging/conversations/<str:conversation_id>/read/", messaging_api.api_guard(messaging_api.mark_read), name="messaging_read"),
    path("api/messaging/requests/<str:request_id>/decision/", messaging_api.api_guard(messaging_api.request_decision), name="messaging_request_decision"),
    path("api/messaging/uploads/", messaging_api.api_guard(messaging_api.upload), name="messaging_upload"),
    path("api/messaging/attachments/<str:image_id>/", messaging_api.api_guard(messaging_api.attachment), name="messaging_attachment"),
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
    path("", include("marketplace.urls")),
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

if settings.DEBUG:
    urlpatterns += static(
        settings.STATIC_URL, document_root=settings.BASE_DIR / "static"
    )
