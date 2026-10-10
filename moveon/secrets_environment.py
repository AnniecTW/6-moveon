# ==================================================

# This file is responsible for loading secret configuration values
# (API keys, database URLs, OAuth credentials, etc.) into Django.
#
# We use the ⁠ django-environ ⁠ library to read these values from a ⁠ .env ⁠ file
# and convert them into operating system environment variables.
#
# This lets us:
#   • Keep secrets out of GitHub
#   • Use different settings for development vs production
#   • Use the same codebase everywhere
#
# Example: If .env contains
#   OPENAI_API_KEY=sk-abc123
#
# then this library makes it available in Django as:
#   os.environ["OPENAI_API_KEY"]
#
# which we can access safely in base.py using:
#   os.getenv("OPENAI_API_KEY")
#
# ==================================================

import environ
import os
import secrets
from pathlib import Path

# Create an environment reader object
# This object knows how to load key=value pairs from .env
# and expose them as OS environment variables.
def is_a5_preview_settings():
    return os.environ.get("DJANGO_SETTINGS_MODULE") == "moveon.settings.a5_preview"


# The mock preview does not read .env. Its temporary session key is local only;
# restarting the preview requires a new login and verification-code request.
env = (environ.Env(SECRET_KEY=(str, secrets.token_urlsafe(50)))
       if is_a5_preview_settings() else environ.Env())

# Find project root (folder that contains manage.py and .env)
# IMPORTANT: Even though BASE_DIR exists in base.py, it does not exist yet when secrets_environment.py runs.
BASE_DIR = Path(__file__).resolve().parent.parent

# Load .env from project root
if not is_a5_preview_settings():
    environ.Env.read_env(BASE_DIR / ".env")
