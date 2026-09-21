## Week 3 Progress - AI Bundle Builder (Srinath)

Branch: `week3-bundle-srinath`. This note is the merge context: what was built, the decisions behind it, what touches shared files, and what to reconcile when the login, profile, create-listing and messaging branches land.

### What was built

The Move-In Bundle flow, end to end, for a logged-in buyer:

1. Homepage "Try it!" (hero) opens a popup: pick a space, then pick categories.
2. A "Generating your bundles" screen (sparkle + dots animation) while the tiers are generated.
3. Bundle Builder: Budget / Best Value / Premium tabs, per-category cards, Swap.
4. Summary: item table and total, then "Send Requests to Sellers".

Checkout creates one `Conversation` per seller (get_or_create on buyer, seller, listing; sets `bundle_item`) plus one initial `Message`, marks each `BundleItem` REQUESTED and the `Bundle` REQUESTS_SENT. There is no messaging UI yet, so that data is the hook for the messaging feature.

Without JS or when logged out, "Try it!" falls back to full pages (`/bundles/select-space/`, `/bundles/select-categories/`), which still work.

### Files

New (bundle-only): `bundles/forms.py`, `services.py`, `space_categories.py`, `urls.py`; `templates/bundles/`; `static/css/bundles.css`, `static/css/bundles/wizard.css`; `static/js/bundles/` (`start-launcher.js`, `generating.js`); `templates/registration/login.html` (stopgap, see below). `bundles/views.py` and `bundles/tests.py` were empty scaffolds.

Existing files edited (conflict hotspots):
- `moveon/urls.py`: mock login/logout routes and `include("bundles.urls")`
- `moveon/settings/base.py`: `LOGIN_URL`, `LOGIN_REDIRECT_URL`, `LOGOUT_REDIRECT_URL`, `GEMINI_API_KEY`
- `requirements.txt` (google-generativeai), `.env.example` (GEMINI_API_KEY)
- `templates/marketplace/partials/_hero.html`: "Try it!" now launches the bundle popup (was `?bundle=on` filter link)
- `templates/marketplace/base.html`: one extra stylesheet link (`css/bundles/wizard.css`)
- `static/js/marketplace.js`: one import (`./bundles/start-launcher.js`)
- `marketplace/management/commands/seed_demo_data.py`: 4 new item types (Curtains, Coffee Table, Shelf, Decor) and 21 extra bundle-eligible listings
- `marketplace/test_browse.py`: seeded listing count assertion 8 -> 29

No model changes and no migrations were added.

### Decisions

- **Login is required.** `Bundle.buyer` and `Conversation.buyer` need a real user, and a buyer's own listings are excluded from their candidates. Views use `LoginRequiredMixin`.
- **Stopgap login is pushed as-is** (routes, `templates/registration/login.html`, `LOGIN_*` settings) so the flow can be tested now. It must be removed when the real login lands.
- **Pricing:** bundle total = plain sum of `listing_price`. No discount and no `minimum_price` use yet (deferred as a future add-on). The LLM never sets a price.
- **LLM job (Gemini, `gemini-3.6-flash`):** classify eligible listings per category into Budget / Best Value / Premium, and write a one-line rationale per tier. Inputs: price, condition, description, days until move-out, benchmark range, average completed sale price for that item type, latest PriceRecommendation status. Best Value is a holistic price/quality judgment, not a price midpoint.
- **Fallback:** if `GEMINI_API_KEY` is empty or the call fails, tiers are price-only (cheapest = Budget, median = Best Value, priciest = Premium). The builder shows a badge saying whether the pick was AI-generated or price-based.
- **One LLM call per bundle**, run from the generating screen via fetch and cached in the session. Swaps and tab switches never re-call it. Thin inventory: the same listing may repeat across tiers.
- **Move-out dates are not shown** to buyers in the builder; they are only model input for now (the price-reduction/notification feature is separate and out of scope).
- **Space/category lists** are a hardcoded map (`space_categories.py`), matched by item type name. Categories with no bundle-eligible listings show greyed out. Only Living Room was wireframed; other spaces are inferred.
- **No "browse on my own" mode.** Manual editing is the Swap on the AI-generated bundle.
- **UI:** reuses the homepage tokens/components (theme.css, components.css); popup reuses the native `<dialog>` pattern of the existing header dialog. Header shows inert Messages/Profile placeholder icons.
- **Tests never call Gemini:** `bundles/tests.py` forces `GEMINI_API_KEY=""`.

### Bugs found and fixed while building (regression tests exist)

- Session JSON turns dict keys into strings, which broke item-type matching in the builder (items existed but rendered as "No listing available").
- The builder GET re-synced items on every load and silently undid swaps.
- A buyer could be matched with their own listing (blocked later by `Conversation` validation).
- Multi-line `{# #}` comment in a Django template rendered as raw text (use `{% comment %}` for multi-line).

### Run it locally

```bash
conda activate moveon-env
pip install -r requirements.txt
python manage.py migrate
python manage.py seed_demo_data
python manage.py seed_featured_bundles   # homepage carousel needs this separately
# add GEMINI_API_KEY to .env (optional; blank = price-based fallback)
python manage.py runserver
```

Demo users (seed only): alex / jamie / sam / maya, password `password123`.

Tests: 60 total. One failure exists on `main` independent of this work (`marketplace.test_browse.BrowseTests.test_search_is_escaped_and_empty_state_works`, whitespace in the empty-state text).

### Merge checklist

1. **Login:** delete the mock routes in `moveon/urls.py` and `templates/registration/login.html` (same template path would shadow the real one). The real login must honour `?next=` and match `settings.LOGIN_URL`. Update `bundles/tests.py::test_anonymous_user_redirected_to_login` (uses `reverse("login")`).
2. **Messaging:** verify the `Conversation` / `Message` models and constraints are unchanged, then run `makemigrations --check`. Checkout code: `BundleSummaryView.post` in `bundles/views.py`. Update the checkout confirmation copy and link once the inbox exists.
3. **Create Listing:** must use the item type names in `space_categories.py` and set `bundle_eligible` and `status=ACTIVE`. Curtains/Coffee Table/Shelf/Decor exist only in `seed_demo_data`.
4. **Not built:** seller accept/decline of bundle requests (`BundleItem`/`Bundle` status transitions to ACCEPTED/DECLINED/PARTIALLY_ACCEPTED/CONFIRMED) and listing reservation.
5. **Security:** never run `seed_demo_data` in production (known-password users).
6. **Cross-app coupling:** `bundles.css` imports `marketplace/theme.css` and `components.css`; `marketplace.js` imports `bundles/start-launcher.js`.
7. **Header/UI:** replace the wizard header placeholder icons and homepage "coming soon" dialogs with real links when those pages exist.
8. Every developer needs their own `GEMINI_API_KEY` in `.env`.
