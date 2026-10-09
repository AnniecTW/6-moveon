"""Require campus access for application routes not declared public."""

from urllib.parse import urlencode

from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import redirect
from django.urls import reverse

from .auth_backend import has_campus_access


ACCOUNT_ROUTES = frozenset({
    "account", "account_logout", "account_verify", "account_verify_resend",
    "password_reset", "password_reset_done", "password_reset_confirm", "account_google",
    # Reserved for phase 4's allauth provider URLs; this does not install them.
    "google_login", "google_callback", "socialaccount_signup",
    "socialaccount_login_cancelled", "socialaccount_login_error",
})
PUBLIC_ROUTES = ACCOUNT_ROUTES | frozenset({
    "home", "listing-list-url", "listing-detail-url",
    "listing_manual", "listing_render", "listing_cbv_base", "listing_cbv_generic",
    "listing-api", "listing-api-demo",
})


def access_denied_response(request, *, json_response=False):
    """Keep machine-readable denials distinct from account-page redirects."""
    if json_response:
        authenticated = request.user.is_authenticated
        return JsonResponse(
            {"error": "Campus access required." if authenticated else "Sign in required.",
             "code": "campus_access_required" if authenticated else "login_required"},
            status=403 if authenticated else 401,
        )
    if request.method in ("GET", "HEAD"):
        target = reverse("account") + "?" + urlencode({"next": request.get_full_path()})
        return redirect(target)
    return HttpResponseForbidden("Campus access required.")


class CampusAccessMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_view(self, request, view_func, view_args, view_kwargs):
        match = request.resolver_match
        if "admin" in match.namespaces or (not match.namespaces and match.url_name in PUBLIC_ROUTES):
            return None
        if request.user.is_authenticated and has_campus_access(request.user):
            return None
        json_response = (
            request.path.startswith("/api/")
            or request.path.endswith(".json")
            or match.url_name == "listing_image_upload"
            or ("bundles" in match.namespaces and match.url_name in {"generate", "start_modal"}
                and request.method == "POST")
        )
        return access_denied_response(request, json_response=json_response)
