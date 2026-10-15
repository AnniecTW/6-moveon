"""Add research-backed category/type choices to the marketplace taxonomy."""

import csv

from django.core.management.base import BaseCommand
from django.db import transaction

from marketplace.models import ItemCategory, ItemType
from marketplace.pricing.initial import SOURCE_PATH, load_source, normalize


class Command(BaseCommand):
    help = "Add eligible MerRec category/type pairs without changing existing choices."

    def handle(self, *args, **options):
        records, _ = load_source()
        eligible = {(record.category, record.item_type) for record in records}
        labels = {}
        with SOURCE_PATH.open(encoding="utf-8-sig", newline="") as source:
            for row in csv.DictReader(source):
                key = (normalize(row["moveon_category"]), normalize(row["moveon_item_type"]))
                if key in eligible and key not in labels:
                    labels[key] = (row["moveon_category"].strip(), row["moveon_item_type"].strip())
        categories = {normalize(category.category_name): category
                      for category in ItemCategory.objects.all()}
        types = {(normalize(kind.category.category_name), normalize(kind.item_type_name))
                 for kind in ItemType.objects.select_related("category")}
        added_categories = added_types = 0
        with transaction.atomic():
            for key in sorted(labels):
                category_name, type_name = labels[key]
                category = categories.get(key[0])
                if category is None:
                    category = ItemCategory.objects.create(category_name=category_name)
                    categories[key[0]] = category
                    added_categories += 1
                if key not in types:
                    ItemType.objects.create(category=category, item_type_name=type_name)
                    types.add(key)
                    added_types += 1
        self.stdout.write(self.style.SUCCESS(
            f"Added {added_categories} categories and {added_types} item types "
            f"from {len(eligible)} eligible source-backed pairs."
        ))
