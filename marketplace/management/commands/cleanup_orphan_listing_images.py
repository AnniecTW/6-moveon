from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from marketplace.models import ListingImage


class Command(BaseCommand):
    help = "Deletes unattached listing images older than 24 hours."

    def handle(self, *args, **options):
        cutoff = timezone.now() - timedelta(hours=24)
        images = ListingImage.objects.filter(
            listing__isnull=True,
            created_at__lt=cutoff,
        )
        deleted = 0
        for image in images.iterator():
            image.delete()
            deleted += 1
        self.stdout.write(self.style.SUCCESS(f"Deleted {deleted} orphan listing image(s)."))
