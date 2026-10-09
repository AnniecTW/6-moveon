"""Use the same credential and campus-access rules for allauth sessions."""

from allauth.account.adapter import DefaultAccountAdapter
from allauth.account.auth_backends import AuthenticationBackend
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.http import HttpResponseForbidden
from django.shortcuts import redirect
from django.utils.http import url_has_allowed_host_and_scheme

from .auth_backend import CampusModelBackend, account_usable, has_campus_access
from .email_state import sync_campus_email
from .email_verification import EmailDeliveryError, issue_code


class CampusAllauthBackend(CampusModelBackend, AuthenticationBackend):
    """Preserve unambiguous identifiers and reject suspended accounts."""


class CampusAccountAdapter(DefaultAccountAdapter):
    def clean_email(self, email):
        email = email.strip().lower()
        validate_email(email)
        if not email.endswith("@illinois.edu"):
            raise ValidationError("Use an @illinois.edu email address.")
        return email

    def pre_login(self, request, user, **kwargs):
        if not account_usable(user) or not user.email.lower().endswith("@illinois.edu"):
            return HttpResponseForbidden("This account does not have campus access.")
        sync_campus_email(user)
        if not has_campus_access(user):
            target = kwargs.get("redirect_url")
            if target and url_has_allowed_host_and_scheme(
                target, {request.get_host()}, require_https=request.is_secure(),
            ):
                request.session["account_next"] = target
            request.session["pending_verification_user_id"] = user.pk
            try:
                issue_code(user)
            except EmailDeliveryError:
                request.session["verification_delivery_error"] = True
            return redirect("account_verify")
        return super().pre_login(request, user, **kwargs)
