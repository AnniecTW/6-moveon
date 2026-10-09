"""Use the same credential and campus-access rules for allauth sessions."""

from allauth.account.adapter import DefaultAccountAdapter
from allauth.account.auth_backends import AuthenticationBackend
from allauth.account.models import EmailAddress
from allauth.core.exceptions import ImmediateHttpResponse
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from allauth.socialaccount.models import SocialAccount
from allauth.socialaccount.providers.base import AuthError, AuthProcess
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.http import HttpResponseForbidden
from django.shortcuts import redirect
from django.utils.http import url_has_allowed_host_and_scheme

from .auth_backend import CampusModelBackend, account_usable, has_campus_access
from .email_state import sync_campus_email
from .email_verification import EmailDeliveryError, issue_code
from .oauth import google_failure


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
            sociallogin = (kwargs.get("signal_kwargs") or {}).get("sociallogin")
            request.session["verification_login_method"] = "google" if sociallogin else "password"
            try:
                issue_code(user)
            except EmailDeliveryError:
                request.session["verification_delivery_error"] = True
            return redirect("account_verify")
        return super().pre_login(request, user, **kwargs)


class CampusSocialAccountAdapter(DefaultSocialAccountAdapter):
    """Google proves its identity; the local challenge grants campus access."""

    def reject(self, request, message):
        raise ImmediateHttpResponse(google_failure(request, message))

    def pre_social_login(self, request, sociallogin):
        account = sociallogin.account
        data = account.extra_data
        subject = data.get("sub") or data.get("id")
        try:
            email = CampusAccountAdapter(request).clean_email(data.get("email", ""))
        except (ValidationError, AttributeError):
            self.reject(request, "Use a Google account with a verified @illinois.edu email address.")
        verified = data.get("email_verified", data.get("verified_email")) is True
        if (account.provider != "google" or not isinstance(subject, str)
                or not subject.strip() or subject != subject.strip()
                or subject != account.uid or len(subject) > 255 or not verified):
            self.reject(request, "Use a Google account with a verified @illinois.edu email address.")

        User = get_user_model()
        connecting = sociallogin.state.get("process") == AuthProcess.CONNECT
        if connecting:
            user = request.user
            if not has_campus_access(user):
                self.reject(request, "Sign in and verify your campus email before connecting Google.")
            if sociallogin.is_existing and sociallogin.user.pk != user.pk:
                self.reject(request, "This Google identity is already linked to another account.")
            legacy = User.objects.filter(google_subject=subject).first()
            if legacy and legacy.pk != user.pk:
                self.reject(request, "This Google identity is already linked to another account.")
            if user.email.lower() != email:
                self.reject(request, "Connect Google using the same campus email as your MoveOn account.")
            if (user.google_subject and user.google_subject != subject) or SocialAccount.objects.filter(
                user=user, provider="google",
            ).exclude(uid=subject).exists():
                self.reject(request, "A different Google identity is already linked to this account.")
        else:
            user = sociallogin.user if sociallogin.is_existing else User.objects.filter(google_subject=subject).first()
            if user:
                if not account_usable(user):
                    self.reject(request, "This account is unavailable.")
                if user.email.lower() != email:
                    self.reject(request, "Google account email changed. Contact support.")
                if not sociallogin.is_existing:
                    # Existing historical subject links are identity evidence;
                    # a matching email alone is never enough to attach an account.
                    if SocialAccount.objects.filter(user=user, provider="google").exclude(uid=subject).exists():
                        self.reject(request, "A different Google identity is already linked to this account.")
                    try:
                        with transaction.atomic():
                            sociallogin.user = user
                            sociallogin.save(request, connect=True)
                    except IntegrityError:
                        self.reject(request, "Google account linking could not be completed. Try again.")
            elif User.objects.filter(email__iexact=email).exists() or User.objects.filter(username__iexact=email).exists():
                self.reject(request, "An account with this email already exists. Log in with your password, then connect Google in Settings.")
            elif EmailAddress.objects.filter(email__iexact=email).exists():
                self.reject(request, "This email is associated with an existing account. Contact support to resolve the email conflict.")
            else:
                sociallogin.user.email = email
                sociallogin.user.display_name = str(data.get("name") or email.partition("@")[0])[:150]
                sociallogin.user.google_subject = subject
        # Keep allauth EmailAddress metadata tied to the local campus proof.
        for address in sociallogin.email_addresses:
            address.email = email
            address.verified = bool(user and has_campus_access(user))

    def save_user(self, request, sociallogin, form=None):
        try:
            with transaction.atomic():
                return super().save_user(request, sociallogin, form)
        except IntegrityError:
            self.reject(request, "This account already exists. Log in again or use your password.")

    def get_connect_redirect_url(self, request, socialaccount):
        from django.urls import reverse

        return reverse("seller-settings")

    def on_authentication_error(self, request, provider, error=None, exception=None, extra_context=None):
        message = ("Google sign-in was cancelled. You can try again or use your password."
                   if error == AuthError.CANCELLED else "Google sign-in could not be completed. Please try again.")
        self.reject(request, message)
