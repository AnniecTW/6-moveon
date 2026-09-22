

def _seller_profile(user):
    """Keep shared account details in one context shape for future dashboards."""
    return {
        "name": user.display_name or user.get_username(),
        "initial": (user.display_name or user.get_username() or "?")[0].upper(),
        "verified": user.email_verified,
        # These profile fields do not exist in the current schema yet.
        "program": "Academic profile not set",
        "rating": "4.9",
        "review_count": 8,
        "meetup": "Preferred meetup not set",
    }


def _pricing_plan(listing, today):
    """Present a useful plan label until a dedicated pricing-plan field exists."""
    if listing.move_out_date and (listing.move_out_date - today).days <= 7:
        return "Sell before I move", "Next review in 2 days"
    if listing.price_recommendations.all():
        return "Maximize value", "Next review based on activity"
    return "Balanced", "Next review based on activity"


def _demo_view_count(listing):
    """Deterministic placeholder until listing-view events are modeled."""
    return (listing.pk % 47) + 1


def _seller_dashboard_context(user):
    """Shared, model-backed context for every Seller dashboard route."""
    active_listings = Listing.objects.filter(
        seller=user, status=Listing.Status.ACTIVE
    )
    completed_sales = Transaction.objects.filter(
        seller=user, status=Transaction.Status.COMPLETED
    )
    return {
        "profile": _seller_profile(user),
        "active_count": active_listings.count(),
        # TODO: Replace with a Sum over a future ListingView/event model.
        "total_views": sum(_demo_view_count(item) for item in active_listings),
        "inquiries": Conversation.objects.filter(seller=user).count(),
        "avg_days_to_sell": 0 if not completed_sales.exists() else 14,
    }


def _seven_day_views(total, today):
    """Shape deterministic demo views for a replaceable analytics boundary."""
    days = [today - timedelta(days=offset) for offset in range(6, -1, -1)]
    labels = [f"{day.strftime('%b')} {day.day}" for day in days]
    weights = [8, 10, 9, 12, 11, 14, 16]
    weight_total = sum(weights)
    values = [round(total * weight / weight_total) for weight in weights]
    if values:
        values[-1] += total - sum(values)
    return labels, values


def _fallback_price_events(listings, labels):
    """Demo annotations used only when no recorded applied recommendation exists."""
    candidates = list(listings[:2])
    event_indexes = [2, 5]
    events = []
    for index, listing in enumerate(candidates):
        old_price = listing.retail_price or listing.listing_price
        if old_price == listing.listing_price:
            old_price = listing.listing_price + 5
        events.append(
            {
                "listing_id": listing.pk,
                "listing_title": listing.title,
                "date": labels[event_indexes[index]],
                "old_price": float(old_price),
                "new_price": float(listing.listing_price),
                "temporary": True,
            }
        )
    return events


