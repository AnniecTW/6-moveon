from .base import *

DEBUG = True
# Local CPU inference is too slow for interactive search. Keep embeddings live.
LOCAL_LLM_ENABLED = env.bool("LOCAL_LLM_ENABLED", default=False)
ALLOWED_HOSTS = ["localhost", "127.0.0.1"]

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "local_console": {
            "format": "%(asctime)s %(levelname)s %(name)s: %(message)s",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "local_console",
        },
    },
    "loggers": {
        "marketplace.local_llm": {
            "handlers": ["console"],
            "level": "DEBUG",
            "propagate": False,
        },
        "marketplace.browse": {
            "handlers": ["console"],
            "level": "DEBUG",
            "propagate": False,
        },
    },
}

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / env("DATABASE_PATH", default="data/db.sqlite3"),
    }
}
