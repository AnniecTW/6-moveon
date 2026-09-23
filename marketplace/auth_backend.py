from django.contrib.auth.backends import ModelBackend
from django.db.models import Q
from django.views.decorators.debug import sensitive_variables

from .models import User


def account_usable(user):
    return user.is_active and user.account_status == User.AccountStatus.ACTIVE


def has_campus_access(user):
    return (
        account_usable(user)
        and user.email_verified
        and user.email_verified_at is not None
        and user.email.lower().endswith("@illinois.edu")
    )


@sensitive_variables("password")
def credential_user(identifier, password):
    """Find the single account named by a username or campus email and password."""
    if not identifier or password is None:
        return None
    matches = list(User.objects.filter(
        Q(username=identifier) | Q(email__iexact=identifier)
    ).order_by("pk")[:2])
    if len(matches) != 1:
        # Keep missing and ambiguous identifiers close to password-check cost.
        User().set_password(password)
        return None
    user = matches[0]
    return user if user.check_password(password) else None


class CampusModelBackend(ModelBackend):
    @sensitive_variables("password")
    def authenticate(self, request, username=None, password=None, **kwargs):
        identifier = username or kwargs.get(User.USERNAME_FIELD)
        user = credential_user(identifier, password)
        if user is not None and self.user_can_authenticate(user):
            return user
        return None

    def user_can_authenticate(self, user):
        return super().user_can_authenticate(user) and account_usable(user)
