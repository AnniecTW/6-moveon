# Week 3: Account access and Admin

This update covers phase one: registration, login, campus email verification,
password reset, the Google login entry point, and Django Admin access. It does
not implement Messaging.

## Access rules

MoveOn uses one `User` model and distinguishes three checks:

| Check | Requirement |
| --- | --- |
| Account usable | `is_active=True` and `account_status=ACTIVE` |
| Student feature access | Usable account, `@illinois.edu` email, and successful local email verification with a timestamp |
| Django Admin access | Usable account and Django staff permission; `createsuperuser` gives developer-created administrators full model permissions |

Public listing browsing remains available to guests. Routes not explicitly
listed as public in `marketplace/access_middleware.py` require student access by
default. An Admin session alone cannot open them. New public routes must be
added to that allowlist deliberately. Suspended or inactive accounts lose access
even when they already have a session.

`/admin/` is currently a Django route. A future deployment may restrict its
network exposure. This update does not add a separate administrator account
table, school SSO, or detailed staff roles. Admin user forms display email
verification status as read-only; a staff user cannot grant student access by
checking a box.

## Local workflow

Run the setup commands in the [README](../../../README.md) for a fresh local
database. Existing databases and demo listings do not need to be cleared.
For an administrator, run `python manage.py createsuperuser` once per fresh
database and use that account at `/admin/`. Its email need not be a campus
address. Use a personal password; no shared demo administrator is seeded.

To check student access, create a new account with a campus email, read the
six-digit verification code in the `runserver` terminal, enter it in the
account overlay, then log in and log out. A username or campus email works as
the login identifier. The code expires after 10 minutes, allows
five attempts, has a 60-second resend cooldown, and is invalidated after
success. It is generated and checked by Django and is bound to that account,
email, and verification request. With real delivery, entering the code proves
control of the mailbox for this MVP; reading it from the development console
only tests the workflow. Neither case proves current enrollment. Verification
alone does not log the user in.

Use **Forgot password?** to print a one-hour reset link in the terminal. Open
the link, set a new password, and log in again. A used or expired link is
invalid. Console output is a local demonstration, not proof of email delivery.

Fresh seed demo users use `@example.invalid` addresses and unusable passwords;
they remain listing and conversation data, not login shortcuts. Running the
seed commands again uses `get_or_create`, so it does not rewrite existing demo
user credentials. Legacy accounts with only `email_verified=True` still need a
verification timestamp before student access.

## Configuration

Development defaults to a readable console email backend. Automated auth
tests use Django's in-memory backend. For real mail delivery, configure the
following values in the local `.env` or deployment environment, using a
verified sender and credentials from the mail provider. `.env.example` lists
the variable names; do not place secrets in that tracked file.

```env
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=your-smtp-server
EMAIL_PORT=587
EMAIL_HOST_USER=your-smtp-login
EMAIL_HOST_PASSWORD=your-smtp-key
EMAIL_USE_TLS=True
DEFAULT_FROM_EMAIL=MoveOn <verified-sender@example.com>
```

For Brevo, `EMAIL_HOST_PASSWORD` is its SMTP key, not the account password or
API key. SMTP acceptance still needs confirmation through the provider logs
and a real inbox before real delivery can be marked tested.

Google sign-in needs a Google Cloud web client ID in `GOOGLE_CLIENT_ID` and
an authorized site origin. Django verifies the ID token. A Google account
does not gain student access merely from its email suffix or Google's
`email_verified` claim: MoveOn's own campus verification still applies.
Google login does not silently link an existing password account with the same
email. School SSO remains a future integration.

## Test evidence and remaining checks

```bash
python manage.py test tests.marketplace.test_auth
python manage.py test
python manage.py check
python manage.py makemigrations --check --dry-run
```

The full local suite passed 77 tests on 2026-09-23. It covers signup through
logout, code expiry and attempt limits, password reset and invalid links,
username and email login, blocked accounts, Google application logic with a
mock token verifier, and the Admin/student access boundary. `check` reported
no issues and `makemigrations --check --dry-run` reported no new changes.

Real SMTP delivery and a real Google OAuth round trip remain unverified until
their external credentials and origins are configured. The administrator's
existing local password still needs a manual `/admin/` browser check. No
Messaging behavior was changed in this update.
