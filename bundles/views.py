from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import transaction as db_transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.generic import FormView, View

from marketplace.models import ItemType, Listing
from messaging.models import Conversation, Message

from .forms import CategorySelectForm, SpaceSelectForm
from .models import Bundle, BundleCategory, BundleItem
from .services import generate_bundle_tiers
from .space_categories import available_item_types_for_space

MINIMUM_BUNDLE_ITEMS = 3


def _compute_and_cache_generation(request, bundle):
    """Runs the (possibly slow, real-LLM-backed) tier generation for a
    bundle and caches the result in the session, keyed by bundle id. Shared
    by the async /bundles/generate/ endpoint and BundleBuilderView's
    fallback (for a bundle whose session cache expired or was never
    populated, e.g. a bookmarked/no-JS visit)."""
    item_type_ids = list(
        bundle.requested_categories.values_list("item_type_id", flat=True)
    )
    generation = generate_bundle_tiers(bundle.space, item_type_ids, bundle.buyer)
    generations = request.session.get("bundle_generations") or {}
    generations[str(bundle.id)] = generation
    request.session["bundle_generations"] = generations
    request.session.modified = True
    return generation


class BundleStartModalView(LoginRequiredMixin, View):
    """Renders the space+categories popup fragment. Fetched lazily by JS
    from the homepage (rather than rendered on every homepage load) so
    anonymous/no-JS visitors never pay for computing all 6 spaces' category
    availability up front - they still get the full-page fallback below."""

    template_name = "bundles/_start_modal_fragment.html"

    def get(self, request, *args, **kwargs):
        space_panels = [
            (value, label, available_item_types_for_space(value))
            for value, label in Bundle.Space.choices
        ]
        return render(request, self.template_name, {"space_panels": space_panels})


class BundleStartView(LoginRequiredMixin, View):
    """POST-only endpoint the popup's JS submits both space + categories to
    in one request - what BundleSpaceView + BundleCategoryView otherwise do
    across two page loads, combined since the popup collects both in one
    flow."""

    def post(self, request, *args, **kwargs):
        space = request.POST.get("space")
        if space not in dict(Bundle.Space.choices):
            return JsonResponse({"error": "Pick a valid space."}, status=400)

        available_ids = {
            item_type.id
            for item_type, is_available in available_item_types_for_space(space)
            if is_available
        }
        try:
            item_type_ids = [int(pk) for pk in request.POST.getlist("categories")]
        except ValueError:
            return JsonResponse({"error": "Invalid category selection."}, status=400)
        item_type_ids = [pk for pk in item_type_ids if pk in available_ids]
        if not item_type_ids:
            return JsonResponse(
                {"error": "Select at least one category."}, status=400
            )

        with db_transaction.atomic():
            bundle = Bundle.objects.create(
                buyer=request.user, space=space, status=Bundle.Status.DRAFT
            )
            BundleCategory.objects.bulk_create(
                [
                    BundleCategory(bundle=bundle, item_type_id=pk)
                    for pk in item_type_ids
                ]
            )

        request.session["bundle_wizard"] = {"space": space, "bundle_id": bundle.id}
        return JsonResponse(
            {"redirect_url": f"{reverse('bundles:generating')}?bundle={bundle.id}"}
        )


class BundleSpaceView(LoginRequiredMixin, FormView):
    """Screen 1 (full-page fallback for no-JS/logged-out visitors - the
    popup above is the primary path for everyone else). Pick the space
    being furnished."""

    template_name = "bundles/select_space.html"
    form_class = SpaceSelectForm

    def form_valid(self, form):
        self.request.session["bundle_wizard"] = {"space": form.cleaned_data["space"]}
        return redirect(reverse("bundles:select_categories"))


