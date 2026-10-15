from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone

from marketplace.models import Listing, PriceRecommendation
from marketplace.pricing.deadline import evaluate_listing, notify_trigger


class Command(BaseCommand):
    help = "Create seller-reviewable deadline price recommendations for active listings."

    def handle(self, *args, **options):
        day = timezone.localdate()
        count = 0
        notified = 0
        ids = Listing.objects.filter(
            Q(status=Listing.Status.ACTIVE, move_out_date__gte=day,
              minimum_price__isnull=False) |
            Q(price_recommendations__status=PriceRecommendation.Status.PENDING)
        ).distinct().values_list("pk", flat=True).iterator()
        for listing_id in ids:
            recommendation = evaluate_listing(listing_id, day=day)
            if recommendation:
                count += 1
                if notify_trigger(listing_id, recommendation.pk, day=day):
                    notified += 1
        self.stdout.write(
            f"Evaluated deadline pricing for {day}; {count} pending recommendation(s), "
            f"{notified} milestone notification(s) present."
        )
