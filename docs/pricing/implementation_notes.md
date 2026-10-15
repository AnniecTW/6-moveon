# Phase 1 implementation notes

Feature 1 is implemented. Features 2 and 3 remain untouched. The concise
status is in [implementation progress](IMPLEMENTATION_PROGRESS.md); this file
keeps the implementation history and file inventory. Source profiles and
statistical reports are under `validation/`.

The runtime engine (`marketplace/pricing/initial.py`) reads the unchanged
1,409-row CSV, excludes two explicit price-risk flags, calculates Decimal
matched medians and observed IQRs, and only computes a condition factor from
same-item-type observations with support on both sides. Sparse same-type
observations now produce a warned reference; the engine abstains when no
same-type observations exist. No age factor, universal depreciation, LLM price, or
claimed sale-probability estimate is used. Regression is implemented in the
reproducible analysis script, but is gated off in production because it has
higher MAE than the comparable baseline on the same chronological holdout.

The existing listing form and benchmark fields are reused. Migration 0017
adds optional seller-confirmed brand and JSON provenance/decision metadata to
`Listing`; no parallel listing model or form was introduced. A small read-only
preview endpoint serves the existing listing form. The form
recomputes the price server-side when saving. Seller price remains editable,
and acceptance cannot cross the seller's minimum. The former fixed price and
floor suggestions are removed. The price guide reports LOW or VERY LOW evidence because
the source is historical, US-wide, and not a verified completed-sale sample.

Original Phase 1 validation: `manage.py check` passed; `makemigrations --check --dry-run`
reported no changes; the analysis script completed; the 21 focused Django
tests and the full 196-test Django suite passed; Node syntax checking of the
new JavaScript passed. The CSV SHA-256 remains
`160c363b9df39c6007beecbfcfe1c49547ac7e4d3d9aaf5a3947bfdd2b8d7640`.
The derived CSV omits item titles. Deployment environments must apply
migration 0017. The local development database
was initialized with `manage.py migrate --noinput`; migration 0017 is applied
there and `manage.py check` passes afterward.

## Semantic item-type discovery addition

| Part | Implementation | Limit |
|---|---|---|
| Matching | `marketplace/pricing/semantic.py` embeds the seller's title/category/type and source-backed type descriptions with `all-MiniLM-L6-v2`; it ranks cosine scores and returns up to five types above provisional 0.40. | Similarity measures text, not price equivalence. The threshold has no labeled calibration yet. |
| Seller flow | Category and Item type are separate fields. The seller can select one suggested type or None; the latter keeps the manually selected type. | There may be fewer than five matches. |
| Price calculation | Existing `initial.recommend()` runs for the selected type and condition. Sparse observations now yield a warned reference median; no same-type observations still abstain. | The source has very little Furniture data; discovery cannot create missing comparables. |
| Provenance | Choice is saved in existing `valuation_metadata` JSON. | No migration needed. |

The local database initially had only 6 of the 42 source-backed category/type
pairs. `python manage.py sync_pricing_taxonomy` added 2 categories and 36 item
types and is idempotent. Run it after migrations in each deployment. It does
not copy historical prices into the listing table.

Files changed for this addition: `marketplace/pricing/semantic.py`,
`marketplace/forms.py`, `marketplace/views.py`, `marketplace/urls.py`,
`marketplace/apps.py`, `marketplace/test_initial_pricing.py`, `templates/marketplace/listing_form.html`,
`static/js/marketplace/type-suggestions.js`,
`static/js/marketplace/initial-price.js`, `static/css/marketplace/listing-form.css`, root `requirements.txt`, and this
document plus `IMPLEMENTATION_PROGRESS.md`, and
`marketplace/management/commands/sync_pricing_taxonomy.py`. The strategy documents and source
CSV remain unchanged.

