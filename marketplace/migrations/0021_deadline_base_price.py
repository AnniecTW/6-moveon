from django.db import migrations, models
from django.db.models.functions import Coalesce


def fill_existing_bases(apps, schema_editor):
    Listing = apps.get_model("marketplace", "Listing")
    Listing.objects.using(schema_editor.connection.alias).update(
        deadline_base_price=Coalesce("deadline_start_price", "listing_price")
    )


class Migration(migrations.Migration):
    dependencies = [
        ("marketplace", "0020_urgent_deadline_floor"),
    ]

    operations = [
        migrations.AddField(
            model_name="listing",
            name="deadline_base_price",
            field=models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True),
        ),
        migrations.RunPython(fill_existing_bases, migrations.RunPython.noop),
    ]
