"""Small UI/permission boundary around allauth's Google OAuth views."""

from urllib.parse import urlencode

from allauth.socialaccount.providers.google import views as google_views
from allauth.socialaccount.providers.oauth2.client import OAuth2Error
from allauth.socialaccount.providers.oauth2.views import OAuth2CallbackView
from django.conf import settings
from django.contrib import messages
from django.db import IntegrityError
from django.http import HttpResponseForbidden
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_GET, require_POST

from .auth_backend import has_campus_access


class CampusGoogleOAuth2Adapter(google_views.GoogleOAuth2Adapter):
    def complete_login(self, request, app, token, **kwargs):
        try:
            return super().complete_login(request, app, token, **kwargs)
        except (ValueError, KeyError) as exc:
            # Invalid JSON/identity fields can fail before the social adapter.
            raise OAuth2Error("Invalid Google identity response.") from exc


_google_callback = OAuth2CallbackView.adapter_view(CampusGoogleOAuth2Adapter)


def google_configured():
    return bool(settings.GOOGLE_CLIENT_ID and settings.GOOGLE_CLIENT_SECRET)


def google_failure(request, message):
    if request.user.is_authenticated and has_campus_access(request.user):
        messages.error(request, message)
        return redirect("seller-settings")
    request.session["google_auth_error"] = message
    target = request.session.get("account_next", reverse("home"))
    if target == reverse("home"):
        return redirect("account")
    return redirect(reverse("account") + "?" + urlencode({"next": target}))


@require_POST
def google_login(request):
    process = request.POST.get("process", "login")
    if process not in {"login", "connect"}:
        return HttpResponseForbidden("Invalid Google authentication action.")
    if process == "connect" and not has_campus_access(request.user):
        return HttpResponseForbidden("Sign in and verify your campus email before connecting Google.")
    if not google_configured():
        return google_failure(request, "Google sign-in is not configured.")
    target = request.POST.get("next") or request.session.get("account_next")
    if not target or not url_has_allowed_host_and_scheme(
        target, {request.get_host()}, require_https=request.is_secure(),
    ):
        target = reverse("seller-settings") if process == "connect" else reverse("home")
    request.session["account_next"] = target
    # allauth owns state, PKCE and code exchange. Do not accept the old browser
    # credential as an identity assertion, or an unchecked redirect/process.
    request.POST = request.POST.copy()
    request.POST["next"] = target
    request.POST["process"] = process
    return google_views.oauth2_login(request)


@require_GET
def google_callback(request):
    if not google_configured():
        return google_failure(request, "Google sign-in is not configured.")
    try:
        return _google_callback(request)
    except IntegrityError:
        # A concurrent explicit connection can claim the same unique subject.
        return google_failure(request, "Google account linking could not be completed. Try again.")
