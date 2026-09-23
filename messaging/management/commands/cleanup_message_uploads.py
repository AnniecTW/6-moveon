"""Remove abandoned private uploads that were never sent."""

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from messaging.models import MessageImage


class Command(BaseCommand):
    help = "Delete message uploads older than 24 hours that are not attached to a message."

    def handle(self, *args, **options):
        stale = MessageImage.objects.filter(message__isnull=True,
            created_at__lt=timezone.now() - timedelta(hours=24))
        count = stale.count()
        stale.delete()
        self.stdout.write(f"Removed {count} abandoned message uploads.")
