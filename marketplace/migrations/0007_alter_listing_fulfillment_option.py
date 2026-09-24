from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("marketplace", "0006_remove_either_fulfillment"),
    ]

    operations = [
        migrations.AlterField(
            model_name="listing",
            name="fulfillment_option",
            field=models.CharField(
                choices=[
                    ("PICKUP", "Pickup"),
                    ("DELIVERY", "Delivery"),
                    ("BOTH", "Pickup / Delivery"),
                ],
                max_length=20,
            ),
        ),
    ]