The root requirements now include `sentence-transformers`; the experiment
requirements inherit it. The model is downloaded on first use. The available
Python environment for automated tests has Django but lacks the embedding
package and model. Tests therefore exercised the matching code with a
controlled encoder, the endpoint with mocked results and unavailable-model
behavior, and the real form/pricing path. Actual embedding precision, recall,
bookcase/bookshelf behavior, latency, and the 0.40 threshold still require
validation with a labeled set in the deployment environment. Until then,
suggestions are seller-reviewed discovery aids, not evidence of price accuracy.
Search now caches parsed CSV rows by file size/mtime and source-backed type
embeddings by catalog text in each server process. Only the query is embedded
on repeated searches. The browser uses a 650 ms pause and aborts superseded
requests. In this checkout, 20 CSV reads averaged 24.8 ms each; 20 cached
source calls averaged 1.3 ms each, including the initial read. This does not
measure actual model load or encoding latency because the model is unavailable
in the test environment. The first request can still download/load it.

The suggestion cards now override the broad input styles so radio controls
stay 16 px and cards remain compact. Selecting a candidate updates its
category/type and displays the actual price result or abstention explanation
beside the cards. A sparse candidate is marked as limited evidence before selection.
Choosing None restores the original manual category/type. The development
`runserver` process preloads the embedding model before serving requests;
other servers can opt in with `MOVEON_PRELOAD_PRICING=1`. Model loading may
make server startup slower, and live model load time has not been measured in
this checkout.

The updated Django suite passed 216 tests, including 31 focused pricing tests;
system and migration checks found no issues, and the new JavaScript passed
Node syntax checking.

## Price-selection latency update

- The suggestions endpoint now runs `initial.recommend()` for each returned
  candidate using the current condition and brand. It returns source-backed
  guides and abstentions with the candidates; it never creates a price from
  text similarity.
- Selecting a candidate renders that result immediately. If the condition or
  brand has changed since the search, the form requests a new guide. Saving
  recalculates the benchmark and retains seller minimum-price protection.
- The price endpoint and form save use the same parsed-source cache as semantic
  search. It is invalidated when the CSV size or modification time changes.
  A 30-call local calculation averaged 34.2 ms with repeated CSV parsing and
  1.2 ms with cached rows. These timings exclude HTTP and embedding time.
- Files changed for this update: `marketplace/views.py`, `marketplace/forms.py`,
  `marketplace/test_initial_pricing.py`, `static/js/marketplace/initial-price.js`,
  `static/js/marketplace/type-suggestions.js`, and these two documentation files.
  No migration or pricing-policy change is needed.

## Sparse price references (current policy)

- Policy `initial-v1.3` keeps the 8-record exact-condition and 10-record
  standard type-only rules. When these cannot apply but same-type records
  exist, it shows their observed median with **VERY LOW evidence**. It uses
  sparse condition matches when available; otherwise it uses all conditions
  and explicitly says the selected condition is not represented. No condition
  discount is invented. With no same-type records, it still abstains.
- The price card and selected-type result show a yellow warning with the exact
  reference count and reliability caveat. Sparse guides omit the observed
  middle-50% range. The seller can set another price; accepting a reference
  cannot cross their minimum. Save recalculates the reference and records its
  method, warning, evidence grade, source IDs, and seller decision.
- Storage Shelves & Racks has three source prices: $24 and $25 (New), $13
  (Like New). With Good selected, no Good match exists, so its provisional
  all-condition median is **$24.00**, marked VERY LOW evidence.
- On the chronological holdout, 281/282 items received a numeric type-only
  guide (MAE **$21.19**); 11 of those were sparse references (MAE **$10.75**).
  The condition-aware guide covered 281/282 (MAE **$21.22**), with 11 sparse
  references (MAE **$12.48**). Those 11 observations cannot validate sparse
  accuracy, and none of the source prices are confirmed sales.
- `run_phase1.py` now separates sparse-reference results in its report. The
  available test Python lacks NumPy, so that full script could not run here;
  the same chronological split and metrics were computed with Python's
  standard library. The old regression report/JSON describe the 12-record
  policy and are labeled historical. Re-run the script in the fully installed
  environment to refresh the current-policy JSON and regression comparison.
- Files changed for the sparse-reference update: `marketplace/pricing/initial.py`,
  `marketplace/pricing/semantic.py`, `marketplace/test_initial_pricing.py`,
  `templates/marketplace/listing_form.html`,
  `static/js/marketplace/initial-price.js`,
  `static/js/marketplace/type-suggestions.js`,
  `static/css/marketplace/listing-form.css`,
  `experiments/merrec-pricing/analysis/run_phase1.py`, these notes, and
  `validation/regression_diagnostics.md`. No migration is needed.

