from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("marketplace", "0016_consolidate_profile_images")]

    operations = [
        migrations.AddField(
            model_name="listing", name="brand",
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AddField(
            model_name="listing", name="valuation_metadata",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
