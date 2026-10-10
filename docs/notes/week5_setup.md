# Week 5: Setup and Database Operations

This guide covers A5 Part 1 and Part 2. The [README](../../README.md) provides the
quick start; the [key change log](weekly_progress_updates/wk5_A5_phase1&phase2.md)
records implementation decisions. Commands below are manual instructions, not
startup automation or evidence that production has passed acceptance.

## Working directory and Python

Run commands from the repository root, which contains `manage.py`, using the
Python 3.12 environment with `requirements.txt` installed. For this Windows
checkout, use PowerShell:

```powershell
Set-Location -LiteralPath 'C:\Users\10675\OneDrive\Desktop\uiuc\26fall\ASG\INFO490\info490-moveon'
.\.venv\Scripts\Activate.ps1
```

For macOS/Linux, replace the checkout path and use Bash:

```bash
cd /path/to/info490-moveon
source .venv/bin/activate
```

If using Conda, activate `moveon-env` instead. Unless a block is platform-specific,
the `python manage.py ...` commands work in both shells from this directory.

## Three separate databases

| Environment | Settings | Database and purpose |
| --- | --- | --- |
| Local real accounts | `moveon.settings.development` | `DATABASE_PATH` selects the working SQLite file. New installs may use `data/local.sqlite3`; existing users keep their original path. Used for real password/Google account workflows. |
| Local A5 mock preview | `moveon.settings.a5_preview` | Fixed `data/a5-preview.sqlite3`, regardless of `DATABASE_PATH`. Fictional activity for access, ownership, messaging and chart demonstrations; uploads use `data/a5-preview-media/`. |
| Production | `moveon.settings.production` | A separately configured, persistent absolute `DATABASE_PATH` on the server. Keep actual production users and business data there. |

Development and production currently fall back to `data/db.sqlite3` when
`DATABASE_PATH` is unset. Relative paths resolve from the repository root.
Ordinary settings load `.env`, but an existing process environment value takes
precedence. Preview skips `.env` loading and supplies a temporary default session
key; with no inherited `SECRET_KEY`, restarting requires a new login/code request.

The existing local real-account path recorded for this workspace is
`data/backups/a5-local.sqlite3`. Despite its directory name, it is a working
database, not an automatic backup. Keep it if that is your configured database;
the `data/local.sqlite3` example does not require migration to a new file.

Runtime databases, SQLite sidecars, backups, `.env`, passwords and uploads are
ignored by Git. A fresh clone does not contain these local files.

## Local real-account setup and startup

On a new installation only, copy `.env.example` to `.env` as described in the
README. Generate a private key with the activated Python (PowerShell or Bash):

```bash
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

Put the generated value in `SECRET_KEY`. A new-install example is:

```env
SECRET_KEY=replace-with-your-generated-private-key
DATABASE_PATH=data/local.sqlite3
```

For an existing installation, retain `.env`, credentials and the original
database path. A missing expected database is a reason to locate it, not to
silently create a replacement and conclude that accounts were lost.

For first setup, create the necessary parent directory. The new-install example
uses `data/`; substitute the parent of your own path when needed:

```powershell
New-Item -ItemType Directory -Force data | Out-Null
```

On macOS/Linux, use `mkdir -p data`. Initialize a new database, or apply required
migration updates to an existing database after reviewing changes and making a backup:

```bash
python manage.py migrate --settings=moveon.settings.development
```

Migrations initialize or update the selected database. They do not automatically
make a backup or run `seed_a5_preview`/other demo commands. For an existing,
up-to-date database, daily startup only needs:

```bash
python manage.py runserver 127.0.0.1:8000 --settings=moveon.settings.development
```

Open [http://127.0.0.1:8000/](http://127.0.0.1:8000/). Real Google testing requires that environment's
`GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET`, plus the exact registered callback
`http://127.0.0.1:8000/accounts/google/login/callback/`. A different host or port
requires a matching registered callback. By default, development emails print
in this server terminal; actual delivery requires configured SMTP and a real
received message. Keep keys and credentials out of documentation and Git.

## A5 mock preview

Preview uses ordinary authentication and permissions. It disables real Google
and Gemini credentials and prints email contents in the server terminal. Mock
verification is fictional: this environment cannot prove real Google OAuth or
actual email delivery.

### First initialization only

