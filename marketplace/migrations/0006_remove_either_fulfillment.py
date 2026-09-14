from django.db import migrations, models

def migrate_either_to_pickup(apps, schema_editor):
    Listing = apps.get_model("marketplace", "Listing")
    Listing.objects.using(schema_editor.connection.alias).filter(
        fulfillment_option="EITHER").update(fulfillment_option="PICKUP")

class Migration(migrations.Migration):
    dependencies = [("marketplace", "0005_transaction_transaction_distinct_participants")]
    operations = [
        migrations.RunPython(migrate_either_to_pickup, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="listing", name="fulfillment_option",
            field=models.CharField(choices=[("PICKUP", "Pickup"), ("DELIVERY", "Delivery")], max_length=20)),
    ]

