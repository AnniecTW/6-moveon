# MoveOn (INFO 490 - Project 1)

This branch is progressing through **A5 Part 1 and Part 2**. Phases 2 and 3
provide custom signup, campus email verification, password login, POST-only
logout, fixed permissions and private charts. The existing User model and
allauth foundation are retained. Google login now uses allauth's OAuth callback,
the same campus challenge and the same session/access rules. Existing local
accounts connect Google explicitly from Settings after signing in; matching
email alone does not merge accounts. Credentials come from environment settings
and social access/refresh tokens are not stored in the database.
See the [A5 key change log](docs/notes/weekly_progress_updates/wk5_A5_phase1&phase2.md).

The A4 global mode has been removed. Its former environment variable is
ignored; it cannot disable account entry or make private charts public.
The assignment database `data/db.sqlite3` contains fictional `example.invalid` identities
with unusable passwords, 14 listings and four demo transactions. No sessions,
email verification challenges, Google identities or administrator accounts are
included. Use an ignored database copy for local accounts by setting
`DATABASE_PATH` in `.env`, then run migrations on that copy. Keep real accounts,
sessions and OAuth secrets out of the tracked assignment database.

Start MoveOn with `python manage.py runserver 127.0.0.1:8014`.
Browse `/` and `/api/listings/` anonymously. After login and campus verification,
open `/charts/`, `/reports/` and `/api/listings/converted/?currency=CAD`.
Historical A4 chart specifications and screenshots are in `docs/notes/week4_specs/` and
`docs/notes/week4_screenshots/`.
See [Week 4 A4 integration changes](docs/notes/weekly_progress_updates/wk4_A4_integration.md)
for the adjustments made to align the existing project with the assignment.

MoveOn is a student marketplace for buying, selling, giving away, and reusing
dorm and apartment items. It helps students find affordable secondhand goods
from other students during move-in and move-out seasons.

The preserved features include searchable listings, personal charts, currency conversion,
summary reports and CSV/JSON downloads. The application uses Django templates,
plain CSS and JavaScript modules. See [Frontend architecture](docs/frontend-architecture.md)
for implementation details.

## Current access rules

| Feature | Permission |
| --- | --- |
| Browse, active listing details, legacy browse layouts, `/api/listings/demo/` HTML documentation | Public |
| `/api/listings/` | The single public business data API; active listing fields, filters and pagination are preserved |
| `/account/` signup/login, verification, password reset, Google login/callback | Public entry; state, CSRF and method requirements still apply; Google connection requires an authenticated campus account |
| `/charts/`, profile pages, chart data/specifications/PNGs | Authenticated campus access; charts always read the current user's activity |
| Messaging, listing creation/edit/preview/publish, image upload, bundles | Authenticated campus access plus seller/buyer/participant/object ownership checks |
| `/reports/`, `/reports/listings.csv`, `/reports/listings.json`, `/api/listings/converted/` | Authenticated campus access; report filters, summaries and downloads are preserved |
| `/admin/` | Django's existing administrator authorization |

Campus access requires an active account, an `@illinois.edu` address and the
existing completed email-code verification. Google/provider metadata alone
does not grant it. Private JSON APIs, specifications and uploads return JSON
401 for anonymous requests or 403 for authenticated users lacking access.
Suspended/inactive accounts lose their recognized session and receive 401.
Private HTML and PNG GET/HEAD requests redirect to `/account/?next=...`.
Protected navigation, report links and currency controls are hidden without
campus access; anonymous browsing/search/filtering continues with USD prices.

Private PNGs first authorize and query the current user's chart API in the
same request. `marketplace/png_renderer.py` receives the spec and authorized
JSON snapshot through stdin. This child starts a temporary `127.0.0.1` relay
and a short-lived rendering descendant: vl-convert 1.9.0 blocks a Python relay
thread when conversion runs in the same process. Django starts no relay server
or relay thread, and neither child queries Django or needs a second website
worker. Private data is absent from command arguments and logs. The relay closes
after success/failure; timeout cleanup terminates the request's process tree.
URL-backed `data.url`, `sys.prefix` interpreter selection and the 30-second
worker timeout are retained. The relay is request-scoped rather than a
persistent service or public endpoint.

---

## Setup

The project uses Python 3.12 across development environments.

### Prerequisites
* Git installed and configured
* Python 3.12 (via Conda or native Python)
* Node.js is optional (JavaScript syntax checks and the legacy Tailwind build only).