def _seller_insights_context(user):
    today = date.today()
    listings = list(
        Listing.objects.filter(seller=user)
        .select_related("item_type", "item_type__category")
        .annotate(inquiry_count=Count("conversations", distinct=True))
    )
    active_listings = [item for item in listings if item.status == Listing.Status.ACTIVE]
    for listing in listings:
        listing.view_count = _demo_view_count(listing)
        listing.display_image_url = listing.image_url or (
            static("img/reference/" + ASSETS[listing.title])
            if listing.title in ASSETS
            else ""
        )

    total_views = sum(item.view_count for item in active_listings)
    total_inquiries = sum(item.inquiry_count for item in listings)
    sales = Transaction.objects.filter(
        seller=user, status=Transaction.Status.COMPLETED
    )
    sold_count = sales.count()
    bundle_sales = sales.filter(bundle__isnull=False).count()
    top_performer = max(active_listings, key=lambda item: item.view_count, default=None)
    labels, view_values = _seven_day_views(total_views, today)

    recorded_events = []
    recommendations = PriceRecommendation.objects.filter(
        listing__seller=user,
        status__in=[PriceRecommendation.Status.ACCEPTED, PriceRecommendation.Status.MODIFIED],
    ).select_related("listing")
    for recommendation in recommendations:
        applied_price = recommendation.applied_price or recommendation.recommended_price
        event_date = recommendation.responded_at or recommendation.generated_at
        label = f"{event_date.strftime('%b')} {event_date.day}"
        if label in labels:
            recorded_events.append(
                {
                    "listing_id": recommendation.listing_id,
                    "listing_title": recommendation.listing.title,
                    "date": label,
                    "old_price": float(recommendation.previous_price),
                    "new_price": float(applied_price),
                    "temporary": False,
                }
            )
    price_events = recorded_events or _fallback_price_events(active_listings, labels)

    inquiry_rows = sorted(
        listings, key=lambda item: (item.inquiry_count, item.view_count), reverse=True
    )[:4]
    category_counts = {}
    for listing in active_listings:
        category = listing.item_type.category.category_name
        category_counts[category] = category_counts.get(category, 0) + 1

    inquiry_rate = round(total_inquiries / total_views * 100, 1) if total_views else 0
    sales_rate = round(sold_count / total_inquiries * 100, 1) if total_inquiries else 0
    chart_data = {
        "selected_listing_id": None,
        "views_over_time": {
            "labels": labels,
            "views": view_values,
            "price_events": price_events,
            "temporary": True,
        },
        "inquiries_by_listing": {
            "labels": [item.title for item in inquiry_rows],
            "values": [item.inquiry_count for item in inquiry_rows],
        },
        "category_performance": {
            "labels": list(category_counts),
            "values": list(category_counts.values()),
        },
    }
    return {
        **_seller_dashboard_context(user),
        "active_seller_tab": "insights",
        "summary_metrics": [
            {"value": total_views, "label": "Total views", "change": "+12% vs. previous week", "temporary": True},
            {"value": total_inquiries, "label": "Inquiries", "change": "From listing conversations"},
            {"value": sold_count, "label": "Items sold", "change": "Completed transactions"},
            {"value": bundle_sales, "label": "Bundle sales", "change": "Completed bundle transactions"},
        ],
        "top_performer": top_performer,
        "funnel": [
            {"value": total_views, "label": "Views", "rate": "100%"},
            {"value": total_inquiries, "label": "Inquiries", "rate": f"{inquiry_rate}%"},
            {"value": sold_count, "label": "Sold", "rate": f"{sales_rate}% of inquiries"},
        ],
        "chart_data": chart_data,
        "analytics_uses_demo_views": True,
    }


def _money(value):
    return Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP)


def _seller_pricing_context(user):
    today = date.today()
    listings = (
        Listing.objects.filter(seller=user, status=Listing.Status.ACTIVE)
        .select_related("item_type", "item_type__category")
        .prefetch_related("price_recommendations")
        .annotate(inquiry_count=Count("conversations", distinct=True))
    )
    pricing_rows = []
    for listing in listings:
        listing.display_image_url = listing.image_url or (
            static("img/reference/" + ASSETS[listing.title])
            if listing.title in ASSETS
            else ""
        )
        days_remaining = (
            max((listing.move_out_date - today).days, 0)
            if listing.move_out_date
            else None
        )
        strategy, review_note = _pricing_plan(listing, today)
        strategy_key = {
            "Maximize value": "maximize",
            "Balanced": "balanced",
            "Sell before I move": "sell-before-move",
        }[strategy]

        comparable_is_temporary = not (
            listing.benchmark_low is not None and listing.benchmark_high is not None
        )
        comparable_low = listing.benchmark_low or _money(
            listing.listing_price * Decimal("0.82")
        )
        comparable_high = listing.benchmark_high or _money(
            listing.listing_price * Decimal("0.94")
        )

        recommendations = list(listing.price_recommendations.all())
        latest = recommendations[0] if recommendations else None
        recommendation_is_temporary = latest is None
        suggested_price = (
            latest.applied_price or latest.recommended_price
            if latest
            else comparable_high
        )
        if latest:
            reason = "MoveOn has a recorded recommendation based on this listing's pricing history."
            recommendation_state = latest.get_status_display()
        elif days_remaining is not None and days_remaining <= 7:
            reason = "Your move-out date is close, so a more competitive price may improve the chance of selling in time."
            recommendation_state = "Review suggested"
        elif listing.listing_price > comparable_high:
            reason = "The current price is above the estimated range for similar listings, while buyer inquiries remain limited."
            recommendation_state = "Review suggested"
        else:
            reason = "Your price is aligned with similar listings. Keep monitoring activity before making a change."
            recommendation_state = "On track"

        pricing_rows.append(
            {
                "listing": listing,
                "current_price": listing.listing_price,
                "comparable_low": comparable_low,
                "comparable_high": comparable_high,
                "comparable_is_temporary": comparable_is_temporary,
                "days_remaining": days_remaining,
                "strategy": strategy,
                "strategy_key": strategy_key,
                "review_note": review_note,
                "recommendation": {
                    "suggested_price": suggested_price,
                    "reason": reason,
                    "state": recommendation_state,
                    "temporary": recommendation_is_temporary,
                },
            }
        )

    return {
        **_seller_dashboard_context(user),
        "active_seller_tab": "pricing",
        "pricing_rows": pricing_rows,
        # User-level selling preferences are not represented in the schema yet.
        "default_preferences": {
            "strategy": "balanced",
            "protect_minimum": any(item.minimum_price is not None for item in listings),
            "sell_no_matter_what": any(item.sell_no_matter_what for item in listings),
            "bundle_eligible": any(item.bundle_eligible for item in listings),
        },
        "preferences_are_temporary": True,
    }


