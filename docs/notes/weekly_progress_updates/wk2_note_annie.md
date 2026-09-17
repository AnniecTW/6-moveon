## Environment Security Update

- Updated Django entry points to default to `moveon.settings.development`, with production selectable through `DJANGO_SETTINGS_MODULE`.

- Each teammate should generate a personal Django secret key with:
    `python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"`
- Paste the generated value into the existing local `.env` as `SECRET_KEY=...`. Never commit `.env`.