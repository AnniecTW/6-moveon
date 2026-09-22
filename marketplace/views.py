from urllib.parse import urlencode

from django.http import HttpResponse
from django.contrib.auth import login, logout
from django.contrib.auth.views import PasswordResetConfirmView, PasswordResetView
from django.conf import settings
from django.urls import reverse, reverse_lazy
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST
from django.shortcuts import redirect, render
from django.template import loader
from django.urls import reverse_lazy
from django.views import View
from django.views.generic import ListView
from google.auth.exceptions import GoogleAuthError
from .auth_forms import CampusAuthenticationForm, ListingSignupForm
from .auth_backend import credential_user, has_campus_access
from .email_verification import EmailDeliveryError, consume_code, issue_code
from . import google_auth
from .models import Listing, User
from django.views.generic import CreateView, DetailView, ListView
from django.contrib.auth.mixins import LoginRequiredMixin
from .featured import decorate_listing
from .models import Listing
from .browse import browse_context
from .forms import ListingCreateForm


def _safe_return(request):
    target = request.POST.get("next") or request.GET.get("next") or request.session.get("account_next")
    if target and url_has_allowed_host_and_scheme(target, {request.get_host()}, require_https=request.is_secure()):
        return target
    return reverse("home")


def _account_context(request, **extra):
    context = browse_context(request)
    context.update(extra)
    context["auth_overlay"] = True
    context["google_client_id"] = settings.GOOGLE_CLIENT_ID
    context["account_next"] = request.session.get("account_next", reverse("home"))
    context["return_to_messages"] = context["account_next"].startswith(reverse("messages"))
    context["console_email_backend"] = settings.EMAIL_BACKEND in (
        "marketplace.mail_backends.ReadableConsoleEmailBackend",
        "django.core.mail.backends.console.EmailBackend",
    )
    return context


def _pending_user(request):
    uid = request.session.get("pending_verification_user_id")
    return User.objects.filter(pk=uid).first() if uid else None


def _account_after_verification(request):
    target = _safe_return(request)
    if target == reverse("home"):
        return redirect("account")
    return redirect(reverse("account") + "?" + urlencode({"next": target}))


def account_view(request):
    if request.user.is_authenticated:
        if has_campus_access(request.user):
            return redirect("home")
        return render(request, "marketplace/account.html", _account_context(
            request, auth_mode="restricted", restricted_admin=request.user.is_staff,
            restricted_campus_email=request.user.email.lower().endswith("@illinois.edu"),
        ))

    if request.method == "GET":
        target = request.GET.get("next")
        request.session["account_next"] = (
            target if target and url_has_allowed_host_and_scheme(
                target, {request.get_host()}, require_https=request.is_secure()
            ) else reverse("home")
        )
    mode = request.POST.get("mode") if request.method == "POST" else request.GET.get("mode")
    mode = "signup" if mode == "signup" else "login"
    data = request.POST if request.method == "POST" else None
    form = (
        ListingSignupForm(data)
        if mode == "signup"
        else CampusAuthenticationForm(request, data=data)
    )
    if request.method == "POST":
        if form.is_valid():
            if mode == "signup":
                user = form.save()
                request.session["pending_verification_user_id"] = user.pk
                try:
                    issue_code(user)
                except EmailDeliveryError:
                    request.session["verification_delivery_error"] = True
                return redirect("account_verify")
            login(request, form.get_user())
            return redirect(_safe_return(request))
        if mode == "login":
            candidate = credential_user(request.POST.get("username", "").strip(), request.POST.get("password", ""))
            if candidate:
                if candidate.is_active and candidate.account_status == User.AccountStatus.ACTIVE and not has_campus_access(candidate) and candidate.email.lower().endswith("@illinois.edu"):
                    candidate.email_verified = False
                    candidate.email_verified_at = None
                    candidate.save(update_fields=["email_verified", "email_verified_at"])
                    request.session["pending_verification_user_id"] = candidate.pk
                    try:
                        issue_code(candidate)
                    except EmailDeliveryError:
                        request.session["verification_delivery_error"] = True
                    return redirect("account_verify")
    response = render(request, "marketplace/account.html", _account_context(
        request, auth_form=form, auth_mode=mode,
        reset_done=request.GET.get("reset") == "done",
    ))
    if settings.GOOGLE_CLIENT_ID:
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin-allow-popups"
    return response


def account_verify_view(request):
    user = _pending_user(request)
    if not user:
        return redirect("account")
    if has_campus_access(user):
        request.session.pop("pending_verification_user_id", None)
        return _account_after_verification(request)
    error = None
    if request.method == "POST":
        code = request.POST.get("code", "").strip()
        if not (len(code) == 6 and code.isascii() and code.isdigit()):
            error = "Enter the six-digit verification code."
        else:
            error = consume_code(user, code)
            if error is None:
                request.session.pop("pending_verification_user_id", None)
                return _account_after_verification(request)
    delivery_error = request.session.pop("verification_delivery_error", False)
    cooldown = request.session.pop("verification_cooldown", False)
    resent = request.session.pop("verification_resent", False)
    return render(request, "marketplace/account.html", _account_context(
        request, auth_mode="verify", verify_email=user.email, verify_error=error,
        delivery_error=delivery_error, verification_cooldown=cooldown, verification_resent=resent,
    ))


