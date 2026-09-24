import uuid

from django.db import migrations, models


def populate_listing_data(apps, schema_editor):
    Listing = apps.get_model("marketplace", "Listing")
    database = schema_editor.connection.alias
    for listing in Listing.objects.using(database).filter(listing_id__isnull=True).iterator():
        Listing.objects.using(database).filter(pk=listing.pk).update(listing_id=uuid.uuid4())


class Migration(migrations.Migration):
    dependencies = [
        ("marketplace", "0008_listing_pricing_plan"),
    ]

    operations = [
        migrations.AddField(
            model_name="listing",
            name="listing_id",
            field=models.UUIDField(editable=False, null=True),
        ),
        migrations.RunPython(populate_listing_data, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="listing",
            name="listing_id",
            field=models.UUIDField(default=uuid.uuid4, editable=False, unique=True),
        ),
    ]
