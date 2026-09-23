import hmac
import secrets
import uuid
from datetime import timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone
from django.utils.crypto import salted_hmac

from .models import EmailVerification, User

CODE_LIFETIME = timedelta(minutes=10)
RESEND_COOLDOWN = timedelta(seconds=60)
MAX_ATTEMPTS = 5


class EmailDeliveryError(Exception):
    pass


def _digest(user, request_id, code):
    value = f"campus-email:{user.pk}:{user.email.lower()}:{request_id}:{code}"
    return salted_hmac("moveon.email.verification", value).hexdigest()


def issue_code(user):
    """Send a fresh code. Return False during resend cooldown."""
    with transaction.atomic():
        current = EmailVerification.objects.select_for_update().filter(user=user).first()
        now = timezone.now()
        if current and now - current.sent_at < RESEND_COOLDOWN:
            return False
        code = f"{secrets.randbelow(1_000_000):06d}"
        request_id = uuid.uuid4()
        if current is None:
            current = EmailVerification(user=user)
        current.request_id = request_id
        current.code_digest = _digest(user, request_id, code)
        current.expires_at = now + CODE_LIFETIME
        current.sent_at = now
        current.attempts = 0
        current.save()
        try:
            delivered = send_mail(
                "Your MoveOn campus email code",
                f"Your MoveOn campus email verification code is {code}. It expires in 10 minutes.\n"
                "This code verifies email ownership; it does not log you in.",
                settings.DEFAULT_FROM_EMAIL,
                [user.email],
                fail_silently=False,
            )
        except Exception as exc:
            raise EmailDeliveryError("Email backend could not accept the message.") from exc
        if delivered != 1:
            raise EmailDeliveryError("Email backend did not accept the message.")
        return True


def consume_code(user, code):
    """Verify one code for this user's campus email. Return an error or None."""
    with transaction.atomic():
        challenge = EmailVerification.objects.select_for_update().filter(user=user).first()
        if challenge is None:
            return "Request a new code."
        if timezone.now() >= challenge.expires_at:
            return "The code has expired. Request a new code."
        if challenge.attempts >= MAX_ATTEMPTS:
            return "Too many attempts. Request a new code."
        challenge.attempts += 1
        challenge.save(update_fields=["attempts"])
        if not hmac.compare_digest(challenge.code_digest, _digest(user, challenge.request_id, code)):
            return "The code is invalid."
        if not user.is_active or user.account_status != User.AccountStatus.ACTIVE or not user.email.lower().endswith("@illinois.edu"):
            return "This account cannot be verified."
        user.email_verified = True
        user.email_verified_at = timezone.now()
        user.save(update_fields=["email_verified", "email_verified_at"])
        challenge.delete()
        return None
