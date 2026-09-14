# MoveOn (INFO 490 - Project 1)

MoveOn uses Django-rendered templates, plain CSS, and small JavaScript modules.
The browse layout follows the reference frontend while keeping the existing Django apps.
See [Frontend architecture](docs/frontend-architecture.md) for file responsibilities,
dependency decisions, supported interactions, and remaining feature work.

---

## Local Environment Setup

Please follow the steps below to set up your local development environment. We are standardizing on **Python 3.12** across all machines to prevent dependency discrepancies.

### Prerequisites
* Git installed and configured
* Python 3.12 (via Conda or native Python)
* Node.js is optional (JavaScript syntax checks and the legacy Tailwind build only).

---

### Getting Started

#### 1. Clone the Repository
```bash
git clone https://github.com/AnniecTW/info490-moveon.git
cd info490-moveon
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

Copy `.env.example` to `.env` and set a local `SECRET_KEY`. Do not commit `.env`.

#### 4. Frontend Assets
No frontend install or build is required. Django loads
`static/css/marketplace.css` and `static/js/marketplace.js` directly.
Edit the CSS files under `static/css/marketplace/` and JavaScript modules under
`static/js/marketplace/`, then refresh the browser.
The older Tailwind files remain available but are not used by the browse page.

#### 5. Run Migrations, Seed Demo Data, & Start Dev Server
Create the local database, populate it with demo data, and start the server:

```bash
python manage.py migrate
python manage.py seed_demo_data
python manage.py seed_featured_bundles
python manage.py runserver
```

The entry points default to `moveon.settings.development`. For production, override the setting module through the environment:

```bash
DJANGO_SETTINGS_MODULE=moveon.settings.production python manage.py check --deploy
```

Open [http://127.0.0.1:8000/](http://127.0.0.1:8000/) to browse MoveOn.
The original `/listings/manual/`, `/listings/render/`, `/listings/cbv-base/`,
and `/listings/cbv-generic/` routes all share the new layout and filtering behavior.
The six featured demo listings use local reference images and power the interactive
bundle scenes. Other listings without image URLs show a photo placeholder.

Run checks with `python manage.py check` and `python manage.py test`.

---

### 📌 Development Notes
* **Never commit local databases or environment secrets:** `data/db.sqlite3` and `.env` are already excluded via `.gitignore`.
* **Branching Strategy:** Please create feature branches off `main` rather than committing directly to `main`.
* Git does not track empty directories. The `wireframes` and `branching_strategy` folders therefore contain a README placeholder so the required documentation structure remains visible in the repository before those folders receive their first substantive files.
