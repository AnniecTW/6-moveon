import uuid

import django.db.models.deletion
from django.db import migrations, models


def populate_bundle_identifiers_and_items(apps, schema_editor):
    Bundle = apps.get_model("bundles", "Bundle")
    BundleCategory = apps.get_model("bundles", "BundleCategory")
    BundleItem = apps.get_model("bundles", "BundleItem")

    for bundle in Bundle.objects.all():
        Bundle.objects.filter(pk=bundle.pk).update(bundle_id=uuid.uuid4())

    for category in BundleCategory.objects.all():
        bundle_item = BundleItem.objects.filter(
            bundle_id=category.bundle_id,
            listing__item_type_id=category.item_type_id,
        ).first()
        if bundle_item:
            BundleCategory.objects.filter(pk=category.pk).update(
                bundle_item_id=bundle_item.pk
            )


class Migration(migrations.Migration):
    dependencies = [
        ("bundles", "0003_bundlecategory_plural_name"),
    ]

    operations = [
        migrations.AddField(
            model_name="bundle",
            name="bundle_id",
            field=models.UUIDField(editable=False, null=True),
        ),
        migrations.AddField(
            model_name="bundlecategory",
            name="bundle_item",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="category_requirements",
                to="bundles.bundleitem",
            ),
        ),
        migrations.RunPython(
            populate_bundle_identifiers_and_items,
            migrations.RunPython.noop,
        ),
        migrations.AlterField(
            model_name="bundle",
            name="bundle_id",
            field=models.UUIDField(default=uuid.uuid4, editable=False, unique=True),
        ),
    ]
