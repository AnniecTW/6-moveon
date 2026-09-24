import csv
from datetime import date, timedelta
from decimal import Decimal
from django.db.models import Count, F, Q, Sum
from messaging.models import Conversation
from bundles.models import Bundle

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
from django.views import View
from django.views.generic import ListView, UpdateView
from PIL import Image, UnidentifiedImageError
from google.auth.exceptions import GoogleAuthError
from .auth_forms import CampusAuthenticationForm, ListingSignupForm
from .auth_backend import credential_user, has_campus_access
from .email_verification import EmailDeliveryError, consume_code, issue_code
from . import google_auth
from .models import ItemCategory, Listing, ListingImage, Transaction, User, WatchlistItem
from django.views.generic import CreateView, DetailView
from django.contrib.auth.mixins import LoginRequiredMixin
from .featured import decorate_listing, discount_percent
from .browse import browse_context
from .forms import ListingCreateForm, SellerSettingsForm, PurchaseHistorySearchForm
from .charts import listing_inquiry_data
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

    def get(self, request, *args, **kwargs):
        response = super().get(request, *args, **kwargs)
        if request.method == "GET" and self.object.status == Listing.Status.ACTIVE:
            Listing.objects.filter(pk=self.object.pk).update(views=F("views") + 1)
        return response

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


def _seller_profile(user):
    """Keep shared account details in one context shape for future dashboards."""
    return {
        "name": user.display_name or user.get_username(),
        "initial": (user.display_name or user.get_username() or "?")[0].upper(),
        "verified": user.email_verified,
    }


def _unanswered_listing_inquiries(user, participant_field, sender_field):
    """Count listing conversations with no messages or unread messages from the other person."""
    conversations = Conversation.objects.filter(
        **{participant_field: user, "listing__isnull": False}
    )
    needs_response = Q(messages__isnull=True) | Q(
        **{f"messages__sender_id": F(sender_field), "messages__is_read": False}
    )
    return (
        conversations.annotate(
            unanswered=Count("pk", filter=needs_response, distinct=True)
        )
        .filter(unanswered__gt=0)
        .count()
    )


def _seller_dashboard_context(user):
    """Shared, model-backed context for every Seller dashboard route."""
    seller_listings = Listing.objects.filter(seller=user)
    active_listings = seller_listings.filter(status=Listing.Status.ACTIVE)
    reserved_count = seller_listings.filter(status=Listing.Status.RESERVED).count()
    sold_count = seller_listings.filter(status=Listing.Status.SOLD).count()
    upcoming_deadline = date.today() + timedelta(days=7)
    approaching_moveout = seller_listings.filter(
        status__in=[Listing.Status.ACTIVE, Listing.Status.RESERVED],
        move_out_date__range=(date.today(), upcoming_deadline),
    ).count()
    missing_moveout = seller_listings.filter(
        status__in=[Listing.Status.ACTIVE, Listing.Status.RESERVED],
        move_out_date__isnull=True,
    ).count()
    seller_conversations = Conversation.objects.filter(
        seller=user, listing__isnull=False
    )
    unanswered_inquiries = _unanswered_listing_inquiries(
        user, "seller", "buyer_id"
    )
    completed_sales = Transaction.objects.filter(
        seller=user, status=Transaction.Status.COMPLETED
    )
    inquiry_chart = listing_inquiry_data(user)
    return {
        "profile": _seller_profile(user),
        "campus_access": has_campus_access(user),
        "active_count": active_listings.count(),
        "reserved_count": reserved_count,
        "sold_count": sold_count,
        "total_views": seller_listings.aggregate(total=Sum("views"))["total"] or 0,
        "inquiries": seller_conversations.count(),
        "unanswered_inquiries": unanswered_inquiries,
        "approaching_moveout": approaching_moveout,
        "missing_moveout": missing_moveout,
        "listing_inquiry_chart": inquiry_chart,
        "total_earned": completed_sales.aggregate(total=Sum("agreed_price"))["total"] or Decimal("0"),
    }


