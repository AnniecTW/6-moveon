from pathlib import Path

from django.conf import settings
from django.core.files import File
from django.db import migrations, models


ASSETS = {
    "Bookshelf": "bookshelf.png",
    "Coffee Table": "coffee-table.png",
    "Desk Lamp": "desk-lamp.png",
    "Oak Desk": "oak-desk.png",
    "Rocking Chair": "rocking-chair.png",
    "Throw Pillow": "gray-pillow.png",
}


def populate_listing_images(apps, schema_editor):
    # Retain migration history without introducing demo data on deployment.
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("marketplace", "0009_listing_listing_id_populate_profile_data"),
    ]

    operations = [
        migrations.AddField(
            model_name="listing",
            name="image",
            field=models.ImageField(blank=True, upload_to="listings/"),
        ),
        migrations.RunPython(populate_listing_images, migrations.RunPython.noop),
    ]
