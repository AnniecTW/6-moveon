from django.db import migrations, models
from django.db.models import Q
from django.utils import timezone


def expire_legacy_pending(apps, schema_editor):
    Recommendation = apps.get_model("marketplace", "PriceRecommendation")
    Recommendation.objects.using(schema_editor.connection.alias).filter(
        status="PENDING"
    ).update(status="EXPIRED", responded_at=timezone.now())


class Migration(migrations.Migration):
    dependencies = [("marketplace", "0017_listing_initial_valuation")]

    operations = [
        migrations.AddField("listing", "deadline_start_date", models.DateField(blank=True, null=True)),
        migrations.AddField("listing", "deadline_end_date", models.DateField(blank=True, null=True)),
        migrations.AddField("listing", "deadline_start_price", models.DecimalField(blank=True, null=True, max_digits=8, decimal_places=2)),
        migrations.AddField("listing", "deadline_floor", models.DecimalField(blank=True, null=True, max_digits=8, decimal_places=2)),
        migrations.AddField("listing", "deadline_gamma", models.DecimalField(blank=True, null=True, max_digits=4, decimal_places=2)),
        migrations.AddField("listing", "deadline_policy_version", models.CharField(blank=True, max_length=32)),
        migrations.AddField("listing", "deadline_below_floor_opt_in", models.BooleanField(default=False)),
        migrations.AddField("listing", "deadline_revision", models.PositiveIntegerField(default=0)),
        migrations.AddField("pricerecommendation", "rationale", models.TextField(blank=True)),
        migrations.AddField("pricerecommendation", "policy_version", models.CharField(blank=True, max_length=32)),
        migrations.AddField("pricerecommendation", "schedule_revision", models.PositiveIntegerField(default=0)),
        migrations.AddField("pricerecommendation", "schedule_date", models.DateField(blank=True, null=True)),
        migrations.AddField("pricerecommendation", "below_floor", models.BooleanField(default=False)),
        migrations.RunPython(expire_legacy_pending, migrations.RunPython.noop),
        migrations.AddConstraint("pricerecommendation", models.UniqueConstraint(fields=["listing"], condition=Q(status="PENDING"), name="one_pending_deadline_rec")),
    ]
