from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("marketplace", "0006_remove_either_fulfillment"),
    ]

    operations = [
        migrations.AddField(
            model_name="listing",
            name="views",
            field=models.PositiveIntegerField(default=0),
        ),
    ]
