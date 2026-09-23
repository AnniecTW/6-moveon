from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("bundles", "0002_initial"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="bundlecategory",
            options={
                "ordering": ["bundle", "item_type"],
                "verbose_name_plural": "Bundle categories",
            },
        ),
    ]