## Validation and reproducibility details

- The original CSV has **1,409** rows. Two explicit price-risk rows are
  excluded, leaving **1,407** eligible records. Its SHA-256 is
  `160c363b9df39c6007beecbfcfe1c49547ac7e4d3d9aaf5a3947bfdd2b8d7640`;
  the source file is unchanged. The chronological holdout has **282** items.
- Original same-row regression comparison under the old 12-record fallback:
  comparable median MAE **$21.72** and median absolute error **$10.36**;
  hedonic OLS MAE **$25.68** and median absolute error **$16.73** on the same
  **268** covered holdout items. Regression was not promoted. The design was
  full-rank (maximum VIF **2.83**), but Breusch–Pagan indicated uneven
  variance (p = **0.00194**) and **63** training observations exceeded the
  Cook's-distance screen. Independence cannot be fully checked without
  stable seller/product identifiers. See [regression diagnostics](validation/regression_diagnostics.md).
- Current sparse policy `initial-v1.3`: **281/282** holdout items receive a
  numeric guide, including **11** VERY LOW evidence references. Type-only
  MAE is **$21.19** and condition-aware MAE **$21.22** on their respective
  281 covered items. The 11 sparse cases are too few to validate sparse
  reliability. These labels are historical observed prices, not verified
  transactions or local sale outcomes.
- `python experiments/merrec-pricing/analysis/run_phase1.py` regenerates the
  cleaned table, profile, regression diagnostics, and evaluation JSON in an
  environment with the packages in the experiment requirements file. This
  checkout's available Python lacks NumPy, so the current full script was
  syntax-checked but not run. The current-policy holdout figures above were
  recomputed from the same chronological split with the standard library.
  The checked-in regression report and JSON remain labeled historical until
  the full analysis runs in the fully installed project environment.
- Current verification: **216** Django tests passed (**31** focused pricing
  tests); Django system check, migration consistency check, JavaScript syntax
  checks, and `git diff --check` passed. The local test interpreter lacks the
  embedding model, so semantic-ranking quality and live latency remain
  unmeasured. No migration was added for semantic matching or sparse guides.

## File inventory

Paths are relative to `6-moveon/`.

| Area | Files | Purpose |
|---|---|---|
| Pricing engine | `marketplace/pricing/initial.py`, `marketplace/pricing/semantic.py` | Source-backed medians, condition adjustment, sparse warnings, semantic type discovery |
| Analysis | `experiments/merrec-pricing/analysis/run_phase1.py`, `experiments/merrec-pricing/data/pricing_clean_v1.csv` | Reproducible cleaning and statistical evaluation |
| Model and migration | `marketplace/models.py`, `marketplace/migrations/0017_listing_initial_valuation.py` | Optional brand and saved recommendation provenance; migration 0017 must be applied in each environment |
| Django integration | `marketplace/forms.py`, `marketplace/views.py`, `marketplace/urls.py`, `marketplace/apps.py`, `marketplace/management/commands/sync_pricing_taxonomy.py` | Form validation, server recalculation, endpoints, model preload, and taxonomy sync |
| Listing form | `templates/marketplace/listing_form.html`, `static/js/marketplace/initial-price.js`, `static/js/marketplace/type-suggestions.js`, `static/css/marketplace/listing-form.css` | Live guide, seller choice, and yellow sparse warning within the existing design |
| Verification and dependencies | `marketplace/test_initial_pricing.py`, root `requirements.txt`, `experiments/merrec-pricing/requirements.txt` | Automated checks and reproducible packages |
| Documentation | `docs/pricing/IMPLEMENTATION_PROGRESS.md`, this file, and `docs/pricing/validation/` | Status, implementation record, data profile, and diagnostics |

Run `python manage.py migrate` and `python manage.py sync_pricing_taxonomy`
after deploying migration 0017. The taxonomy command is idempotent. No
duplicate Listing model, price service, or research-price table was added.
