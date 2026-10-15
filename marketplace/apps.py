import logging
import os
import sys

from django.apps import AppConfig


logger = logging.getLogger(__name__)


class MarketplaceConfig(AppConfig):
    name = "marketplace"

    def ready(self):
        # Django imports apps for tests and management commands too. Warm only
        # in the actual runserver process, or when another server opts in.
        is_runserver = "runserver" in sys.argv
        is_serving_process = os.environ.get("RUN_MAIN") == "true" or "--noreload" in sys.argv
        if not ((is_runserver and is_serving_process) or
                os.environ.get("MOVEON_PRELOAD_PRICING") == "1"):
            return
        try:
            from .pricing.semantic import _model

            _model()
        except Exception:
            logger.exception("Pricing search model could not be preloaded; manual item-type selection remains available")
