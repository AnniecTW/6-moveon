from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def copy_legacy_image_urls(apps, schema_editor):
    Listing = apps.get_model("marketplace", "Listing")
    ListingImage = apps.get_model("marketplace", "ListingImage")
    database = schema_editor.connection.alias
    listings = (
        Listing.objects.using(database)
        .exclude(image_url__isnull=True)
        .exclude(image_url="")
        .iterator()
    )
    for listing in listings:
        ListingImage.objects.using(database).create(
            listing_id=listing.pk,
            uploaded_by_id=listing.seller_id,
            external_url=listing.image_url,
            position=0,
        )


def remove_copied_legacy_image_urls(apps, schema_editor):
    Listing = apps.get_model("marketplace", "Listing")
    ListingImage = apps.get_model("marketplace", "ListingImage")
    database = schema_editor.connection.alias
    for listing in Listing.objects.using(database).all().iterator():
        if listing.image_url:
            ListingImage.objects.using(database).filter(
                listing_id=listing.pk,
                uploaded_by_id=listing.seller_id,
                external_url=listing.image_url,
                position=0,
            ).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("marketplace", "0009_merge_20260923_2240"),
    ]

    operations = [
        migrations.CreateModel(
            name="ListingImage",
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
                (
                    "image",
                    models.ImageField(
                        blank=True,
                        upload_to="listing_images/%Y/%m/",
                    ),
                ),
                ("external_url", models.URLField(blank=True)),
                ("position", models.PositiveSmallIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "listing",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="images",
                        to="marketplace.listing",
                    ),
                ),
                (
                    "uploaded_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="listing_images",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={"ordering": ["position", "id"]},
        ),
        migrations.RunPython(copy_legacy_image_urls, remove_copied_legacy_image_urls),
    ]
