# MoveOn (INFO 490 - Project 1)

MoveOn is a student marketplace for buying, selling, giving away, and reusing
dorm and apartment items. It helps students find affordable secondhand goods
from other students during move-in and move-out seasons.

Features include searchable listings, seller and buyer profiles, messaging,
move-in bundles, personal charts, currency conversion, summary reports and
CSV/JSON downloads. The application uses Django templates, plain CSS and
JavaScript modules. See [Frontend architecture](docs/frontend-architecture.md)
for implementation details.

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

For the public API analysis notebook, install its additional data-analysis and
Jupyter dependencies instead:

```bash
pip install -r requirements-notebook.txt
```

#### 4. Configure Environment Variables
On a new installation, copy `.env.example` to `.env`. Keep an existing `.env`:

```bash
# macOS / Linux
cp .env.example .env

# Windows PowerShell
Copy-Item .env.example .env
```

Set a private `SECRET_KEY` and choose the working database path in `.env`.
For a new installation:

```env
SECRET_KEY=your-local-secret-key
DATABASE_PATH=data/local.sqlite3
```

Existing users should keep their original database path; do not move or replace
the database to match this example. When `DATABASE_PATH` is unset, the current
default remains `data/db.sqlite3`. Creating a directory or selecting a path does
not back up a database. Keep `.env` private and untracked; see the
[Environment and database setup guide](docs/notes/week5_setup.md) for key generation and environment details.

#### 5. AI Features (setup, demo data, and how to use them)

**Model downloads.** No model weights are committed; they download to the Hugging Face cache (`~/.cache/huggingface/`) on first use.

| Model | Used for | Access | Size |
|---|---|---|---|
| `meta-llama/Llama-3.2-3B-Instruct` | Natural-language listing search (main AI feature) | Gated: accept the Llama 3.2 license on Hugging Face, create a read token, and set `HF_TOKEN=hf_...` in `.env` | ~6 GB |
| `sentence-transformers/all-MiniLM-L6-v2` | Item-type and price suggestions when creating a listing | Public, no token | ~90 MB |

The first AI search downloads Llama (several minutes) and loads it into memory. After that, a search takes about 8 s on an Apple M-series laptop. A CUDA GPU is used automatically if available. Optional Gemini features (bundle tiers, photo autofill) use `GEMINI_API_KEY` and fall back without it. Do not commit `.env`, tokens, or model weights.

**Demo data.** A newly migrated database has no listings, so AI search has nothing to rank. To load the 40-listing catalogue used in our A6 and A9 evaluations into a separate database:

```bash
export DATABASE_PATH=data/eval.sqlite3      # PowerShell: $env:DATABASE_PATH="data/eval.sqlite3"
python manage.py migrate
python manage.py sync_pricing_taxonomy      # item types for pricing suggestions
python manage.py evaluate_ai --seed         # loads the listings, then runs the evaluation once
python manage.py runserver
```

`--seed` only works on an empty database; omit it on later runs. Results are written to `docs/A9-part3/`; see [README_AI.md](README_AI.md#part-3-evaluation-of-the-integrated-features). Keep the same `DATABASE_PATH` set when starting the server.

**Using AI search (no login needed).**
1. Open [http://127.0.0.1:8000/](http://127.0.0.1:8000/) or `/listings/`.
2. Turn on the **AI natural-language search** switch next to the search box.
3. Type a request such as `I need to heat up food quickly` or `comfortable seating for when friends visit`, then press Enter.
4. AI-ranked listings appear as cards. If the model fails or finds nothing relevant (try `snowboard for winter break`), the page shows a labelled message with random fallback listings.

You can also open a search directly: `/listings/?search_mode=ai&q=I+need+to+heat+up+food+quickly`.

**Using pricing suggestions (campus login needed).**
1. Sign up at `/account/` with an `@illinois.edu` address. In development, the verification code is printed in the `runserver` console.
2. Open `/listings/new/` and type a title such as `Mini fridge for dorm room`.
3. Suggested item types with price guides appear under the title. Select one, then accept, edit, or ignore the suggested price.

#### 6. Frontend Assets
No frontend installation or build step is required. The browse page uses the
CSS and JavaScript files under `static/css/marketplace/` and `static/js/`.
Tailwind's package and source files are kept for possible future use.

#### 7. Prepare the Working Database & Start the Dev Server

Run from the repository root with the Python environment activated. Create only
the parent directory needed by your chosen database path (`data/` in the new-install example):

```powershell
New-Item -ItemType Directory -Force data | Out-Null
```

On macOS/Linux, use `mkdir -p data`. For first setup or required migration updates:

```bash
python manage.py migrate --settings=moveon.settings.development
python manage.py runserver 127.0.0.1:8000 --settings=moveon.settings.development
```

`migrate` initializes or updates the selected database; it does not automatically
back it up or populate demonstration data. For an initialized, up-to-date database,
run only `runserver`. Open [http://127.0.0.1:8000/](http://127.0.0.1:8000/).
See the [Environment and database setup guide](docs/notes/week5_setup.md) for existing databases,
mock preview, backups, production configuration and optional manual checks.

### Optional Google Sign-In

Configure `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` in the target environment,
and register callback URLs matching the actual host and port. The local setup
above uses `http://127.0.0.1:8000/accounts/google/login/callback/`; the production
callback is `https://moveonbochen.pythonanywhere.com/accounts/google/login/callback/`.

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

## Project History

Earlier assignment records are retained in the [Weeks 1–5 notes](docs/notes/notes.txt)
and [A5 authentication change log](docs/notes/weekly_progress_updates/wk5_A5_phase1&phase2.md).
These historical notes are separate from the A6 production reflection.
