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

## Testing Message seller / Messaging locally

The [Messages page](http://127.0.0.1:8000/messages/) requires two active,
verified `@illinois.edu` accounts: A is the buyer and B is the seller, with at
least one active listing owned by B. Use one of these setup paths:

- **Isolated preview data:** `messaging_preview` uses its own SQLite database.
  Its seed command creates demo data, including all six Messaging trade states,
  Bundle request outcomes, and verified accounts `alex`, `maya`, and `jamie`.
  It prints passwords for newly enabled accounts in the terminal; rerunning
  keeps existing passwords. Use them locally and never paste them into tracked
  files. If an existing preview password is unknown, reset it with
  `python manage.py changepassword <username> --settings=moveon.settings.messaging_preview`.
- **Regular development data:** Register A and B through the site, verify both
  accounts using the six-digit codes printed in the `runserver` terminal, then
  sign in as B and use **Sell Item** to create and publish an active listing.
  Listing creation is available in the UI; Django Admin is not needed for this
  workflow.

Start an isolated preview server from the repository root:

These `migrate` commands update only the database selected by `--settings`.
Use the preview settings to try the new `messaging.0007_deal_proposal` migration
without changing an existing development database.

```bash
# macOS / Linux
python manage.py migrate --settings=moveon.settings.messaging_preview
python manage.py seed_messaging_preview --settings=moveon.settings.messaging_preview
python manage.py runserver 127.0.0.1:8000 --settings=moveon.settings.messaging_preview
```

```powershell
# Windows PowerShell
& .\.venv\Scripts\python.exe manage.py migrate --settings=moveon.settings.messaging_preview
& .\.venv\Scripts\python.exe manage.py seed_messaging_preview --settings=moveon.settings.messaging_preview
& .\.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8000 --settings=moveon.settings.messaging_preview
```

For regular development data, migrate and start the server with the development
settings instead. Then register the accounts and create B's listing in the UI:

```bash
# macOS / Linux
python manage.py migrate --settings=moveon.settings.development
python manage.py runserver --settings=moveon.settings.development
```

```powershell
# Windows PowerShell
& .\.venv\Scripts\python.exe manage.py migrate --settings=moveon.settings.development
& .\.venv\Scripts\python.exe manage.py runserver --settings=moveon.settings.development
```

### Manual test

1. Sign in as A. Open B's active listing detail page and click **Message
   Seller**. The browser should navigate to `/messages/?listing=<id>` and open
   the matching conversation.
2. Send a message as A. Confirm B's Messages unread badge increases, then sign
   in as B, open the conversation, and reply.
3. Sign out and click **Message Seller** as a guest. The account page should
   retain the Messages destination when switching between **Create account**
   and **Log in**; after verification and sign-in, the browser should return to
   the listing conversation. As a separate check, use the header profile icon
   to sign in; that general account entry should return to the home page.
4. As B, click **Start Deal**, enter a final price, check the seller confirmation,
   and submit. B should see **Waiting for response**; A should see **Action
   needed** and **Review Deal**. The listing's public price should stay the same.
5. As B, use **Edit Offer** to change the price. A should see the old price as a
   non-actionable **Replaced** offer. In a second browser session, leave A's
   review dialog open while B edits: polling should show the new offer and
   disable confirmation of the old one without clearing a chat draft.
6. As A, review and **Accept** the current offer. Both sides should
   show **Pending pickup** and the agreed price. Another buyer with an existing
   conversation for that listing should see **Unavailable**, without A's price.
   On another active listing, submit and withdraw one offer, then submit a new
   offer for A to **Decline**. Neither old offer should remain actionable.
7. Use the seeded pending Bundle request to check **Accept request** or
   **Decline request**; create another pending request to test both actions.
   The seeded accepted and declined rows show historical results. Acceptance
   reserves its listing without a second buyer confirmation. While a request
   is pending, the seller cannot start or edit an ordinary offer in that
   conversation.

Run the focused Messaging tests against an automatically created test database.
`test` does not write to the preview or regular development database:

```bash
# macOS / Linux
python manage.py test tests.messaging --settings=moveon.settings.messaging_preview
python manage.py check --settings=moveon.settings.messaging_preview
python manage.py makemigrations --check --dry-run --settings=moveon.settings.messaging_preview
node --check static/messaging/messaging.js  # optional, if Node.js is installed
```

```powershell
# Windows PowerShell
& .\.venv\Scripts\python.exe manage.py test tests.messaging --settings=moveon.settings.messaging_preview
& .\.venv\Scripts\python.exe manage.py check --settings=moveon.settings.messaging_preview
& .\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run --settings=moveon.settings.messaging_preview
node --check static/messaging/messaging.js  # optional, if Node.js is installed
```

For a broader regression check, run
`python manage.py test --settings=moveon.settings.messaging_preview` once.

### Common questions

- **Messaging migration:** This checkout already has the merge migration
  `messaging.0006_merge_20260923_2310`; `messaging.0007_deal_proposal` follows
  it. Run `migrate` with the settings for the database you intend to update.
- **Why can't a Django Admin account open Messages?** Admin access does not
  grant student access. Use active accounts with verified `@illinois.edu`
  addresses.
- **Which settings should I use?** Use `moveon.settings.messaging_preview`
  for isolated seeded preview data and Messaging tests. Use
  `moveon.settings.development` for ordinary registration and listing creation.
  Django tests create a separate test database under either settings module.

See [current Messaging deals and trade status](docs/notes/weekly_progress_updates/wk4_messaging_deals.md)
for the offer flow, [the Week 3 Messaging snapshot](docs/notes/weekly_progress_updates/wk3_messaging.md)
for the original chat MVP, and the
[Message seller wiring note](docs/notes/weekly_progress_updates/wk3_detail_message_wiring.md)
for this listing-to-conversation integration.
