import uuid

import django.db.models.deletion
from django.db import migrations, models


def populate_transaction_links(apps, schema_editor):
    Transaction = apps.get_model("marketplace", "Transaction")
    Conversation = apps.get_model("messaging", "Conversation")
    for transaction in Transaction.objects.all():
        conversation = Conversation.objects.filter(
            buyer_id=transaction.buyer_id,
            seller_id=transaction.seller_id,
            listing_id=transaction.listing_id,
        ).first()
        Transaction.objects.filter(pk=transaction.pk).update(
            transaction_id=uuid.uuid4(),
            conversation_id=conversation.pk if conversation else None,
        )


class Migration(migrations.Migration):
    dependencies = [
        ("marketplace", "0010_listing_image"),
        ("messaging", "0005_remove_conversation_lifecycle_statuses"),
    ]

    operations = [
        migrations.AddField(
            model_name="transaction",
            name="conversation",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="transactions",
                to="messaging.conversation",
            ),
        ),
        migrations.AddField(
            model_name="transaction",
            name="transaction_id",
            field=models.UUIDField(editable=False, null=True),
        ),
        migrations.RunPython(populate_transaction_links, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="transaction",
            name="transaction_id",
            field=models.UUIDField(default=uuid.uuid4, editable=False, unique=True),
        ),
    ]