@login_required
def seller_listings_view(request):
    today = date.today()
    listings = (
        Listing.objects.filter(seller=request.user)
        .select_related("item_type", "item_type__category")
        .prefetch_related("images")
        .annotate(inquiry_count=Count("conversations__buyer", distinct=True))
    )
    query = request.GET.get("q", "").strip()
    status = request.GET.get("status", "ALL")
    category = request.GET.get("category", "")
    ordering = request.GET.get("ordering", "newest")
    if query:
        listings = listings.filter(title__icontains=query)
    if status and status != "ALL":
        listings = listings.filter(status=status)
    if category:
        listings = listings.filter(item_type__category_id=category)
    listings = listings.order_by("listing_price" if ordering == "price" else "-created_at")

    listing_rows = []
    for listing in listings:
        listing.display_image_url = listing.cover_image_url
        listing.view_count = listing.views
        listing.days_remaining = (
            max((listing.move_out_date - today).days, 0)
            if listing.move_out_date
            else None
        )
        listing_rows.append(listing)

    return render(
        request,
        "marketplace/seller_listings.html",
        {
            **_buyer_pickups_context(request.user),
            "active_seller_tab": "listings",
            "active_buyer_tab": "",
            "listings": listing_rows,
            "categories": ItemCategory.objects.filter(
                item_types__listings__seller=request.user
            ).distinct(),
            "listing_status_choices": Listing.Status.choices,
            "selected_category": category,
            "selected_status": status,
            "selected_ordering": ordering,
        },
    )


@login_required
def seller_settings_view(request):
    form = SellerSettingsForm()
    return render(
        request,
        "marketplace/seller_settings.html",
        {
            **_buyer_pickups_context(request.user),
            "active_seller_tab": "settings",
            "active_buyer_tab": "",
            "settings_form": form,
        },
    )


def _pickup_image(listing):
    return listing.cover_image_url


def _transaction_reference_value(transaction):
    return (
        transaction.benchmark_price_snapshot
        or transaction.listing.retail_price
        or transaction.listing.benchmark_price
    )


def _transaction_savings(transaction):
    reference_value = _transaction_reference_value(transaction)
    if reference_value is None:
        return None
    return max(reference_value - transaction.agreed_price, Decimal("0"))


