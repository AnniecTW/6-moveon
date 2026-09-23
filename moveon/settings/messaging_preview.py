"""Local-only Messaging preview backed by an isolated SQLite database."""

from .development import *

DATABASES["default"]["NAME"] = BASE_DIR / "data" / "messaging_preview.sqlite3"
MEDIA_ROOT = BASE_DIR / "data" / "messaging_preview_media"
EMAIL_BACKEND = "marketplace.mail_backends.ReadableConsoleEmailBackend"