class BundleCategoryView(LoginRequiredMixin, FormView):
    """Screen 2: pick requested item types for the chosen space. Creates
    the Bundle + BundleCategory rows and triggers tier generation once
    categories are submitted - nothing is persisted before this step."""

    template_name = "bundles/select_categories.html"
    form_class = CategorySelectForm

    def dispatch(self, request, *args, **kwargs):
        wizard = request.session.get("bundle_wizard") or {}
        self.space = wizard.get("space")
        if not self.space:
            messages.info(request, "Pick a space to get started.")
            return redirect(reverse("bundles:select_space"))
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["space"] = self.space
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["space"] = self.space
        context["space_label"] = dict(Bundle.Space.choices).get(self.space, self.space)
        context["available_pairs"] = available_item_types_for_space(self.space)
        return context

    def form_valid(self, form):
        item_type_ids = [int(pk) for pk in form.cleaned_data["categories"]]

        with db_transaction.atomic():
            bundle = Bundle.objects.create(
                buyer=self.request.user, space=self.space, status=Bundle.Status.DRAFT
            )
            BundleCategory.objects.bulk_create(
                [
                    BundleCategory(bundle=bundle, item_type_id=item_type_id)
                    for item_type_id in item_type_ids
                ]
            )

        self.request.session["bundle_wizard"] = {
            "space": self.space,
            "bundle_id": bundle.id,
        }

        # Generation (a real, possibly slow LLM call) does NOT happen here -
        # it happens on the "Generating..." interstitial page's fetch call,
        # so the buyer sees a waiting animation for the actual duration of
        # the call instead of the browser just hanging on this POST.
        return redirect(f"{reverse('bundles:generating')}?bundle={bundle.id}")


class BundleGeneratingView(LoginRequiredMixin, View):
    """Interstitial shown while the (possibly slow, real-LLM-backed) tier
    generation runs. Renders instantly with a waiting animation; its own
    JS fires the actual generation via BundleGenerateView and navigates on
    to the builder once that resolves. If generation was already cached
    (e.g. the buyer navigated back here), skip straight to the builder -
    and if JS never runs (disabled/blocked), the page's <noscript> link
    still reaches the builder, which computes generation itself as a
    fallback (see _compute_and_cache_generation), just without the
    animation."""

    template_name = "bundles/generating.html"

    def get(self, request, *args, **kwargs):
        bundle = self._get_bundle(request)
        generations = request.session.get("bundle_generations") or {}
        if str(bundle.id) in generations:
            return redirect(f"{reverse('bundles:builder')}?bundle={bundle.id}")
        return render(request, self.template_name, {"bundle": bundle})

    def _get_bundle(self, request):
        bundle_id = request.GET.get("bundle") or (
            request.session.get("bundle_wizard") or {}
        ).get("bundle_id")
        return get_object_or_404(Bundle, pk=bundle_id, buyer=request.user)


class BundleGenerateView(LoginRequiredMixin, View):
    """POST-only endpoint the generating page's JS calls to actually run
    generation and get back where to go next."""

    def post(self, request, *args, **kwargs):
        bundle_id = request.POST.get("bundle") or request.GET.get("bundle")
        bundle = get_object_or_404(Bundle, pk=bundle_id, buyer=request.user)

        generation = _compute_and_cache_generation(request, bundle)

        if not generation["tiers"]:
            messages.error(
                request,
                "None of the categories you picked currently have bundle-eligible "
                "listings. Try different categories.",
            )
            return JsonResponse(
                {"redirect_url": reverse("bundles:select_categories")}
            )

        return JsonResponse(
            {"redirect_url": f"{reverse('bundles:builder')}?bundle={bundle.id}"}
        )