Use this section only if `data/a5-preview.sqlite3` does not exist. If it already
exists, preserve it and use the startup section below. If initialization was
interrupted, inspect the existing file before deciding which step remains.

Windows PowerShell, from the activated repository root:

```powershell
if (Test-Path -LiteralPath 'data/a5-preview.sqlite3') { throw 'Preview database exists; preserve it and inspect first.' }
New-Item -ItemType Directory -Force data | Out-Null
python manage.py migrate --settings=moveon.settings.a5_preview --skip-checks --noinput
if ($LASTEXITCODE -ne 0) { throw 'Migration failed; do not seed.' }
python manage.py seed_a5_preview --settings=moveon.settings.a5_preview
```

macOS/Linux Bash, from the activated repository root:

```bash
if [ -e data/a5-preview.sqlite3 ]; then
    echo 'Preview database exists; preserve it and inspect first.'
else
    mkdir -p data
    python manage.py migrate --settings=moveon.settings.a5_preview --skip-checks --noinput &&
    python manage.py seed_a5_preview --settings=moveon.settings.a5_preview
fi
```

The seed command accepts only the exact preview settings and resolved dedicated
database path. It creates no administrator or Google identity and refuses
non-preset accounts or identity conflicts. Existing seeded records are reused;
passwords, verification and business edits are not reset. Reseeding is not a
daily startup step and does not reconstruct a missing password file.

| Username | Fictional email | Initial state |
| --- | --- | --- |
| `mock_maya_01` | `mock_maya_01@illinois.edu` | Verified; listings, purchases, sales and conversations |
| `mock_leo_02` | `mock_leo_02@illinois.edu` | Verified; a separate set of listings and activity |
| `mock_nora_03` | `mock_nora_03@illinois.edu` | Unverified; verification gate and initially empty business activity |

Newly generated passwords are written only to the ignored local file
`data/a5-preview-credentials.local.txt`. Open it locally; do not copy passwords
into this guide, screenshots or commits. Existing users keep their passwords.

### Start an initialized preview

PowerShell or Bash, from the activated repository root:

```bash
python manage.py runserver 127.0.0.1:8025 --settings=moveon.settings.a5_preview --noreload
```