@login_required
def seller_listings_view(request):
    today = date.today()
    listings = (
        Listing.objects.filter(seller=request.user)
        .select_related("item_type", "item_type__category")
        .prefetch_related("price_recommendations")
        .annotate(inquiry_count=Count("conversations", distinct=True))
    )
    query = request.GET.get("q", "").strip()
    status = request.GET.get("status", "ACTIVE")
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
        listing.display_image_url = listing.image_url or (
            static("img/reference/" + ASSETS[listing.title])
            if listing.title in ASSETS
            else ""
        )
        plan, review_note = _pricing_plan(listing, today)
        listing.plan = plan
        listing.review_note = review_note
        # Listing view events are not modeled yet; keep this demo metric explicit.
        listing.view_count = _demo_view_count(listing)
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
            **_seller_dashboard_context(request.user),
            "active_seller_tab": "listings",
            "listings": listing_rows,
            "categories": Listing.objects.filter(seller=request.user)
            .values("item_type__category_id", "item_type__category__category_name")
            .distinct(),
            "selected_category": category,
            "selected_status": status,
            "selected_ordering": ordering,
        },
    )


@login_required
def seller_insights_view(request):
    return render(
        request,
        "marketplace/seller_insights.html",
        _seller_insights_context(request.user),
    )


@login_required
def seller_pricing_view(request):
    return render(
        request,
        "marketplace/seller_pricing.html",
        _seller_pricing_context(request.user),
    )


def _seller_settings_initial(request):
    return request.session.get(
        "seller_settings",
        {
            "payment_preference": "meetup",
            "primary_meetup": "",
            "alternate_meetup": "",
            "delivery_preference": "pickup",
            "delivery_notes": "",
            "notify_inquiries": True,
            "notify_bundles": True,
            "notify_pricing": True,
            "notify_moveout": True,
            "notify_transactions": True,
        },
    )


@login_required
def seller_settings_view(request):
    initial = _seller_settings_initial(request)
    form = SellerSettingsForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        request.session["seller_settings"] = form.cleaned_data
        messages.success(
            request,
            "Seller preferences saved for this session. Database persistence is not connected yet.",
        )
        return redirect("seller-settings")
    return render(
        request,
        "marketplace/seller_settings.html",
        {
            **_seller_dashboard_context(request.user),
            "active_seller_tab": "settings",
            "settings_form": form,
            "settings_are_temporary": True,
        },
    )


def _pickup_image(listing):
    bundle_image_fallbacks = {
        "Desk Chair": "rocking-chair.png",
        "Gray Rug": "gray-pillow.png",
        "Floor Lamp": "desk-lamp.png",
        "Blue Sofa": "living-room-clean.png",
    }
    asset = ASSETS.get(listing.title) or bundle_image_fallbacks.get(listing.title)
    return listing.image_url or (static("img/reference/" + asset) if asset else "")


