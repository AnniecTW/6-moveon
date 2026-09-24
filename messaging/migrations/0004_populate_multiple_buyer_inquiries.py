from django.db import migrations


def populate_multiple_buyer_inquiries(apps, schema_editor):
    # Retain migration history without introducing demo data on deployment.
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("messaging", "0003_conversation_statuses_and_public_id"),
    ]

    operations = [
        migrations.RunPython(
            populate_multiple_buyer_inquiries,
            migrations.RunPython.noop,
        ),
    ]