Open [http://127.0.0.1:8025/](http://127.0.0.1:8025/); preview allows `127.0.0.1` only. Keep it on
loopback. Do not repeat first-time migration/seed just to start it. Apply genuinely
required schema updates with preview settings only, after backing up that file.

## Production configuration boundary

Use an independent persistent database, preferably outside the Git checkout,
for example `/home/<username>/moveon-data/production.sqlite3`. Replace placeholders
with confirmed server paths. Configure production's private `SECRET_KEY`,
`DATABASE_PATH`, `ALLOWED_HOSTS`, Google credentials and SMTP settings there.
Register `https://moveonbochen.pythonanywhere.com/accounts/google/login/callback/`
for the current production domain.

The project's `manage.py` and `moveon/wsgi.py` default to development. The actual
hosting WSGI configuration must select `moveon.settings.production` before Django
loads; setting it in a separate console does not configure existing Web workers.
Use the server's configured virtual environment and checkout when running manual
management commands. `runserver` commands above are for local development only.

For an existing production database, back it up before required migrations and
preserve its account/business data. Only a genuinely new, empty production
environment should initialize a new database. Never upload a local real-account,
preview or historical A4 database over production. Never run `seed_a4_data`,
`seed_demo_data` or `seed_a5_preview` against it. The account-specific command below
is a separate, deliberate operation. If production still uses the formerly tracked `data/db.sqlite3`,
preserve it outside Git before a code update can remove that file; keep writes
paused until any deliberate database-path switch is complete.

## Optional A4 demo activity for your own account

`seed_account_demo` adds fictional business records for the three existing private
charts; it does not prove real purchases, sales or inquiries occurred. The target
username must already exist and satisfy the current campus access rules. Its
credentials, email verification and Google identity are not changed.

After manually backing up the actual production database and synchronizing this
command's source code, use a PythonAnywhere **Bash console**. Replace all
placeholders below with the existing checkout, virtual environment, persistent
database and target username. The database path must match the Web worker's
working database; this is not a new database or a preview upload.

```bash
cd '/home/YOUR_PYTHONANYWHERE_USERNAME/YOUR_CHECKOUT_DIRECTORY'
source '/home/YOUR_PYTHONANYWHERE_USERNAME/.virtualenvs/YOUR_MOVEON_VENV/bin/activate'
export DATABASE_PATH='/home/YOUR_PYTHONANYWHERE_USERNAME/YOUR_EXISTING_DATABASE.sqlite3'
python manage.py seed_account_demo --username 'YOUR_EXISTING_USERNAME' --settings=moveon.settings.production
```

For deliberate local real-account use, run from the activated repository root
with your existing local database configured, replacing the target username:

```bash
python manage.py seed_account_demo --username 'YOUR_EXISTING_USERNAME' --settings=moveon.settings.development
```

The command maps A4's Maya role to the target account, without changing the
original Maya account or invoking another seed. It creates two dedicated Alex
and Jamie counterparts with target-linked identifiers, `@example.invalid` emails,
unusable passwords and inactive, non-admin, unverified accounts with no Google
identity. It creates no bundles, featured inventory or price recommendations.

| Demo record | Target role / initial result |
| --- | --- |
| Blue Sofa, Floor Lamp, Desk | Buyer; completed $65, $15, $33 purchases on September 21, 23, 25, 2026, at 12:00 UTC |
| Desk Chair | Seller; completed $18 sale to Demo Alex on September 27, 2026, at 12:00 UTC |
| Gray Rug | Seller; Demo Alex's three messages are read; Demo Jamie's single inquiry is unread |

Four completed-transaction listings are SOLD; Gray Rug remains ACTIVE. A4's
listing fields and dynamic move-out offsets are retained. Inquiry timestamps
use creation time, as in the original seed. Initially, Gray Rug has two inquiry
conversations: one answered and one unanswered under the current read-state
rule. Opening messages can change that state.

With no prior transactions, the unchanged ORM charts aggregate **$113 spent and
$18 earned**, with a cumulative timeline on the four dates above. Existing
transactions still contribute under the normal chart rules; no chart payload
is stored or totals forced. Gray Rug remains subject to the existing chart's
top-six listing limit if the account already has inquiry activity.

The command prints the actual database path, target and counts of newly created
participants, taxonomy entries, listings, transactions, conversations and messages;
it prints no credentials. A fresh run adds 2 participants, 5 listings, 4
transactions, 2 conversations and 4 messages, plus missing taxonomy. Stable
identifiers make an unchanged rerun add zero records. Existing edits are retained;
identifier, ownership or transaction/listing-state conflicts abort and roll back
the entire write transaction. There is no reset, backup or automatic startup hook.

## Actual SQLite backup and recovery

Preparing a working database means choosing its path, creating its parent
directory and applying migrations. A backup means creating a separate,
consistent snapshot of an existing database. Neither directory creation,
`DATABASE_PATH` nor `migrate` performs a backup.

### Create a consistent snapshot

The following instructions apply to the SQLite files used by all three
environments. On production, run them in the server's Bash console, with the
server's Python environment and confirmed absolute source/backup paths. Do not
substitute a local file for the production source.

For a running database, use SQLite's backup API rather than copying only its
main file; active journal/WAL data may be needed for consistency. Python's
[`Connection.backup()`](https://docs.python.org/3.12/library/sqlite3.html#sqlite3.Connection.backup)
supports active databases and produces a consistent snapshot through
[SQLite's online backup API](https://www.sqlite.org/backup.html). Before a schema
or database-path change, pause writes and keep them paused through the change.

Windows PowerShell, from the activated repository root. Replace the two paths
with your actual source and a new, uniquely named destination:

```powershell
$sqliteSnapshot = @'
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

source = Path(sys.argv[1]).resolve(strict=True)
target = Path(sys.argv[2]).resolve()
target.parent.mkdir(parents=True, exist_ok=True)
target.touch(mode=0o600, exist_ok=False)
with (
    closing(sqlite3.connect(source.as_uri() + '?mode=ro', uri=True)) as src,
    closing(sqlite3.connect(target)) as dst,
):
    src.backup(dst)
    if dst.execute('PRAGMA integrity_check').fetchone() != ('ok',):
        raise RuntimeError('Snapshot integrity check failed.')
print(target)
'@
$sqliteSnapshot | python - 'data/local.sqlite3' 'data/backups/local-YYYYMMDD-HHMM.sqlite3'
```

macOS/Linux Bash, from the activated repository root (or the server checkout for
production). Replace both paths before execution:

```bash
python - data/local.sqlite3 data/backups/local-YYYYMMDD-HHMM.sqlite3 <<'PY'
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

source = Path(sys.argv[1]).resolve(strict=True)
target = Path(sys.argv[2]).resolve()
target.parent.mkdir(parents=True, exist_ok=True)
target.touch(mode=0o600, exist_ok=False)
with (
    closing(sqlite3.connect(source.as_uri() + '?mode=ro', uri=True)) as src,
    closing(sqlite3.connect(target)) as dst,
):
    src.backup(dst)
    if dst.execute('PRAGMA integrity_check').fetchone() != ('ok',):
        raise RuntimeError('Snapshot integrity check failed.')
print(target)
PY
```

The source must exist; the destination must not exist. A failure is not a valid
backup, even if a partial destination remains. Use a new destination for the
next attempt. This snapshots database records only; preserve uploaded media
separately and keep backups/password files private.

### Restore deliberately, with writers stopped

1. Stop the local server and other writers; for production, stop Web workers and
   other jobs during a maintenance window. Take a separate snapshot of the current
   database before recovery. Match the backup's schema to the intended code version.
2. For development or production, restore a known-good snapshot to a **new file**,
   preserving the old working file. Local PowerShell example:

   ```powershell
   if (Test-Path -LiteralPath 'data/local-restored.sqlite3') { throw 'Restore target already exists.' }
   Copy-Item -LiteralPath 'data/backups/local-YYYYMMDD-HHMM.sqlite3' -Destination 'data/local-restored.sqlite3'
   ```

   Local macOS/Linux Bash equivalent:

   ```bash
   if [ -e data/local-restored.sqlite3 ]; then
       echo 'Restore target already exists.'
   else
       cp data/backups/local-YYYYMMDD-HHMM.sqlite3 data/local-restored.sqlite3
   fi
   ```

   Confirm that the copy succeeded before changing anything. For production,
   use confirmed persistent absolute paths on that server, outside Git.
3. Deliberately point development/production `DATABASE_PATH` to the restored
   file; also update an overriding process/WSGI value if present. This is an
   explicit recovery operation, not a requirement to move an existing database
   during normal setup. Apply migrations only if the chosen code requires them,
   after retaining the original snapshot.
4. Preview has a fixed path. With every preview process stopped, archive its
   existing `data/a5-preview.sqlite3` and any corresponding `-wal`, `-shm` or
   `-journal` files together in a separate recovery directory. Copy only a
   known-good standalone preview snapshot to `data/a5-preview.sqlite3`; do not
   pair it with old sidecars. Retain the matching local password file and media.
   Do not restore real-account or production data into preview.
5. Restart the appropriate environment and manually verify the restored accounts
   and business records. A local restore or integrity check does not establish
   production acceptance. Keep the prior files until recovery is confirmed.

## Optional checks and manual acceptance

Run checks manually only when there is a specific configuration, dependency or
code-change reason. They are not prerequisites for every startup. From the
activated repository root, these commands work in PowerShell or Bash:

```bash
python -m pip check
python manage.py check --settings=moveon.settings.development
python manage.py makemigrations --check --dry-run --settings=moveon.settings.development
python manage.py migrate --check --settings=moveon.settings.development
python manage.py test tests.marketplace.test_a5_accounts tests.marketplace.test_a5_access tests.marketplace.test_a5_charts tests.marketplace.test_google_oauth --settings=moveon.settings.development
```

`migrate --check` reports unapplied migrations; it does not apply them. Django
tests use a separate test database; keep the explicit settings and intended
environment. For preview configuration checks, substitute
`moveon.settings.a5_preview`. Run production configuration checks only in the
properly configured server environment, from its checkout and virtual environment:

```bash
python manage.py check --deploy --settings=moveon.settings.production
```

Local startup, mock activity and recorded tests do not prove deployed OAuth,
SMTP delivery, access rules or PNG behavior. Record actual production checks
separately using real production accounts.

The [existing local manual checklist](../A5_MANUAL_CHECKLIST_ZH.md) is present in
the maintained workspace but deliberately ignored by Git; this link is for local
use and the file is not included in fresh clones/GitHub. If absent in your checkout,
there is no bundled manual checklist. Its recorded paths and Git examples are
workspace history; use this guide for current setup instructions.