class BundleBuilderView(LoginRequiredMixin, View):
    """Screen 3: switch between AI-generated tiers and swap items. The
    active tier's picks are kept persisted as this bundle's BundleItem
    rows (per the Part-4 doc: the DB represents the current working bundle,
    not every generated alternative)."""

    template_name = "bundles/builder.html"
    DEFAULT_TIER = "BEST_VALUE"

    def get(self, request, *args, **kwargs):
        bundle = self._get_bundle(request)
        if bundle.status != Bundle.Status.DRAFT:
            return redirect(f"{reverse('bundles:summary')}?bundle={bundle.id}")
        generation = self._get_generation(request, bundle)
        requested_tier = request.GET.get("tier")
        has_items = bundle.bundle_items.exists()

        # Only (re)sync from the tier's generated recipe on first load or an
        # actual tab switch - resyncing on every GET would silently discard
        # any manual swap the buyer just made, since a swap POST redirects
        # back to this same GET.
        if not has_items or (requested_tier and requested_tier != bundle.selected_tier):
            tier = requested_tier or bundle.selected_tier or self.DEFAULT_TIER
            self._sync_bundle_items(bundle, tier, generation)
        else:
            tier = bundle.selected_tier or self.DEFAULT_TIER

        return self._render(request, bundle, tier, generation)

    def post(self, request, *args, **kwargs):
        bundle = self._get_bundle(request)
        if bundle.status != Bundle.Status.DRAFT:
            return redirect(f"{reverse('bundles:summary')}?bundle={bundle.id}")
        generation = self._get_generation(request, bundle)
        tier = request.POST.get("tier") or bundle.selected_tier or self.DEFAULT_TIER

        if request.POST.get("action") == "swap":
            self._swap_item(request, bundle, generation)

        return redirect(f"{reverse('bundles:builder')}?bundle={bundle.id}&tier={tier}")

    def _get_bundle(self, request):
        bundle_id = request.GET.get("bundle") or (
            request.session.get("bundle_wizard") or {}
        ).get("bundle_id")
        return get_object_or_404(Bundle, pk=bundle_id, buyer=request.user)

    def _get_generation(self, request, bundle):
        generations = request.session.get("bundle_generations") or {}
        generation = generations.get(str(bundle.id))
        if generation is not None:
            return self._normalize_generation(generation)

        # Not cached - e.g. a bookmarked/no-JS visit that skipped the
        # generating interstitial. Compute it now (blocking) as a fallback.
        return _compute_and_cache_generation(request, bundle)

    def _normalize_generation(self, generation):
        """Django's session backend round-trips through JSON, which
        silently turns dict keys into strings - a generation freshly
        computed this request has int item_type_id keys, but one read back
        from the session has string keys. Coerce back to int so
        item_type_id lookups (e.g. current_by_type.get(item_type_id) in
        _render) work regardless of where the generation came from."""
        return {
            **generation,
            "tiers": {
                tier: {
                    **tier_data,
                    "items": {
                        int(item_type_id): listing_id
                        for item_type_id, listing_id in tier_data["items"].items()
                    },
                }
                for tier, tier_data in generation["tiers"].items()
            },
        }

    def _sync_bundle_items(self, bundle, tier, generation):
        tier_data = generation["tiers"].get(tier)
        if tier_data is None:
            return

        with db_transaction.atomic():
            bundle.bundle_items.all().delete()
            for listing_id in tier_data["items"].values():
                listing = Listing.objects.get(pk=listing_id)
                BundleItem.objects.create(
                    bundle=bundle,
                    listing=listing,
                    listing_price_snapshot=listing.listing_price,
                    proposed_bundle_price=listing.listing_price,
                    item_status=BundleItem.ItemStatus.SELECTED,
                )
            bundle.selected_tier = tier
            bundle.save(update_fields=["selected_tier", "updated_at"])

    def _swap_item(self, request, bundle, generation):
        try:
            item_type_id = int(request.POST.get("item_type_id"))
            new_listing_id = int(request.POST.get("listing_id"))
        except (TypeError, ValueError):
            return

        current_item = bundle.bundle_items.filter(
            listing__item_type_id=item_type_id
        ).first()
        new_listing = (
            Listing.objects.filter(
                pk=new_listing_id,
                item_type_id=item_type_id,
                status=Listing.Status.ACTIVE,
                bundle_eligible=True,
            )
            .exclude(seller=bundle.buyer)
            .first()
        )
        if new_listing is None:
            messages.error(request, "That item is no longer available to swap in.")
            return

        with db_transaction.atomic():
            if current_item is not None:
                current_item.delete()
            BundleItem.objects.create(
                bundle=bundle,
                listing=new_listing,
                listing_price_snapshot=new_listing.listing_price,
                proposed_bundle_price=new_listing.listing_price,
                item_status=BundleItem.ItemStatus.SELECTED,
            )

    def _render(self, request, bundle, tier, generation):
        bundle_items = list(
            bundle.bundle_items.select_related("listing__item_type", "listing__seller")
        )
        current_by_type = {item.listing.item_type_id: item for item in bundle_items}

        categories = []
        for item_type_id, item_type_name in self._tiers_by_type(generation).items():
            current_item = current_by_type.get(item_type_id)
            candidates = (
                Listing.objects.filter(
                    item_type_id=item_type_id,
                    status=Listing.Status.ACTIVE,
                    bundle_eligible=True,
                )
                .exclude(seller=bundle.buyer)
                .exclude(pk=current_item.listing_id if current_item else None)
            )
            categories.append(
                {
                    "item_type_id": item_type_id,
                    "item_type_name": item_type_name,
                    "current_item": current_item,
                    "swap_candidates": candidates,
                }
            )

        individual_total = sum(
            (item.listing.listing_price for item in bundle_items), start=0
        )

        context = {
            "bundle": bundle,
            "active_tier": tier,
            "tier_choices": Bundle.Tier.choices,
            "rationale": (generation["tiers"].get(tier) or {}).get("rationale", ""),
            "generation_source": generation.get("source"),
            "missing_categories": generation.get("missing_categories") or [],
            "categories": categories,
            "bundle_items": bundle_items,
            "items_count": len(bundle_items),
            "minimum_items": MINIMUM_BUNDLE_ITEMS,
            "individual_total": individual_total,
        }
        return render(request, self.template_name, context)

    def _tiers_by_type(self, generation):
        item_type_ids = set()
        for tier_data in generation["tiers"].values():
            item_type_ids.update(tier_data["items"].keys())
        names = dict(
            ItemType.objects.filter(id__in=item_type_ids).values_list(
                "id", "item_type_name"
            )
        )
        return {
            item_type_id: names.get(item_type_id, "") for item_type_id in item_type_ids
        }


