"""Print what Gemini actually does for this project's key and model.

Run: python manage.py diagnose_gemini
Makes at most three small calls with no SDK retries, so each failure is
reported once with its real error type, message and elapsed time.
"""

import time

from django.conf import settings
from django.core.management.base import BaseCommand

from bundles.services import GEMINI_MODEL_NAME


class Command(BaseCommand):
    help = "Diagnose Gemini connectivity, model name, latency and errors."

    def handle(self, *args, **options):
        import google.generativeai as genai

        api_key = getattr(settings, "GEMINI_API_KEY", "")
        if not api_key:
            self.stdout.write(self.style.ERROR("GEMINI_API_KEY is empty in settings/.env."))
            return
        genai.configure(api_key=api_key)
        self.stdout.write(f"SDK google-generativeai {genai.__version__}; configured model: {GEMINI_MODEL_NAME}")

        self.stdout.write("\n1) Does the key list the configured model?")
        try:
            names = [m.name.removeprefix("models/") for m in genai.list_models()
                     if "generateContent" in m.supported_generation_methods]
            self.stdout.write(f"   {len(names)} models support generateContent.")
            found = GEMINI_MODEL_NAME in names
            self.stdout.write((self.style.SUCCESS if found else self.style.ERROR)(
                f"   '{GEMINI_MODEL_NAME}' {'is' if found else 'is NOT'} available."))
            self.stdout.write("   Available: " + ", ".join(sorted(names)))
        except Exception as exc:
            self.stdout.write(self.style.ERROR(f"   list_models failed: {type(exc).__name__}: {exc}"))

        real_prompt = self._safe_real_prompt()
        chain = list(getattr(settings, "GEMINI_MODEL_CHAIN", None) or [GEMINI_MODEL_NAME])
        self.stdout.write(f"\nModel chain: {', '.join(chain)}")
        for model in chain:
            for label, prompt in (("tiny prompt", 'Reply with only this JSON: {"ok": true}'),
                                  ("real prompt", real_prompt)):
                self.stdout.write(f"\n[{model}] {label} ({len(prompt)} chars)")
                started = time.monotonic()
                try:
                    response = genai.GenerativeModel(model).generate_content(
                        prompt,
                        generation_config=genai.GenerationConfig(response_mime_type="application/json"),
                        request_options={"timeout": 60, "retry": None},
                    )
                    self.stdout.write(self.style.SUCCESS(
                        f"   OK in {time.monotonic() - started:.1f}s; usage: {getattr(response, 'usage_metadata', None)}"))
                except Exception as exc:
                    self.stdout.write(self.style.ERROR(
                        f"   FAILED after {time.monotonic() - started:.1f}s: {type(exc).__name__}: {exc}"))

    def _safe_real_prompt(self):
        try:
            return self._real_prompt()
        except Exception as exc:
            self.stdout.write(self.style.WARNING(
                f"\n(Could not build a real prompt: {type(exc).__name__}. "
                "Run migrate and the seed commands first. Using a tiny prompt instead.)"))
            return "Reply with only this JSON: {\"ok\": true}"

    def _real_prompt(self):
        from marketplace.models import Listing
        from bundles.services import _build_prompt, _eligible_candidates
        from marketplace.models import ItemType

        type_ids = list(ItemType.objects.filter(
            listings__status=Listing.Status.ACTIVE, listings__bundle_eligible=True
        ).distinct().values_list("id", flat=True)[:8])
        by_type = {k: v for k, v in _eligible_candidates(type_ids, buyer=None).items() if v}
        return _build_prompt("LIVING_ROOM", by_type) if by_type else "Reply with only: {}"
