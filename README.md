# MoveOn (INFO 490 - Project 1)

MoveOn is a student marketplace for buying, selling, giving away, and reusing
dorm and apartment items. It helps students find affordable secondhand goods
from other students during move-in and move-out seasons.

The project includes a searchable and filterable listing page, featured bundles,
saved items, and responsive browser interactions. The application uses Django templates, plain CSS, and
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

## Account access and email

For a local check, register with an `@illinois.edu` address, copy the six-digit
code from the `runserver` terminal, verify, log in, and log out. Then use
**Forgot password?** and open its reset link from that terminal. The local
console backend does **not** deliver real email. A developer can create a
full-access Django Admin account once per new database; Admin login does not
require campus email verification.

```bash
python manage.py createsuperuser
python manage.py test tests.marketplace.test_auth
python manage.py test
```

See [Week 3 authentication details](docs/notes/weekly_progress_updates/wk3_authentication.md)
for account rules, configuration, test coverage, and remaining external checks.

## Messages

The desktop [Messages page](http://127.0.0.1:8000/messages/) supports protected
conversations, unread counts, Bundle requests, and image messages. For a local
preview in PowerShell, run these commands from the repository root (seed only
once if you want to keep existing preview passwords):

```powershell
& .\.venv\Scripts\python.exe manage.py migrate --settings=moveon.settings.messaging_preview
& .\.venv\Scripts\python.exe manage.py seed_messaging_preview --settings=moveon.settings.messaging_preview
& .\.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8000 --settings=moveon.settings.messaging_preview
```

To run the focused Messaging tests, use
`& .\.venv\Scripts\python.exe manage.py test tests.messaging --settings=moveon.settings.development`.
For a quick manual check, sign in as one preview user, send a message to the
other, then confirm the recipient's unread badge and reply.
See [Messaging implementation and local setup](docs/notes/weekly_progress_updates/wk3_messaging.md)
or jump directly to the [10-minute manual test](docs/notes/weekly_progress_updates/wk3_messaging.md#manual-testing).
