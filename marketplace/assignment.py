"""A4 presentation settings; never authenticate the fictional chart identity."""

from django.conf import settings
from django.contrib.auth import get_user_model


def context(request):
    return {"a4_assignment_mode": settings.A4_ASSIGNMENT_MODE}


def demo_user():
    return get_user_model().objects.filter(
        username=settings.A4_DEMO_USERNAME,
        email__endswith="@example.invalid",
        is_staff=False,
        is_superuser=False,
    ).first()
