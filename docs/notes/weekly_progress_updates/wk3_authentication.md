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

### Google sign-in setup and verification

Google sign-in requires a Google Cloud OAuth Web application Client ID. If the
team has not created one, leave `GOOGLE_CLIENT_ID` unset or empty: real Google
sign-in cannot be used, and the account page shows **Continue with Google** as
disabled with an app-configuration explanation. Username/campus-email
registration, MoveOn's
six-digit email code, password login, and password reset still work. With the
default console mail backend, the code is printed in `runserver`; this tests
the workflow but does not prove control of a real mailbox.

To test the actual Google sign-in flow locally:

1. A developer or team owner creates or selects a Google Cloud project,
   configures its OAuth consent/branding information, and creates an OAuth
   client of type **Web application**. The consent screen's support email is
   an app contact, not the campus email eligibility check. Each student user
   does not create a Cloud project, and the MoveOn site does not need to be
   deployed before local testing. See [Google's setup guide](https://developers.google.com/identity/gsi/web/guides/get-google-api-clientid).
2. Add the exact browser origin under **Authorized JavaScript origins**. For
   port 8000, add `http://localhost` and `http://localhost:8000`; if using
   `http://127.0.0.1:8000` in the browser, add it separately. An origin has
   scheme, host, and port, with no `/account/` path. Add the deployed HTTPS
   origin when the site is deployed. This implementation uses a JavaScript
   callback and posts the ID token to Django, so it does not use an OAuth
   redirect URI or client secret.
3. Put the Web application **Client ID** in the local, Git-ignored `.env`,
   alongside `SECRET_KEY`, then restart `runserver`:

   ```env
   GOOGLE_CLIENT_ID=your-web-client-id.apps.googleusercontent.com
   ```

4. Open `/account/` on the same origin, click the enabled Google button, and
   select a Google account that reports a verified `@illinois.edu` email.
   Django verifies the returned ID token with `google-auth` against this
   Client ID. On first use, MoveOn creates a local account with an unusable
   password, then requires its **own** campus email code before student access.
   After that verification, try Google sign-in again and confirm login and
   logout. An existing MoveOn password account with the same email is not
   silently linked; use its password login instead. A personal Gmail address
   does not satisfy MoveOn's campus-email rule.

Google's `email_verified` claim and an `@illinois.edu` suffix alone do not mark
the MoveOn campus email as verified. This is Google account authentication,
not Illinois SSO or proof of current enrollment. If the Google popup is blank
or `/gsi/transform` does not complete, check the exact authorized origin and
browser console; the account page already sets the popup-compatible COOP
header when a Client ID is configured. [Google's token-verification guide](https://developers.google.com/identity/gsi/web/guides/verify-google-id-token)
explains the ID-token and email-ownership limits. Real Google OAuth and real
mailbox delivery must each be checked with external configuration; mocked
Google tests alone do not establish either result. School SSO remains a future
integration.

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
