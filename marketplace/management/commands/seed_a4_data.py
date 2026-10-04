"""Build repeatable fictional A4 examples on an empty or already-demo database."""

from datetime import datetime, timezone as datetime_timezone

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from marketplace.models import Listing, Transaction, User
from messaging.models import Conversation, Message


class Command(BaseCommand):
    help = "Seed fictional A4 listings and chart activity without login credentials."

    @transaction.atomic
    def handle(self, *args, **options):
        users = list(User.objects.all())
        if any(not user.email.endswith("@example.invalid") or
               user.has_usable_password() or user.is_staff or user.is_superuser or
               user.email_verified or user.google_subject for user in users):
            raise CommandError("Use a fresh database; existing non-demo accounts are preserved.")
        call_command("seed_demo_data", stdout=self.stdout)
        call_command("seed_featured_bundles", stdout=self.stdout)
        maya = User.objects.get(username="maya")
        for title, seller_name, amount, day in [
            ("Blue Sofa", "alex", 65, 21),
            ("Floor Lamp", "jamie", 15, 23),
            ("Desk", "alex", 33, 25),
        ]:
            listing = Listing.objects.get(title=title, seller__username=seller_name)
            completed_at = datetime(2026, 9, day, 12, tzinfo=datetime_timezone.utc)
            activity, _ = Transaction.objects.get_or_create(
                listing=listing, buyer=maya, seller=listing.seller,
                defaults={"agreed_price": amount, "status": Transaction.Status.COMPLETED,
                          "completed_at": completed_at},
            )
            Transaction.objects.filter(pk=activity.pk).update(created_at=completed_at)
        Transaction.objects.filter(seller=maya, listing__title="Desk Chair").update(
            completed_at=datetime(2026, 9, 27, 12, tzinfo=datetime_timezone.utc)
        )
        rug = Listing.objects.get(title="Gray Rug", seller=maya)
        Message.objects.filter(conversation__listing=rug,
                               conversation__buyer__username="alex").update(is_read=True)
        conversation, _ = Conversation.objects.get_or_create(
            listing=rug, seller=maya, buyer=User.objects.get(username="jamie")
        )
        Message.objects.get_or_create(
            conversation=conversation, sender=conversation.buyer,
            body_text="Fictional A4 inquiry: is pickup available?",
        )
        self.stdout.write(self.style.SUCCESS(
            "A4 demo ready: fictional identities, no usable passwords, "
            "Maya spent $113 and earned $18."
        ))
