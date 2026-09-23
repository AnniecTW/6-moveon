from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("messaging", "0004_populate_multiple_buyer_inquiries"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="conversation",
            name="buyer_status",
        ),
        migrations.RemoveField(
            model_name="conversation",
            name="seller_status",
        ),
    ]
