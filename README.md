# MoveOn (INFO 490 - Project 1)

MoveOn is a student marketplace for buying, selling, giving away, and reusing
dorm and apartment items. It helps students find affordable secondhand goods
from other students during move-in and move-out seasons.

Features include searchable listings, seller and buyer profiles, messaging,
move-in bundles, personal charts, currency conversion, summary reports and
CSV/JSON downloads. The application uses Django templates, plain CSS and
JavaScript modules. See [Frontend architecture](docs/frontend-architecture.md)
for implementation details.

## A7 Multi-Model AI Systems

Use these files to review the A7 submission. The notebook covers Part 1 and the
Part 2 cost simulation; Part 3 routing scenarios are in `system_design.md`.

### Deliverables

| Part | Deliverable | Reviewer reference |
|---|---|---|
| Part 1: Model benchmark | [Notebook](docs/A7-part1/input/multi_model_system.ipynb) | Contains the 15-model benchmark workflow, scoring guidance, benchmark results, and analysis. The completed run has 375 responses (15 models × 25 prompts). |
| Part 2: Cost and scaling | [Notebook](docs/A7-part1/input/multi_model_system.ipynb) | Uses the Part 1 benchmark to estimate token load, AWS replicas and cost, and Hugging Face API cost for six DAU levels. It maps 15 local LLMs to seven paid HF API models. Each DAU assumes 5 requests per person per day; the AWS capacity estimate uses 70% utilization. These are benchmark-based estimates, not production load-test results. |
| Part 3: Routing design | [System design](docs/A7-part1/system_design.md) | Describes five routing scenarios, the selected local and hosted models, and latency, cost, and quality trade-offs. |

### Supporting files

| File | Purpose |
|---|---|
| [Prompt bank](docs/A7-part1/input/a7_prompts.json) | The 25 prompts and evaluation references used by the benchmark. |
| [Benchmark records and reviewed scores](docs/A7-part1/input/benchmark_results.json) | Completed per-answer data used by the Part 2 simulation; no model rerun is needed for the cost estimates. |
| [Per-answer benchmark CSV](docs/A7-part1/input/A7_Step1_5_Benchmark_375.csv) | Readable 375-row benchmark export. |
| [Part 2 output files](docs/A7-part1/output/) | `results.csv`, `scores.csv`, and `summary.csv` provide per-answer results, reviewed scores, and grouped summaries. `run_config.json` records the run setup. |

The notebook now includes saved outputs for the 375-response benchmark table,
model/category summaries, both 90-row cost tables, and the six-scenario cost
summary. Its defaults leave dependency installation, Drive mounting, model
generation, and score re-export disabled. To regenerate the analysis outputs,
provide [a7_prompts.json](docs/A7-part1/input/a7_prompts.json) and
[benchmark_results.json](docs/A7-part1/input/benchmark_results.json); the
notebook searches beside itself, in `input/`, and under `docs/A7-part1/input/`.
Those files are external inputs, so rebuilding the analyses requires them even
though the saved notebook can be reviewed without rerunning models. A fresh
model run is a separate opt-in action and gated models may require an HF token
and repository access approval.

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

#### 5. Frontend Assets
No frontend installation or build step is required. The browse page uses the
CSS and JavaScript files under `static/css/marketplace/` and `static/js/`.
Tailwind's package and source files are kept for possible future use.

#### 6. Prepare the Working Database & Start the Dev Server

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