def _transaction_reference_value(transaction):
    return (
        transaction.benchmark_price_snapshot
        or transaction.listing.retail_price
        or transaction.listing.benchmark_price
        or transaction.agreed_price
    )


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
    pickup_rows = []
    for transaction in pending:
        estimated_value = _transaction_reference_value(transaction)
        pickup_rows.append(
            {
                "transaction_id": transaction.pk,
                "listing": transaction.listing,
                "image_url": _pickup_image(transaction.listing),
                "agreed_price": transaction.agreed_price,
                "savings": max(estimated_value - transaction.agreed_price, Decimal("0")),
                "seller": transaction.seller,
                "meetup_datetime": transaction.meetup_datetime,
                "meetup_location": transaction.meetup_location,
                "status_label": transaction.get_status_display(),
                "temporary": False,
            }
        )

    pickup_data_is_temporary = False
    if not pickup_rows:
        demo_listing = (
            Listing.objects.filter(status=Listing.Status.ACTIVE)
            .exclude(seller=user)
            .select_related("seller", "item_type", "item_type__category")
            .first()
        )
        if demo_listing:
            estimated_value = (
                demo_listing.retail_price
                or demo_listing.benchmark_price
                or demo_listing.listing_price
            )
            pickup_rows.append(
                {
                    "transaction_id": None,
                    "listing": demo_listing,
                    "image_url": _pickup_image(demo_listing),
                    "agreed_price": demo_listing.listing_price,
                    "savings": max(
                        estimated_value - demo_listing.listing_price, Decimal("0")
                    ),
                    "seller": demo_listing.seller,
                    "meetup_datetime": timezone.now() + timedelta(days=2),
                    "meetup_location": "Illini Union",
                    "status_label": "Pickup scheduled",
                    "temporary": True,
                }
            )
            pickup_data_is_temporary = True

    amount_paid = sum((item.agreed_price for item in purchases), Decimal("0"))
    estimated_value = sum(
        (
            _transaction_reference_value(item)
        )
        for item in purchases
    )
    total_saved = max(estimated_value - amount_paid, Decimal("0"))
    if pickup_data_is_temporary:
        amount_paid = sum(
            (item["agreed_price"] for item in pickup_rows), Decimal("0")
        )
        total_saved = sum((item["savings"] for item in pickup_rows), Decimal("0"))
        estimated_value = amount_paid + total_saved
    chart_max = max(amount_paid, total_saved, Decimal("1"))
    spent_bar_height = round(float(amount_paid / chart_max) * 100)
    savings_bar_height = round(float(total_saved / chart_max) * 100)
    chart_points = [
        {
            "type": (
                "pickup"
                if transaction.status == Transaction.Status.PENDING_PICKUP
                else "history"
            ),
            "date": (
                transaction.completed_at or transaction.created_at
            ).date().isoformat(),
            "spent": float(transaction.agreed_price),
            "saved": float(
                max(
                    _transaction_reference_value(transaction)
                    - transaction.agreed_price,
                    Decimal("0"),
                )
            ),
        }
        for transaction in purchases
        if transaction.status
        in (Transaction.Status.PENDING_PICKUP, Transaction.Status.COMPLETED)
    ]
    if pickup_data_is_temporary:
        chart_points = [
            {
                "type": "pickup",
                "date": timezone.localdate().isoformat(),
                "spent": float(row["agreed_price"]),
                "saved": float(row["savings"]),
            }
            for row in pickup_rows
        ]
    return {
        "profile": _seller_profile(user),
        "active_buyer_tab": "pickups",
        "buyer_summary": {
            "total_saved": total_saved,
            "items_bought": len(pickup_rows) if pickup_data_is_temporary else len(purchases),
            "pending_pickups": len(pickup_rows) if pickup_data_is_temporary else len(pending),
            "saved_bundles": Bundle.objects.filter(buyer=user)
            .exclude(status=Bundle.Status.CANCELLED)
            .count(),
            "amount_paid": amount_paid,
            "estimated_value": estimated_value,
            "chart_max": chart_max,
            "spent_bar_height": spent_bar_height,
            "savings_bar_height": savings_bar_height,
            "chart_points": chart_points,
        },
        "pickup_rows": pickup_rows,
        "pickup_data_is_temporary": pickup_data_is_temporary,
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
    bundle_data_is_temporary = False
    if not bundles:
        preview = (
            Bundle.objects.exclude(status=Bundle.Status.CANCELLED)
            .prefetch_related(
                "bundle_items__listing__seller",
                "bundle_items__listing__item_type__category",
            )
            .first()
        )
        if preview:
            bundles = [preview]
            bundle_data_is_temporary = True

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
            reference_value = (
                item.listing.retail_price
                or item.listing.benchmark_price
                or item.listing_price_snapshot
            )
            confirmed = item.item_status == item.ItemStatus.ACCEPTED
            confirmed_count += int(confirmed)
            current_total += item_price
            estimated_value += reference_value
            item_rows.append(
                {
                    "item": item,
                    "image_url": _pickup_image(item.listing),
                    "price": item_price,
                    "confirmed": confirmed,
                    "status_label": (
                        "Confirmed" if confirmed else "Pending Seller Response"
                    ),
                }
            )
        target_budget = _money(current_total * Decimal("1.20"))
        saved_amount = max(estimated_value - current_total, Decimal("0"))
        total_items = len(item_rows)
        progress_percent = (
            round(confirmed_count / total_items * 100) if total_items else 0
        )
        bundle_rows.append(
            {
                "bundle": bundle,
                "name": f"{bundle.get_space_display()} Move-In Bundle",
                "items": item_rows,
                "target_budget": target_budget,
                "current_total": current_total,
                "saved_amount": saved_amount,
                "confirmed_count": confirmed_count,
                "total_items": total_items,
                "progress_percent": progress_percent,
                "temporary": bundle_data_is_temporary,
                "target_is_temporary": True,
            }
        )

    context.update(
        {
            "active_buyer_tab": "bundles",
            "bundle_rows": bundle_rows,
            "bundle_data_is_temporary": bundle_data_is_temporary,
        }
    )
    if bundle_data_is_temporary:
        context["buyer_summary"] = {
            **context["buyer_summary"],
            "saved_bundles": len(bundle_rows),
        }
    return context


def _purchase_history_rows(transactions, temporary=False):
    rows = []
    for transaction in transactions:
        reference_value = _transaction_reference_value(transaction)
        rows.append(
            {
                "transaction": transaction,
                "image_url": _pickup_image(transaction.listing),
                "purchase_date": transaction.completed_at or transaction.created_at,
                "reference_value": reference_value,
                "savings": max(reference_value - transaction.agreed_price, Decimal("0")),
                "temporary": temporary,
            }
        )
    return rows


def _buyer_purchase_history_context(user):
    context = _buyer_pickups_context(user)
    transactions = list(
        Transaction.objects.filter(buyer=user, status=Transaction.Status.COMPLETED)
        .select_related("listing", "listing__item_type", "listing__item_type__category", "seller")
        .order_by("-completed_at", "-created_at")
    )
    history_is_temporary = False
    if not transactions:
        preview = (
            Transaction.objects.filter(status=Transaction.Status.COMPLETED)
            .select_related("listing", "listing__item_type", "listing__item_type__category", "seller")
            .order_by("-completed_at", "-created_at")
            .first()
        )
        if preview:
            transactions = [preview]
            history_is_temporary = True
    history_rows = _purchase_history_rows(transactions, history_is_temporary)
    context.update(
        {
            "active_buyer_tab": "history",
            "history_rows": history_rows,
            "history_is_temporary": history_is_temporary,
            "history_totals": {
                "spent": sum(
                    (row["transaction"].agreed_price for row in history_rows),
                    Decimal("0"),
                ),
                "saved": sum(
                    (row["savings"] for row in history_rows), Decimal("0")
                ),
            },
        }
    )
    return context


def _buyer_watchlist_context(user):
    context = _buyer_pickups_context(user)
    listings = list(
        Listing.objects.filter(status=Listing.Status.ACTIVE)
        .exclude(seller=user)
        .select_related("seller", "item_type", "item_type__category")
        .order_by("-created_at", "pk")
    )
    for listing in listings:
        listing.display_image_url = _pickup_image(listing)
        listing.reference_value = (
            listing.retail_price or listing.benchmark_price or listing.listing_price
        )
        listing.discount_percent = discount_percent(
            listing.reference_value, listing.listing_price
        )
    context.update(
        {
            "active_buyer_tab": "watchlist",
            "watchlist_candidates": listings,
            "watchlist_categories": sorted(
                {
                    listing.item_type.category.category_name
                    for listing in listings
                }
            ),
            "watchlist_is_browser_local": True,
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
        _buyer_purchase_history_context(request.user),
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
                reference_value,
                max(reference_value - transaction.agreed_price, Decimal("0")),
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
