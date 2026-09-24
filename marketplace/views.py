from urllib.parse import urlencode
from urllib.parse import urlparse
from uuid import uuid4

from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.validators import URLValidator
from django.http import HttpResponse, JsonResponse
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import PasswordResetConfirmView, PasswordResetView
from django.conf import settings
from django.urls import reverse, reverse_lazy
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST
from django.shortcuts import get_object_or_404, redirect, render
from django.template import loader
from django.urls import reverse_lazy
from django.views import View
from django.views.generic import ListView, UpdateView
from PIL import Image, UnidentifiedImageError
from google.auth.exceptions import GoogleAuthError
from .auth_forms import CampusAuthenticationForm, ListingSignupForm
from .auth_backend import credential_user, has_campus_access
from .email_verification import EmailDeliveryError, consume_code, issue_code
from . import google_auth
from .models import Listing, ListingImage, User
from django.views.generic import CreateView, DetailView
from django.contrib.auth.mixins import LoginRequiredMixin
from .featured import decorate_listing
from .browse import browse_context
from .forms import ListingCreateForm
from .validation import database_for


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
            .prefetch_related("images")
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


class ListingPreviewView(LoginRequiredMixin, ListingDetailView):
    def get_queryset(self):
        return (
            Listing.objects.filter(
                seller=self.request.user,
                status=Listing.Status.DRAFT,
            )
            .select_related("seller", "item_type__category")
            .prefetch_related("images")
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["preview_mode"] = True
        context["similar_listings"] = [
            decorate_listing(item)
            for item in (
                Listing.objects.filter(
                    status=Listing.Status.ACTIVE,
                    item_type__category_id=self.object.item_type.category_id,
                )
                .exclude(pk=self.object.pk)
                .select_related("seller", "item_type__category")
                .prefetch_related("images")[:4]
            )
        ]
        return context


class ListingFormContextMixin:
    form_class = ListingCreateForm

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["initial_photos"] = context["form"].selected_images_for_display()
        return context

    def get_success_url(self):
        if self.request.POST.get("action") == "preview":
            return reverse(
                "listing-preview-url",
                kwargs={"primary_key": self.object.pk},
            )
        return reverse("home")


class ListingCreateView(ListingFormContextMixin, LoginRequiredMixin, CreateView):
    model = Listing
    form_class = ListingCreateForm
    template_name = "marketplace/listing_form.html"
    success_url = reverse_lazy("home")

    def form_valid(self, form):
        form.instance.seller = self.request.user
        form.instance.status = Listing.Status.DRAFT
        return super().form_valid(form)


class ListingUpdateView(ListingFormContextMixin, LoginRequiredMixin, UpdateView):
    model = Listing
    form_class = ListingCreateForm
    template_name = "marketplace/listing_form.html"
    success_url = reverse_lazy("home")
    pk_url_kwarg = "primary_key"

    def get_queryset(self):
        return Listing.objects.filter(seller=self.request.user).prefetch_related("images")

    def form_valid(self, form):
        if self.request.POST.get("action") == "preview":
            form.instance.status = Listing.Status.DRAFT
        return super().form_valid(form)


@require_POST
@login_required
def listing_publish(request, primary_key):
    listing = get_object_or_404(
        Listing.objects.filter(
            seller=request.user,
            status=Listing.Status.DRAFT,
        ).prefetch_related("images"),
        pk=primary_key,
    )
    database = database_for(listing)
    image_ids = ListingImage.objects.using(database).filter(
        listing_id=listing.pk
    ).order_by("position", "id").values_list("pk", flat=True)
    fulfillment = listing.fulfillment_option
    form_data = {
        "title": listing.title,
        "listing_price": str(listing.listing_price),
        "condition": listing.condition,
        "item_type": str(listing.item_type_id),
        "fulfillment_option": fulfillment,
        "fulfillment_pickup": (
            "on"
            if fulfillment in (Listing.Fulfillment.PICKUP, Listing.Fulfillment.BOTH)
            else ""
        ),
        "fulfillment_delivery": (
            "on"
            if fulfillment in (Listing.Fulfillment.DELIVERY, Listing.Fulfillment.BOTH)
            else ""
        ),
        "description": listing.description,
        "minimum_price": (
            str(listing.minimum_price) if listing.minimum_price is not None else ""
        ),
        "move_out_date": (
            listing.move_out_date.isoformat() if listing.move_out_date else ""
        ),
        "bundle_eligible": "on" if listing.bundle_eligible else "",
        "sell_no_matter_what": "on" if listing.sell_no_matter_what else "",
        "image_ids": ",".join(str(image_id) for image_id in image_ids),
    }
    form = ListingCreateForm(data=form_data, instance=listing, user=request.user)
    if not form.is_valid():
        return render(
            request,
            "marketplace/listing_form.html",
            {
                "form": form,
                "initial_photos": form.selected_images_for_display(),
            },
        )

    form.instance.status = Listing.Status.ACTIVE
    listing = form.save()
    return redirect(listing.get_absolute_url())


MAX_LISTING_IMAGE_BYTES = 5 * 1024 * 1024
MAX_UNATTACHED_LISTING_IMAGES = 30
LISTING_IMAGE_FORMATS = {
    "JPEG": "jpg",
    "PNG": "png",
    "WEBP": "webp",
}


@login_required
@require_POST
def listing_image_upload(request):
    uploaded_file = request.FILES.get("file")
    external_url = request.POST.get("url", "").strip()
    if (uploaded_file is None) == (not external_url):
        return JsonResponse(
            {"error": "Provide either an image file or an image URL."}, status=400
        )

    pending_image = ListingImage(listing=None, uploaded_by=request.user)
    database = database_for(pending_image)
    if (
        ListingImage.objects.using(database)
        .filter(uploaded_by=request.user, listing__isnull=True)
        .count()
        >= MAX_UNATTACHED_LISTING_IMAGES
    ):
        return JsonResponse(
            {"error": "You have too many pending images. Finish a listing before uploading more."},
            status=400,
        )

    if uploaded_file is not None:
        if uploaded_file.size == 0 or uploaded_file.size > MAX_LISTING_IMAGE_BYTES:
            return JsonResponse(
                {"error": "Choose an image that is 5MB or smaller."}, status=400
            )
        try:
            uploaded_file.seek(0)
            with Image.open(uploaded_file) as image:
                image.verify()
                image_format = image.format
        except (Image.DecompressionBombError, OSError, UnidentifiedImageError, ValueError):
            return JsonResponse(
                {"error": "The file is not a valid image."}, status=400
            )
        if image_format not in LISTING_IMAGE_FORMATS:
            return JsonResponse(
                {"error": "Use a JPEG, PNG, or WebP image."}, status=400
            )
        uploaded_file.seek(0)
        uploaded_file.name = f"{uuid4().hex}.{LISTING_IMAGE_FORMATS[image_format]}"
        pending_image.image = uploaded_file
    else:
        try:
            URLValidator()(external_url)
        except DjangoValidationError:
            return JsonResponse({"error": "Enter a valid image URL."}, status=400)
        if urlparse(external_url).scheme not in {"http", "https"}:
            return JsonResponse(
                {"error": "Image URLs must use HTTP or HTTPS."}, status=400
            )
        pending_image.external_url = external_url

    pending_image.save(using=database)
    return JsonResponse({"id": pending_image.pk, "url": pending_image.url}, status=201)
