from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("marketplace", "0007_listing_views"),
    ]

    operations = [
        migrations.AddField(
            model_name="listing",
            name="pricing_plan",
            field=models.CharField(
                blank=True,
                choices=[
                    ("BALANCED", "Balanced"),
                    ("MAXIMIZE_VALUE", "Maximize Value"),
                    ("SELL_BEFORE_MOVE", "Sell Before I Move"),
                ],
                default="",
                max_length=20,
            ),
        ),
    ]