---

### Getting Started

#### 1. Clone the Repository
```bash
git clone https://github.com/AnniecTW/6-moveon.git
cd 6-moveon
```

#### 2. Create and Activate Virtual Environment

* **Option A: Using Conda (Recommended)**
  ```bash
  conda create -n moveon-env python=3.12 -y
  conda activate moveon-env
  ```
  
* **Option B: Using Native Python `venv`**
  ```bash
  # macOS / Linux
  python3.12 -m venv .venv
  source .venv/bin/activate

  # Windows (Command Prompt / PowerShell)
  python -m venv .venv
  .venv\Scripts\activate
  ```

#### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

#### 4. Configure Environment Variables
Create a local environment file from the tracked template:

```bash
# macOS / Linux
cp .env.example .env

# Windows PowerShell
Copy-Item .env.example .env
```

Open `.env` and replace the placeholder value with a local Django secret key:

```env
SECRET_KEY=your-local-secret-key
DATABASE_PATH=data/backups/a5-local.sqlite3
```

You can generate a secure local key with:

```bash
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

Copy the generated value after `SECRET_KEY=` in `.env`.

The application loads this value from `.env` when Django starts. Keep `.env`
local and never commit it. Only `.env.example` should be tracked in Git.

#### 5. Frontend Assets
No frontend installation or build step is required. The browse page uses the
CSS and JavaScript files under `static/css/marketplace/` and `static/js/`.
Tailwind's package and source files are kept for possible future use.

#### 6. Prepare a Local Database, Run Migrations & Start Dev Server

Preserve the tracked A4 database. For a fresh Windows checkout, initialize
the ignored copy only when it does not already exist:

```powershell
New-Item -ItemType Directory -Force data/backups | Out-Null
if (-not (Test-Path data/backups/a5-local.sqlite3)) {
    Copy-Item data/db.sqlite3 data/backups/a5-local.sqlite3
}
```

On macOS/Linux, create `data/backups` and copy `data/db.sqlite3` to the configured
path only if that copy is absent. Existing local databases must be preserved.
Then migrate and start the app:

```bash
python manage.py migrate
python manage.py runserver 127.0.0.1:8014
```

The entry points default to `moveon.settings.development`. For production, override the setting module through the environment:

```bash
DJANGO_SETTINGS_MODULE=moveon.settings.production python manage.py check --deploy
```

Open [http://127.0.0.1:8014/](http://127.0.0.1:8014/) to browse MoveOn.
The original `/listings/manual/`, `/listings/render/`, `/listings/cbv-base/`,
and `/listings/cbv-generic/` routes all share the new layout and filtering behavior.
Featured listing cards use local reference images. Other listings without image
URLs show a photo placeholder.

Marketplace tests are grouped under `tests/marketplace/`; the original
`marketplace/tests.py` is now `tests/marketplace/test_views.py`.
Run configuration checks with `python manage.py check`. Focused A5 checks are:

```powershell
python manage.py test tests.marketplace.test_a5_accounts tests.marketplace.test_a5_access tests.marketplace.test_a5_charts
```

## Assignment 4: APIs, visualizations, exports, and deployment

The following section documents the historical A4 submission at `2fbfe4f`.
Its public Maya charts, public exports and disabled account entry describe
that version. Current access rules are listed above. To replay A4, use that
commit in a separate checkout with an independent demo database; do not replace
the A5 checkout or its account database. `seed_a4_data` remains available for
an independent fictional dataset and refuses databases containing real accounts.

### Part 1: Internal JSON API and Vega-Lite charts

- `/api/listings/` is a public, read-only GET endpoint backed by active `Listing`
  records. It returns count/page metadata and up to 20 results per page. For
  example, `/api/listings/?q=desk&page=1` filters listings by a search term.
- `/charts/` embeds the earned/spent bar chart and cumulative line chart, plus
  the existing inquiry chart. They use fictional Maya activity from the database,
  with $113 spent and $18 earned.
- The specifications are `/vega-lite/earned-spent.json`,
  `/vega-lite/earned-spent-timeline.json` and `/vega-lite/listing-inquiries.json`.
  Their `data.url` values point to public JSON endpoints under
  `/api/profile/charts/`; no inline data is used.
- Matching PNG endpoints replace `.json` with `.png`. Server-side rendering uses
  the same internal API response through a temporary loopback endpoint so it
  does not need a second web-app worker to serve the data request.
- Vega Editor can read the chart APIs. The website uses compatible, pinned Vega
  libraries from esm.sh, so browser chart rendering requires internet access.

Main files: `marketplace/api.py`, `marketplace/charts.py`,
`templates/marketplace/assignment_charts.html` and
`static/js/marketplace/vega-charts.js`.

### Part 2: External API integration

`/api/listings/converted/?currency=CAD&q=Oak%20Desk` combines filtered internal
listing prices with keyless Frankfurter exchange rates. The endpoint accepts
USD, CAD, EUR and GBP. External requests use query parameters, `timeout=5` and
`raise_for_status()`; failures return JSON errors. Exchange-rate responses are
used for the current request and are not stored in the database.

Main file: `marketplace/api.py`.

### Part 3: Reports and CSV/JSON exports

- `/reports/` presents two database summaries: listings by category and listings
  by condition, together with the total count, average price and empty states.
- Download buttons lead to `/reports/listings.csv` and `/reports/listings.json`.
  Both exports use the same active listings and filters, with timestamped filenames.
  JSON includes `generated_at`, `record_count` and `listings`.
- Open `/reports/?q=Desk` to demonstrate a filtered report and matching downloads.
  `/reports/?q=zzzz-no-result` demonstrates the empty state. The header's Reports
  link opens the unfiltered report.
- Exports are ordered by ascending ID (`pk`); sold listings are excluded.

Main files: `marketplace/reports.py`, `marketplace/browse.py` and
`templates/marketplace/reports.html`.

### Part 4: Database and deployment preparation

`data/db.sqlite3` is the assignment demonstration database: five fictional
identities with unusable passwords, 14 listings (13 active), four transactions
and sample conversations. It contains no real accounts, administrator accounts,
sessions, email verification challenges or Google identities. The previous
working database is backed up locally under ignored `data/backups/`.

The `.gitignore` exception allows this demo database to be submitted to GitHub.
Private `.env` files, database backups, the local verification environment and
collected static assets remain ignored. `STATIC_ROOT` is `BASE_DIR / "staticfiles"`;
run the following before configuring PythonAnywhere's `/static/` mapping:

```bash
python manage.py collectstatic --noinput --settings=moveon.settings.production
```

Confirm that the GitHub submission branch includes the complete A4 implementation,
`requirements.txt`, chart specifications/screenshots and the clean `data/db.sqlite3`.
Push the final branch, then clone or pull that branch on PythonAnywhere.
Create a Python 3.12 environment and install `requirements.txt`. Configure a private
`SECRET_KEY`, the actual `ALLOWED_HOSTS` and the historical mode setting for that version.
Configure the Web-tab WSGI file with
`DJANGO_SETTINGS_MODULE=moveon.settings.production` and the project/virtualenv paths.
Run production `collectstatic`, map `/static/` to `staticfiles`, and reload the site.

### A4 demonstration and submission files

| Feature | Local route | What to demonstrate |
| --- | --- | --- |
| Internal API | `/api/listings/` | Database-backed JSON and a search query |
| Visualizations | `/charts/` | Bar and line charts, their JSON specifications and PNG outputs |
| External API | `/api/listings/converted/?currency=CAD` | Converted prices and the returned exchange rate |
| Reports and downloads | `/reports/` | Both summaries, CSV/JSON downloads, filtering and the empty state |

Chart JSON specifications are in
[`docs/notes/week4_specs/`](docs/notes/week4_specs/); website screenshots,
Vega Editor previews and PNG outputs are in
[`docs/notes/week4_screenshots/`](docs/notes/week4_screenshots/).

Confirmed that the deployed APIs, embedded charts and CSV/JSON downloads work.
Granted instructor account `mohitg27` access.

## Current deployment configuration cleanup

When manually deploying the A5 changes, remove `A4_ASSIGNMENT_MODE` from the
production `.env`, any WSGI/environment assignments and local startup scripts.
Remove it from a shell with `unset A4_ASSIGNMENT_MODE` on Linux or
`Remove-Item Env:A4_ASSIGNMENT_MODE -ErrorAction SilentlyContinue` in PowerShell.
The current code ignores any leftover value, but clearing it avoids misleading
configuration. Keep production secrets private and use the existing production
account database, separate from the tracked fictional A4 database. Dependencies,
allauth migrations, static assets and the web app reload are manual deployment
steps; the complete OAuth/deployment handoff belongs to phases 4 and 5.
