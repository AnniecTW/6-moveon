# Week 4: A4 integration changes

Historical A4 record, applicable through `2fbfe4f`. Its public demo mode is
removed in A5 phase 3. Preserve this record, the specifications, screenshots
and fictional seed command; replay A4 using that commit and a separate demo
database. See the [A5 key change log](wk5_A5_phase1&phase2.md) for the fixed permissions.

This integration adapts the existing Week 3 project and the teammates' Week 4
contributions to the October 3 A4 update. The focus is a public coursework demo:
internal/external APIs, visualizations, reports, downloads and deployment preparation.

## Ordinary user authentication disabled

- Added `A4_ASSIGNMENT_MODE=True` in the settings and environment template.
- Updated `CampusAccessMiddleware` to redirect login, registration, verification,
  password-reset and Google sign-in routes home; account-dependent routes return 403.
- Added the assignment context processor and changed the header to show public
  chart/report links. Removed the Message Seller entry from the A4 detail view.
- Kept existing account code for later coursework and retained Django Admin's
  normal authentication. The A4 demo does not require an ordinary user session.

Files: `moveon/settings/base.py`, `.env.example`, `marketplace/assignment.py`,
`marketplace/access_middleware.py`, `templates/marketplace/partials/_header.html`
and `templates/marketplace/listing_detail.html`.

## Part 1: Public APIs and URL-backed charts

- Retained the database-backed `/api/listings/` GET API and existing chart queries.
- Added the public `/charts/` page for the summary bar, cumulative line and inquiry
  charts, replacing the need to demonstrate them through a signed-in profile.
- Adjusted chart access decorators so A4 uses the fixed fictional Maya identity;
  ordinary account-scoped behavior is retained when A4 mode is disabled.
- Kept `data.url` in all chart specifications and allowed the Vega Editor origin
  to read the public chart APIs. Saved submission specifications and screenshots
  under `docs/notes/week4_specs/` and `docs/notes/week4_screenshots/`.
- Fixed PNG rendering by supplying the same API response through a temporary
  loopback HTTP endpoint, avoiding a recursive request to another web-app worker.
- Pinned compatible Vega/Vega-Lite browser dependencies and used UTC dates on the
  line chart so browser and image outputs show the intended transaction dates.

Files: `marketplace/charts.py`, `marketplace/urls.py`,
`templates/marketplace/assignment_charts.html`,
`templates/marketplace/profile_base.html` and `static/js/marketplace/vega-charts.js`.

## Part 2: External API contribution retained

Retained the teammate's Frankfurter currency-conversion implementation in
`marketplace/api.py` and exposed it in the public A4 workflow at
`/api/listings/converted/?currency=CAD`. It combines filtered database prices
with keyless exchange rates, passes query parameters, uses a five-second timeout
and `raise_for_status()`, and returns JSON errors for failures. External responses
are not stored.

## Part 3: Export and reporting contribution retained

Retained the teammate's `marketplace/reports.py` implementation and added its
public report/download entry to the A4 header. `/reports/` presents grouped
category and condition summaries, totals and empty states. CSV and JSON export
the same filtered active listings with timestamped filenames; JSON includes
`generated_at`, `record_count` and `listings`. Both formats use the same stable
record order. Filtering and empty-result examples are now documented in
README in place of the earlier account/messaging demonstrations.

## Part 4: Demo database and static deployment configuration

- Backed up the previous working database under ignored `data/backups/` and built
  a fresh assignment-only `data/db.sqlite3` from migrations.
- Added repeatable `seed_a4_data`: five fictional `example.invalid` identities,
  14 listings (13 active), four transactions and sample conversations. Maya's
  totals are $113 spent and $18 earned, with activity on multiple dates.
- Used unusable passwords and excluded real accounts, staff/superusers, sessions,
  verification challenges and Google identities from the submission database.
- Added the explicit `.gitignore` exception for `data/db.sqlite3` while keeping
  `.env`, backups, collected static assets and the local environment ignored.
- Added `STATIC_ROOT = BASE_DIR / "staticfiles"` for production `collectstatic`;
  retained the existing `requirements.txt` and production settings.

Files: `marketplace/management/commands/seed_a4_data.py`, `data/db.sqlite3`,
`.gitignore` and `moveon/settings/base.py`.

## Repository and documentation cleanup

Removed unused imports from the historical migrations and messaging scaffold,
and removed the obsolete migration image mapping. Grouped URL definitions by
listing APIs, chart data, specifications/images and reports/downloads; retained
the existing migration operations and route behavior.

Moved the ten marketplace test files into the existing `tests/marketplace/`
package, adjusted their imports and renamed the former `marketplace/tests.py`
to `test_views.py`. Updated README and related file/command references.
README now describes Assignment 4 and public demonstrations; login/email and
Message Seller manual walkthroughs remain in the historical Week 3 notes.

## Deployment and submission

1. Confirm that the GitHub submission branch contains the complete A4 code,
   `requirements.txt`, clean `data/db.sqlite3`, chart specifications and screenshots.
   Push the final integration branch, then clone or pull that branch on PythonAnywhere.
2. Create a Python 3.12 environment and install `requirements.txt`. Configure private
   environment values, the actual `ALLOWED_HOSTS` and `A4_ASSIGNMENT_MODE=True`.
3. Configure production WSGI with `DJANGO_SETTINGS_MODULE=moveon.settings.production`.
   Run `collectstatic`, map `/static/` to `staticfiles`, and reload the site.
4. Confirm that the deployed public features work. Replace the local API host in the
   submitted chart specifications with the deployed host, or save fresh online specs.
5. Grant instructor `mohitg27` access. Enter the GitHub branch link, deployed URL
   and PythonAnywhere username in Assignment Comments, then submit through Canvas.

## PythonAnywhere PNG rendering fix

The deployed PNG endpoints returned HTTP 502 because `sys.executable` inside
the uWSGI worker pointed to `/usr/local/bin/uwsgi`. The subprocess therefore
passed Python rendering code to uWSGI instead of a Python interpreter.

Updated `marketplace/charts.py` to locate the environment's Python through
`sys.prefix`: `bin/python` on Linux and `Scripts/python.exe` on Windows. Kept
the existing URL-backed API relay, separate rendering process and 30-second
timeout. Added error logging for subprocess stderr and interpreter startup
failures. The fix adds no dependencies or account-specific paths.

Added regression coverage for all three PNG endpoints when the host executable
is uWSGI. The local correction still requires verification on the deployed PNG
endpoints after the updated file is synchronized and the web app is reloaded.