@require_POST
def account_verify_resend_view(request):
    user = _pending_user(request)
    if not user or has_campus_access(user) or not user.is_active or user.account_status != User.AccountStatus.ACTIVE:
        return redirect("account")
    try:
        if not issue_code(user):
            request.session["verification_cooldown"] = True
        else:
            request.session["verification_resent"] = True
    except EmailDeliveryError:
        request.session["verification_delivery_error"] = True
    return redirect("account_verify")


class CampusPasswordResetView(PasswordResetView):
    template_name = "marketplace/account.html"
    email_template_name = "marketplace/password_reset_email.txt"
    subject_template_name = "marketplace/password_reset_subject.txt"
    success_url = reverse_lazy("password_reset_done")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(_account_context(self.request, auth_mode="forgot", auth_form=context["form"]))
        return context


class CampusPasswordResetConfirmView(PasswordResetConfirmView):
    template_name = "marketplace/account.html"
    success_url = reverse_lazy("account")

    def dispatch(self, request, *args, **kwargs):
        token = kwargs.get("token", "")
        if token.endswith("=") and not token.endswith("=="):
            user = self.get_user(kwargs["uidb64"])
            clean_token = token[:-1]
            if user is not None and self.token_generator.check_token(user, clean_token):
                return redirect(reverse(
                    "password_reset_confirm",
                    kwargs={"uidb64": kwargs["uidb64"], "token": clean_token},
                ))
        return super().dispatch(request, *args, **kwargs)

    def get_success_url(self):
        return reverse("account") + "?reset=done"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(_account_context(self.request, auth_mode="reset", auth_form=context.get("form")))
        return context


def password_reset_done_view(request):
    return render(request, "marketplace/account.html", _account_context(request, auth_mode="reset_sent"))


@require_POST
def account_google_view(request):
    if not settings.GOOGLE_CLIENT_ID:
        return render(request, "marketplace/account.html", _account_context(
            request, auth_mode="login", auth_form=CampusAuthenticationForm(request),
            google_error="Google sign-in is not configured.",
        ))
    credential = request.POST.get("credential", "")
    try:
        claims = google_auth.verify_google_token(credential, settings.GOOGLE_CLIENT_ID)
    except (ValueError, GoogleAuthError, OSError):
        claims = {}
    email = str(claims.get("email", "")).strip().lower()
    subject = str(claims.get("sub", "")).strip()
    error = None
    if not subject or claims.get("email_verified") is not True or not email.endswith("@illinois.edu"):
        error = "Use a Google account with an @illinois.edu email address."
    else:
        user = User.objects.filter(google_subject=subject).first()
        if user and user.email.lower() != email:
            error = "Google account email changed. Contact support."
        elif not user and User.objects.filter(email__iexact=email).exists():
            error = "An account with this email already exists. Log in with your username."
        elif not user:
            username = email.partition("@")[0]
            if User.objects.filter(username=username).exists():
                import secrets
                username = f"{username[:130]}_{secrets.token_hex(6)}"
            user = User(username=username, email=email, display_name=username, google_subject=subject)
            user.set_unusable_password()
            user.save()
        if not error:
            if not user.is_active or user.account_status != User.AccountStatus.ACTIVE:
                error = "This account is unavailable."
            elif not has_campus_access(user):
                user.email_verified = False
                user.email_verified_at = None
                user.save(update_fields=["email_verified", "email_verified_at"])
                request.session["pending_verification_user_id"] = user.pk
                try:
                    issue_code(user)
                except EmailDeliveryError:
                    request.session["verification_delivery_error"] = True
                return redirect("account_verify")
            else:
                login(request, user, backend="marketplace.auth_backend.CampusModelBackend")
                return redirect(_safe_return(request))
    return render(request, "marketplace/account.html", _account_context(
        request, auth_mode="login", auth_form=CampusAuthenticationForm(request), google_error=error,
    ))


@require_POST
def account_logout_view(request):
    logout(request)
    return redirect("home")


# 1. FBV (Manual HttpResponse)
def listing_manual_view(request):
    template = loader.get_template("marketplace/listing_list.html")
    return HttpResponse(template.render(browse_context(request), request))


# 2. FBV (render shortcut)
def listing_render_view(request):
    return render(request, "marketplace/listing_list.html", browse_context(request))


# 3. Base CBV
class ListingBaseView(View):
    def get(self, request):
        return render(request, "marketplace/listing_list.html", browse_context(request))


# 4. Generic CBV
class ListingListView(ListView):  # Naming Pattern: <Model><Purpose>View
    model = Listing
    template_name = "marketplace/listing_list.html"
    context_object_name = "listings"

    def get_queryset(self):
        self.browse = browse_context(self.request)
        return self.browse["listings"]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(self.browse)
        return context


class ListingDetailView(DetailView):
    model = Listing
    template_name = "marketplace/listing_detail.html"
    context_object_name = "listing"
    pk_url_kwarg = "primary_key"

    def get_queryset(self):
        return (
            Listing.objects.filter(status=Listing.Status.ACTIVE)
            .select_related("seller", "item_type__category")
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["listing"] = decorate_listing(context["listing"])
        context["similar_listings"] = [
            decorate_listing(item)
            for item in (
                self.get_queryset()
                .filter(item_type__category_id=self.object.item_type.category_id)
                .exclude(pk=self.object.pk)[:4]
            )
        ]
        return context


class ListingCreateView(LoginRequiredMixin, CreateView):
    model = Listing
    form_class = ListingCreateForm
    template_name = "marketplace/listing_form.html"
    success_url = reverse_lazy("home")

    def form_valid(self, form):
        form.instance.seller = self.request.user
        form.instance.status = Listing.Status.DRAFT
        return super().form_valid(form)
