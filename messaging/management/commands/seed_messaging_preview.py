"""Seed only the isolated local preview database with sign-in test accounts."""

import secrets

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from marketplace.models import User


class Command(BaseCommand):
    help = "Seed Messaging preview data and print temporary local account passwords."

    def handle(self, *args, **options):
        if settings.DATABASES["default"]["NAME"].name != "messaging_preview.sqlite3":
            raise CommandError("This command runs only with moveon.settings.messaging_preview.")
        call_command("seed_demo_data", stdout=self.stdout)
        for username in ("alex", "maya"):
            user = User.objects.get(username=username)
            user.email = f"{username}@illinois.edu"
            user.save(update_fields=["email"])
            password = secrets.token_urlsafe(12)
            user.set_password(password)
            user.email_verified = True
            user.email_verified_at = timezone.now()
            user.save(update_fields=["password", "email_verified", "email_verified_at"])
            self.stdout.write(f"Local preview account {username}: {password}")