class BundleSummaryView(LoginRequiredMixin, View):
    """Screen 4: review the finalized bundle and send requests to sellers."""

    template_name = "bundles/summary.html"

    def get(self, request, *args, **kwargs):
        bundle = self._get_bundle(request)
        bundle_items = list(
            bundle.bundle_items.select_related("listing__item_type", "listing__seller")
        )

        if (
            bundle.status == Bundle.Status.DRAFT
            and len(bundle_items) < MINIMUM_BUNDLE_ITEMS
        ):
            messages.info(
                request,
                f"Add at least {MINIMUM_BUNDLE_ITEMS} items to unlock bundle checkout.",
            )
            return redirect(f"{reverse('bundles:builder')}?bundle={bundle.id}")

        total = sum((item.listing.listing_price for item in bundle_items), start=0)
        context = {
            "bundle": bundle,
            "bundle_items": bundle_items,
            "total": total,
            "sent": bundle.status != Bundle.Status.DRAFT,
        }
        return render(request, self.template_name, context)

    def post(self, request, *args, **kwargs):
        bundle = self._get_bundle(request)
        bundle_items = list(bundle.bundle_items.select_related("listing__seller"))

        if len(bundle_items) < MINIMUM_BUNDLE_ITEMS:
            messages.error(
                request,
                f"Add at least {MINIMUM_BUNDLE_ITEMS} items before checking out.",
            )
            return redirect(f"{reverse('bundles:builder')}?bundle={bundle.id}")

        with db_transaction.atomic():
            for item in bundle_items:
                listing = item.listing
                conversation, _ = Conversation.objects.get_or_create(
                    buyer=request.user,
                    seller=listing.seller,
                    listing=listing,
                    defaults={
                        "bundle_item": item,
                        "last_message_at": timezone.now(),
                    },
                )
                if conversation.bundle_item_id is None:
                    conversation.bundle_item = item
                    conversation.last_message_at = timezone.now()
                    conversation.save(update_fields=["bundle_item", "last_message_at"])

                Message.objects.create(
                    conversation=conversation,
                    sender=request.user,
                    body_text=(
                        f"Hi! I'd like to buy your {listing.title} for "
                        f"${listing.listing_price} as part of a "
                        f"{bundle.get_space_display()} bundle."
                    ),
                )
                item.item_status = BundleItem.ItemStatus.REQUESTED
                item.save(update_fields=["item_status"])

            bundle.status = Bundle.Status.REQUESTS_SENT
            bundle.save(update_fields=["status", "updated_at"])

        messages.success(request, "Requests sent! Sellers will respond soon.")
        return redirect(f"{reverse('bundles:summary')}?bundle={bundle.id}")

    def _get_bundle(self, request):
        bundle_id = request.GET.get("bundle") or (
            request.session.get("bundle_wizard") or {}
        ).get("bundle_id")
        return get_object_or_404(Bundle, pk=bundle_id, buyer=request.user)
