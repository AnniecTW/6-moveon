# MoveOn (INFO 490 - Project 1)

This branch is the **A4 assignment submission**, with public, read-only demo
features and user sign-in/registration disabled (`A4_ASSIGNMENT_MODE=True`).
The assignment database `data/db.sqlite3` contains fictional `example.invalid` identities
with unusable passwords, 14 listings and four demo transactions. No sessions,
email verification challenges, Google identities or administrator accounts are
included. Existing account code is retained for A5 and requires
`A4_ASSIGNMENT_MODE=False` to use.

Start the A4 preview with `python manage.py runserver 127.0.0.1:8014`.
Browse `/`, `/charts/`, `/reports/`, `/api/listings/` and
`/api/listings/converted/?currency=CAD`. Submitted chart JSON specifications
and current screenshots are in `docs/notes/week4_specs/` and
`docs/notes/week4_screenshots/`.
See [Week 4 A4 integration changes](docs/notes/weekly_progress_updates/wk4_A4_integration.md)
for the adjustments made to align the existing project with the assignment.
Account and messaging code is retained for later coursework; A4 demonstrations
use the public routes below.

MoveOn is a student marketplace for buying, selling, giving away, and reusing
dorm and apartment items. It helps students find affordable secondhand goods
from other students during move-in and move-out seasons.

The A4 demo includes searchable listings, public charts, currency conversion,
summary reports and CSV/JSON downloads. The application uses Django templates,
plain CSS and JavaScript modules. See [Frontend architecture](docs/frontend-architecture.md)
for implementation details.

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
A4_ASSIGNMENT_MODE=True
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

#### 6. Run Migrations, Seed Demo Data, & Start Dev Server
Create the local database, populate it with demo data, and start the server:

```bash
python manage.py migrate
python manage.py seed_a4_data
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
Run checks with `python manage.py check` and the anonymous A4 tests with
`python manage.py test tests.marketplace.test_a4_assignment`.
To exercise the entire suite, including the preserved authentication workflows,
run `A4_ASSIGNMENT_MODE=False python manage.py test` (PowerShell equivalents
are shown below). A4-specific tests enable A4 mode themselves.

```powershell
$env:A4_ASSIGNMENT_MODE = "False"
python manage.py test
Remove-Item Env:A4_ASSIGNMENT_MODE
```

## Assignment 4: APIs, visualizations, exports, and deployment

The A4 demonstration uses `A4_ASSIGNMENT_MODE=True`. Visitors can browse data,
view charts and download reports without registering or signing in. Account
routes redirect home, and account-dependent features remain unavailable. Django
Admin retains its own authentication.

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
`SECRET_KEY`, the actual `ALLOWED_HOSTS` and `A4_ASSIGNMENT_MODE=True`.
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
After deployment, replace the local API host in the submitted specifications
with the deployed host, or save fresh copies from the deployed `.json` endpoints.

Confirm that the deployed APIs, charts, PNG outputs and CSV/JSON downloads work.
Grant instructor account `mohitg27` access. Enter the GitHub branch link,
deployed site link and PythonAnywhere username in Assignment Comments,
then complete the Canvas submission.