def _buyer_pickups_context(user):
    purchases = list(
        Transaction.objects.filter(buyer=user)
        .exclude(status=Transaction.Status.CANCELLED)
        .select_related(
            "listing",
            "listing__item_type",
            "listing__item_type__category",
            "seller",
            "bundle",
        )
    )
    pending = [
        transaction
        for transaction in purchases
        if transaction.status == Transaction.Status.PENDING_PICKUP
    ]
    buyer_unanswered_inquiries = _unanswered_listing_inquiries(
        user, "buyer", "seller_id"
    )
    pickup_rows = []
    for transaction in pending:
        pickup_rows.append(
            {
                "transaction_id": transaction.pk,
                "listing": transaction.listing,
                "image_url": _pickup_image(transaction.listing),
                "agreed_price": transaction.agreed_price,
                "savings": _transaction_savings(transaction),
                "seller": transaction.seller,
                "meetup_datetime": transaction.meetup_datetime,
                "meetup_location": transaction.meetup_location,
                "status_label": transaction.get_status_display(),
            }
        )

    amount_paid = sum((item.agreed_price for item in purchases), Decimal("0"))
    completed_sales = list(
        Transaction.objects.filter(seller=user, status=Transaction.Status.COMPLETED)
    )
    total_earned = sum((item.agreed_price for item in completed_sales), Decimal("0"))
    known_savings = [value for item in purchases if (value := _transaction_savings(item)) is not None]
    total_saved = sum(known_savings, Decimal("0"))
    estimated_value = sum(
        (value for item in purchases if (value := _transaction_reference_value(item)) is not None),
        Decimal("0"),
    )
    chart_max = max(amount_paid, total_earned, Decimal("1"))
    spent_bar_height = round(float(amount_paid / chart_max) * 100)
    earned_bar_height = round(float(total_earned / chart_max) * 100)
    chart_points = [
        {
            "type": "purchase",
            "date": (
                transaction.completed_at or transaction.created_at
            ).date().isoformat(),
            "spent": float(transaction.agreed_price),
            "earned": 0,
        }
        for transaction in purchases
        if transaction.status
        in (Transaction.Status.PENDING_PICKUP, Transaction.Status.COMPLETED)
    ]
    chart_points.extend(
        {
            "type": "sale",
            "date": (transaction.completed_at or transaction.created_at).date().isoformat(),
            "spent": 0,
            "earned": float(transaction.agreed_price),
        }
        for transaction in completed_sales
    )
    return {
        **_seller_dashboard_context(user),
        "profile": _seller_profile(user),
        "active_buyer_tab": "pickups",
        "buyer_summary": {
            "total_saved": total_saved,
            "items_bought": len(purchases),
            "pending_pickups": len(pending),
            "saved_bundles": Bundle.objects.filter(buyer=user)
            .exclude(status=Bundle.Status.CANCELLED)
            .count(),
            "amount_paid": amount_paid,
            "total_earned": total_earned,
            "net_balance": total_earned - amount_paid,
            "items_moved": len(purchases) + len(completed_sales),
            "estimated_value": estimated_value,
            "chart_max": chart_max,
            "spent_bar_height": spent_bar_height,
            "earned_bar_height": earned_bar_height,
            "chart_points": chart_points,
        },
        "buyer_unanswered_inquiries": buyer_unanswered_inquiries,
        "pickup_rows": pickup_rows,
    }


def _buyer_bundles_context(user):
    context = _buyer_pickups_context(user)
    bundles = list(
        Bundle.objects.filter(buyer=user)
        .exclude(status=Bundle.Status.CANCELLED)
        .prefetch_related(
            "bundle_items__listing__seller",
            "bundle_items__listing__item_type__category",
        )
    )
    bundle_rows = []
    for bundle in bundles:
        item_rows = []
        current_total = Decimal("0")
        estimated_value = Decimal("0")
        confirmed_count = 0
        for item in bundle.bundle_items.all():
            item_price = (
                item.final_price
                or item.proposed_bundle_price
                or item.listing_price_snapshot
            )
            reference_value = item.listing.retail_price or item.listing.benchmark_price
            confirmed = item.item_status == item.ItemStatus.ACCEPTED
            confirmed_count += int(confirmed)
            current_total += item_price
            if reference_value is not None:
                estimated_value += reference_value
            item_rows.append(
                {
                    "item": item,
                    "image_url": _pickup_image(item.listing),
                    "price": item_price,
                    "confirmed": confirmed,
                    "status_label": item.get_item_status_display(),
                }
            )
        saved_amount = (
            max(estimated_value - current_total, Decimal("0"))
            if item_rows and all(
                row["item"].listing.retail_price is not None
                or row["item"].listing.benchmark_price is not None
                for row in item_rows
            )
            else None
        )
        total_items = len(item_rows)
        progress_percent = (
            round(confirmed_count / total_items * 100) if total_items else 0
        )
        bundle_rows.append(
            {
                "bundle": bundle,
                "name": f"{bundle.get_space_display()} Move-In Bundle",
                "items": item_rows,
                "target_budget": None,
                "current_total": current_total,
                "saved_amount": saved_amount,
                "confirmed_count": confirmed_count,
                "total_items": total_items,
                "progress_percent": progress_percent,
            }
        )

    context.update(
        {
            "active_buyer_tab": "bundles",
            "bundle_rows": bundle_rows,
        }
    )
    return context


