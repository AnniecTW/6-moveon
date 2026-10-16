"""Mirror MoveOn's campus-email proof into allauth's account metadata."""

from allauth.account.models import EmailAddress

from .auth_backend import has_campus_access


def sync_campus_email(user, *, existing_only=False):
    """Keep one primary email; provider claims cannot grant campus access."""
    database = user._state.db or "default"
    addresses = EmailAddress.objects.using(database).filter(user_id=user.pk)
    if existing_only and not addresses.exists():
        return
    email = user.email.strip().lower()
    addresses.exclude(email=email).update(primary=False, verified=False)
    return EmailAddress.objects.using(database).update_or_create(
        user_id=user.pk,
        email=email,
        defaults={"primary": True, "verified": has_campus_access(user)},
    )[0]
