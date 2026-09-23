"""Require campus access for application routes not declared public."""

from urllib.parse import urlencode

from django.http import HttpResponseForbidden
from django.shortcuts import redirect
from django.urls import reverse

from .auth_backend import has_campus_access


PUBLIC_ROUTES = frozenset({
    "home",
    "listing_manual", "listing_render", "listing_cbv_base", "listing_cbv_generic",
    "account", "account_logout", "account_verify", "account_verify_resend",
    "password_reset", "password_reset_done", "password_reset_confirm", "account_google",
})


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
        if request.method in ("GET", "HEAD"):
            target = reverse("account") + "?" + urlencode({"next": request.get_full_path()})
            return redirect(target)
        return HttpResponseForbidden("Campus access required.")
