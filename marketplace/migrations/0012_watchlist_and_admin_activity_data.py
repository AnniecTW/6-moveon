from datetime import timedelta
from decimal import Decimal

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models
from django.utils import timezone


def seed_admin_activity(apps, schema_editor):
    # Retain migration history without introducing demo data on deployment.
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("bundles", "0003_bundlecategory_plural_name"),
        ("marketplace", "0011_transaction_id_and_conversation"),
        ("messaging", "0005_remove_conversation_lifecycle_statuses"),
    ]

    operations = [
        migrations.CreateModel(
            name="WatchlistItem",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "listing",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="watchlist_entries",
                        to="marketplace.listing",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="watchlist_items",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.AddConstraint(
            model_name="watchlistitem",
            constraint=models.UniqueConstraint(
                fields=("user", "listing"),
                name="unique_listing_per_user_watchlist",
            ),
        ),
        migrations.RunPython(seed_admin_activity, migrations.RunPython.noop),
    ]
