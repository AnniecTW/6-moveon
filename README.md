# MoveOn (INFO 490 - Project 1)

MoveOn is a student marketplace for buying, selling, giving away, and reusing
dorm and apartment items. It helps students find affordable secondhand goods
from other students during move-in and move-out seasons.

Features include searchable listings, seller and buyer profiles, messaging,
move-in bundles, personal charts, currency conversion, summary reports and
CSV/JSON downloads. The application uses Django templates, plain CSS and
JavaScript modules. See [Frontend architecture](docs/frontend-architecture.md)
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

Use the independent database configured by `DATABASE_PATH`. Runtime databases
are ignored by Git; a fresh checkout creates its own database through migrations.
Keep an existing local database and its account data rather than replacing it.
For the example path above, create the parent directory before migrating:

```powershell
New-Item -ItemType Directory -Force data/backups | Out-Null
```

On macOS/Linux, use `mkdir -p data/backups`. Then migrate and start the app:

```bash
python manage.py migrate --settings=moveon.settings.development
python manage.py runserver 127.0.0.1:8000 --settings=moveon.settings.development
```

The entry points default to `moveon.settings.development`. For production, override the setting module through the environment:

```bash
DJANGO_SETTINGS_MODULE=moveon.settings.production python manage.py check --deploy
```

Open [http://127.0.0.1:8000/](http://127.0.0.1:8000/) to browse MoveOn.
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

## Assignment 5: Django Authentication, Google OAuth

This update covers A5 Part 1 and Part 2 on the existing MoveOn project.

### Part 1: Internal Django Authentication

- Custom pages provide signup and password login. Login accepts a username or
  campus email; signup checks duplicate usernames/emails and enforces the
  project's `@illinois.edu` email rule.
- A six-digit email challenge establishes campus access. Password reset is
  retained, and POST-only logout invalidates the current session.
- Password login uses django-allauth with the existing `marketplace.User` and
  Django session. Successful login returns to `/` or a validated same-host
  `next` address; verification is followed by a separate login.
- Fixed permissions protect private pages and APIs. Seller/buyer ownership and
  conversation-participant checks continue to apply after authentication.
- The common header shows protected navigation only with campus access and
  refreshes the Messages unread badge across pages. Listing details expose
  Message Seller to visitors and retain the intended conversation through login.
- Shared page notifications consume login feedback once rather than accumulating
  historical sign-in notices until Settings or Bundle is opened.

### Part 2: Google OAuth

- Login and signup provide Continue with Google through django-allauth's Google
  authorization-code flow, using CSRF-protected initiation, session-bound state
  and PKCE.
- Google and password login share the same User, session and access rules.
  Google's verified email claim does not replace MoveOn's campus email challenge.
  New Google accounts complete that challenge and then sign in with Google.
- A linked Google identity reuses its existing account. Existing password
  accounts connect Google explicitly from Settings using the same campus email;
  matching email alone does not merge accounts.
- Cancellation, provider failures and account conflicts return readable feedback.
  Google client credentials are read from environment settings; social access
  and refresh tokens are not stored in the database.

Configure `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` in the target environment,
and register callback URLs matching the actual host and port. The local setup
above uses `http://127.0.0.1:8000/accounts/google/login/callback/`; the production
callback is `https://moveonbochen.pythonanywhere.com/accounts/google/login/callback/`.

### Retained features and data boundaries

Searchable listings, messages, bundles, currency conversion, reports, exports and
the existing charts remain available under the current access rules. The A4
global mode has been removed, and charts read the current authenticated user's
activity rather than a fixed demonstration user.

Private PNG requests authorize and query the current user before passing a
snapshot through stdin to a standalone renderer. Its temporary local relay and
rendering descendant preserve URL-backed chart data without requesting the
website again. The renderer retains the virtual-environment interpreter choice,
30-second worker timeout and process cleanup.

Local real-account, mock preview and production databases are independent.
Runtime databases, backups, credentials and uploads are ignored by Git; schema,
migrations and data-generation commands are maintained as source code. The
`a5_preview` settings and `seed_a5_preview` command provide fictional local data
without loading real Google credentials or changing business permissions.

The historical A4 database snapshot remains in commit `2fbfe4f`. Its
[integration note](docs/notes/weekly_progress_updates/wk4_A4_integration.md),
[chart specifications](docs/notes/week4_specs/) and
[screenshots](docs/notes/week4_screenshots/) remain as historical materials.
See the [A5 key change log](docs/notes/weekly_progress_updates/wk5_A5_phase1&phase2.md)
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

Campus access requires an active account, an `@illinois.edu` address and completed
email-code verification. `User.email_verified` and `email_verified_at` are the
authority; allauth's EmailAddress record mirrors that proof, and changing its
Verified checkbox in Admin does not grant campus access.

Private JSON APIs, specifications and uploads return 401 for anonymous requests
or 403 for authenticated users lacking access. Suspended/inactive accounts lose
their recognized session and receive 401. Private HTML and PNG GET/HEAD requests
redirect to `/account/?next=...`. Protected navigation, report links and currency
controls are hidden without campus access; anonymous browsing/search/filtering
continues with USD prices. The public Message Seller entry still passes through
the protected messaging flow.

## Current progress

A5 Part 1 and Part 2 now provide custom signup, campus email verification,
password login, POST-only logout, fixed permissions and private charts. Google
login uses allauth's OAuth callback with the same campus challenge and shared
account/session rules. Existing local accounts connect Google explicitly from
Settings, and isolated mock data supports local demonstrations. Existing
marketplace functions and historical A4 materials are retained.
