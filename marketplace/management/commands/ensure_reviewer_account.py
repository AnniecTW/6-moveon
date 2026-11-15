"""Create or update the staff account course reviewers use to open the AI dashboard.

Usage (the password is prompted for, or read from an environment variable,
so it never appears in shell history or the repository):

    python manage.py ensure_reviewer_account --username mohitg2
    REVIEWER_PASSWORD=... python manage.py ensure_reviewer_account --username mohitg2 --password-env REVIEWER_PASSWORD

The account is staff (dashboard access) but not a superuser (no admin powers).
It uses a non-campus address, so it reaches only public pages and staff pages
such as /analytics/ai-search/; it cannot act as a student on the marketplace.
"""

import os
from getpass import getpass

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from marketplace.models import User


class Command(BaseCommand):
    help = "Create or update a staff reviewer account for the AI search analytics dashboard."

    def add_arguments(self, parser):
        parser.add_argument("--username", default="mohitg2")
        parser.add_argument("--email", help="Defaults to <username>@reviewer.moveon.invalid.")
        parser.add_argument("--display-name", default="Course reviewer")
        parser.add_argument("--password-env", metavar="VARIABLE",
                            help="Read the password from this environment variable instead of prompting.")

    def handle(self, *args, **options):
        username = options["username"].strip()
        if not username:
            raise CommandError("--username cannot be blank.")
        email = options["email"] or f"{username}@reviewer.moveon.invalid"
        password = self._password(options["password_env"])
        with transaction.atomic():
            user = User.objects.filter(username=username).first()
            created = user is None
            if created:
                if User.objects.filter(email__iexact=email).exists():
                    raise CommandError(f"Another account already uses {email}.")
                user = User(username=username, email=email)
            user.display_name = options["display_name"]
            user.is_active = True
            user.is_staff = True
            # Dashboard access only; no Django admin superpowers.
            user.is_superuser = False
            user.account_status = User.AccountStatus.ACTIVE
            # The course specifies this password, so Django's strength validators are not applied.
            user.set_password(password)
            user.save()
            # Saving can reset verification when the email changes, so mark it afterwards.
            User.objects.filter(pk=user.pk).update(email_verified=True, email_verified_at=timezone.now())
        action = "Created" if created else "Updated"
        self.stdout.write(self.style.SUCCESS(
            f"{action} staff reviewer '{username}'. Dashboard: /analytics/ai-search/"
        ))

    def _password(self, variable):
        if variable:
            password = os.environ.get(variable, "")
            if not password:
                raise CommandError(f"Environment variable {variable} is empty or not set.")
            return password
        password = getpass("Reviewer password: ")
        if not password:
            raise CommandError("The password cannot be blank.")
        if getpass("Repeat password: ") != password:
            raise CommandError("The passwords did not match.")
        return password
