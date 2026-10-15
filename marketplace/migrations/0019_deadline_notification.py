from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("marketplace", "0018_deadline_pricing"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="DeadlineNotification",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("schedule_revision", models.PositiveIntegerField()),
                ("trigger_days", models.PositiveSmallIntegerField()),
                ("suggested_price_snapshot", models.DecimalField(decimal_places=2, max_digits=8)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("read_at", models.DateTimeField(blank=True, null=True)),
                ("resolved_at", models.DateTimeField(blank=True, null=True)),
                ("listing", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="deadline_notifications", to="marketplace.listing")),
                ("recommendation", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="inbox_notifications", to="marketplace.pricerecommendation")),
                ("seller", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="deadline_notifications", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "ordering": ["-created_at", "-pk"],
                "constraints": [models.UniqueConstraint(fields=("listing", "schedule_revision", "trigger_days"), name="unique_deadline_trigger")],
            },
        ),
    ]