def _purchase_history_rows(transactions):
    rows = []
    for transaction in transactions:
        rows.append(
            {
                "transaction": transaction,
                "image_url": _pickup_image(transaction.listing),
                "purchase_date": transaction.completed_at or transaction.created_at,
            }
        )
    return rows


def _buyer_purchase_history_context(user, search_form=None):
    context = _buyer_pickups_context(user)
    transactions = (
        Transaction.objects.filter(buyer=user, status=Transaction.Status.COMPLETED)
        .select_related("listing", "listing__item_type", "listing__item_type__category", "seller")
        .order_by("-completed_at", "-created_at")
    )
    if search_form is not None and search_form.is_valid():
        query = search_form.cleaned_data["q"]
        for term in query.split():
            transactions = transactions.filter(
                Q(listing__title__icontains=term) | Q(seller__display_name__icontains=term)
            )
    elif search_form is not None:
        transactions = transactions.none()
    history_rows = _purchase_history_rows(transactions)
    context.update(
        {
            "active_buyer_tab": "history",
            "history_rows": history_rows,
            "history_search_form": search_form if search_form is not None else PurchaseHistorySearchForm(),
        }
    )
    return context


def _buyer_watchlist_context(user):
    context = _buyer_pickups_context(user)
    entries = list(
        WatchlistItem.objects.filter(user=user)
        .select_related(
            "listing",
            "listing__seller",
            "listing__item_type",
            "listing__item_type__category",
        )
    )
    listings = []
    for entry in entries:
        listing = entry.listing
        listing.display_image_url = listing.cover_image_url
        listing.reference_value = listing.retail_price or listing.benchmark_price
        listing.discount_percent = discount_percent(
            listing.reference_value, listing.listing_price
        )
        listing.watchlisted_at = entry.created_at
        listings.append(listing)
    context.update(
        {
            "active_buyer_tab": "watchlist",
            "watchlist_candidates": listings,
            "watchlist_categories": sorted(
                {item.item_type.category.category_name for item in listings}
            ),
        }
    )
    return context


@login_required
def buyer_watchlist_view(request):
    return render(
        request,
        "marketplace/buyer_watchlist.html",
        _buyer_watchlist_context(request.user),
    )


@login_required
def buyer_purchase_history_view(request):
    return render(
        request,
        "marketplace/buyer_purchase_history.html",
        _buyer_purchase_history_context(
            request.user,
            PurchaseHistorySearchForm(request.POST) if request.method == "POST" else None,
        ),
    )


@login_required
def buyer_purchase_history_csv(request):
    transactions = (
        Transaction.objects.filter(
            buyer=request.user, status=Transaction.Status.COMPLETED
        )
        .select_related("listing", "seller")
        .order_by("-completed_at", "-created_at")
    )
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="moveon-purchase-history.csv"'
    writer = csv.writer(response)
    writer.writerow(
        [
            "Purchase date",
            "Item",
            "Seller",
            "Final price",
            "Estimated retail/reference price",
            "Estimated savings",
            "Transaction status",
        ]
    )
    for transaction in transactions:
        reference_value = _transaction_reference_value(transaction)
        purchase_date = transaction.completed_at or transaction.created_at
        writer.writerow(
            [
                purchase_date.date().isoformat(),
                transaction.listing.title,
                transaction.seller.display_name or transaction.seller.username,
                transaction.agreed_price,
                reference_value or "",
                _transaction_savings(transaction) if reference_value is not None else "",
                transaction.get_status_display(),
            ]
        )
    return response


@login_required
def buyer_pickups_view(request):
    return render(
        request,
        "marketplace/buyer_pickups.html",
        _buyer_pickups_context(request.user),
    )


@login_required
def buyer_bundles_view(request):
    return render(
        request,
        "marketplace/buyer_saved_bundles.html",
        _buyer_bundles_context(request.user),
    )
