import uuid

from django.db import migrations, models


def populate_conversations(apps, schema_editor):
    Conversation = apps.get_model("messaging", "Conversation")
    database = schema_editor.connection.alias
    for conversation in Conversation.objects.using(database).filter(conversation_uid__isnull=True).iterator():
        Conversation.objects.using(database).filter(pk=conversation.pk).update(conversation_uid=uuid.uuid4())


class Migration(migrations.Migration):
    dependencies = [
        ("marketplace", "0009_listing_listing_id_populate_profile_data"),
        ("messaging", "0002_conversation_conversation_distinct_participants"),
    ]

    operations = [
        migrations.AddField(
            model_name="conversation",
            name="conversation_uid",
            field=models.UUIDField(editable=False, null=True),
        ),
        migrations.AddField(
            model_name="conversation",
            name="seller_status",
            field=models.CharField(
                blank=True,
                choices=[("SOLD", "Sold"), ("RESERVED", "Reserved")],
                default="",
                editable=False,
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="conversation",
            name="buyer_status",
            field=models.CharField(
                blank=True,
                choices=[
                    ("FOR_PICKUP", "For pick-up"),
                    ("ITEM_RECEIVED", "Item received"),
                ],
                default="",
                max_length=20,
            ),
        ),
        migrations.RunPython(populate_conversations, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="conversation",
            name="conversation_uid",
            field=models.UUIDField(default=uuid.uuid4, editable=False, unique=True),
        ),
    ]
