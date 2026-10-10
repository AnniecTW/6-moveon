"""Local mock data only; the ordinary authentication and access rules apply."""

from .base import *

DEBUG = True
ALLOWED_HOSTS = ["127.0.0.1"]
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "data" / "a5-preview.sqlite3",
    }
}
MEDIA_ROOT = BASE_DIR / "data" / "a5-preview-media"
EMAIL_BACKEND = "marketplace.mail_backends.ReadableConsoleEmailBackend"
DEFAULT_FROM_EMAIL = "MoveOn mock preview <no-reply@moveon.local>"
EMAIL_HOST_USER = ""
EMAIL_HOST_PASSWORD = ""

# These are disabled at the base/environment boundary too, before .env is read.
GOOGLE_CLIENT_ID = ""
GOOGLE_CLIENT_SECRET = ""
GEMINI_API_KEY = ""
