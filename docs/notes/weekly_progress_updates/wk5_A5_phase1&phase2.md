# Week 5: A5 Part 1 & Part 2 key changes

This log records implementation changes and their reasons. Environment setup,
mock preview, database backup/recovery and optional checks are documented in the
[Week 5 setup guide](../week5_setup.md).

## 2026-10-08: Shared accounts and email verification

- Added `django-allauth[socialaccount]==65.19.7`, the account/socialaccount apps,
  Google provider foundation, custom adapter/backend and account middleware.
  The existing `marketplace.User`, password hashes and business relationships
  remain the shared account model.
- Added `CampusAccountAdapter` to normalize emails, enforce the project's
  `@illinois.edu` restriction and apply campus verification before allauth
  establishes a login session. `ListingSignupForm` delegates the email rule
  to this adapter while retaining duplicate and username/email conflict checks.
- Added `CampusAllauthBackend` to reuse the existing credential ambiguity and
  inactive/suspended-account rules in allauth's authentication integration.
- Password login now uses `perform_login()` and the existing Django session.
  Successful login returns to `/` or a validated same-host `next` address.
  Six-digit verification returns to login; POST logout invalidates the session.
- Added `email_state.py` to mirror MoveOn's campus proof into allauth
  `EmailAddress`. Registration, successful code verification, login checks and
  relevant `User.save()` calls synchronize the primary email and verified flag.
  Old email records become non-primary/unverified after an email change.
- `User.email_verified` and `email_verified_at`, together with account/domain
  checks, remain the authority for campus access. Provider email claims do not
  grant this permission. The save hook uses `existing_only=True` to avoid
  creating email metadata before allauth initializes a new social user.
- Retained the six-digit challenge and password-reset flow.
  `ACCOUNT_EMAIL_VERIFICATION="none"` prevents a second allauth email challenge;
  the project's campus verification checks still apply.
- Added `DATABASE_PATH` support to keep local account work independent of the
  legacy A4 dataset without changing the custom User schema or demo passwords.

## 2026-10-08: Fixed access rules and navigation

- Removed `A4_ASSIGNMENT_MODE` and `A4_DEMO_USERNAME` dependencies from settings,
  middleware, adapter, chart code and templates; removed the unused
  `marketplace/assignment.py`. Feature permissions no longer change with a
  global environment switch.
- `CampusAccessMiddleware` applies a fixed public-route list before business
  views execute. Campus access is required elsewhere; existing object ownership
  and conversation-participant checks remain in the corresponding views.

| Features | Access rule |
| --- | --- |
| Home, active listing browse/details, account workflows, listing API documentation | Public entry; existing method, CSRF and credential checks apply |
| `/api/listings/` | Public business JSON API; existing fields, filters and pagination retained |
| Reports HTML/CSV/JSON, currency API, personal chart data/specs/PNGs, messages, uploads, publishing/editing and bundles | Login and campus email verification; applicable ownership checks retained |
| Django Admin | Django administrator authentication and permissions |

- Private JSON/API requests return structured 401 for anonymous users and 403
  for authenticated users lacking campus access. Private HTML/PNG GET requests
  redirect to the account page with `next`; unauthorized ordinary writes return
  403. Uploads retain their existing login check and gain the shared campus gate.
- Added a shared campus-access context processor. Protected navigation, report
  links, Bundle actions and currency controls follow the same permission rule
  as the server; the public listing contact entry still requires authentication
  before accessing Messages.
- Made browse/favorites JavaScript tolerate missing protected controls.
  Anonymous search, filtering, sorting, USD prices and browser-local favorites
  continue to work without calling the private currency API.
- `/charts/` now displays personal charts using the current authenticated user.
  Existing paths and the compatibility name `a4-charts` remain. Removed the
  demo-user selection and signed `render_token` authorization channel.
- Preserved A4 specifications, screenshots and seed commands as historical
  materials; its database snapshot remains in `2fbfe4f`. Business routes and
  exports remain available under the fixed permissions.

## 2026-10-09: Private PNG subprocess execution

- `charts.py` authorizes the original request and queries its current-user data
  before rendering. Failed specification/data responses return immediately.
  Django sends only `spec`, `payload` and the resolved `data_path` through stdin;
  it no longer starts a relay server or relay thread.
- Added standalone `png_renderer.py`. A request-scoped child starts an exact-path
  HTTP relay on `127.0.0.1` with an ephemeral port, serving only the authorized
  snapshot. It has no Django/ORM, session or database access.
- The relay child starts a short-lived rendering descendant because conversion
  with `vl_convert 1.9.0` blocks Python relay threads in the same process.
  The descendant reads the local `data.url` and returns real PNG bytes via stdout;
  rendering does not request the production website or inline `data.values`.
- Retained virtual-environment interpreter selection through `sys.prefix` and
  the 30-second worker timeout. The internal renderer uses a 28-second wait to
  leave time for cleanup. Success/failure closes the relay and joins its thread;
  worker timeout terminates the request process tree and reaps the child.
- Private snapshots are absent from command arguments, application logs and
  product temporary files. Child diagnostics are fixed messages; Django logs
  only interpreter, exception type and return code. Failures retain the
  controlled 502 response.
- Adjusted account/access/chart/renderer tests for the shared account rules,
  fixed permissions, current-user isolation, real URL-backed PNGs, empty data,
  sequential requests, startup/render failures and actual timeout cleanup.

## 2026-10-09: Google OAuth and explicit account connection

- Replaced browser GIS credential submission with django-allauth Google OAuth
  authorization-code login/callback. Kept POST/CSRF initiation, session-bound
  state and PKCE; login/signup retain the existing custom account page.
- Added a social adapter enforcing Google's verified campus email and stable
  subject. Google verification cannot replace the local six-digit challenge:
  new Google users have unusable passwords and sign in with Google after their
  campus email is verified. Password and Google login share User/session/access.
- Linked identities reuse allauth SocialAccount by subject. Existing historical
  `google_subject` links are bridged after identity/email checks. Same-email
  accounts do not merge anonymously; qualified users connect the same campus
  Google email explicitly from Settings. Connections cannot take another user's
  identity or add a different Google identity to the same account.
- Google cancellation, malformed identity responses, provider failures and
  account conflicts (including retained historical email metadata) return
  readable feedback without a second signup page. Protected return paths survive
  verification; external return URLs are rejected. Removed the old token verifier,
  popup-specific response header and GIS JavaScript; `/account/google/` remains
  a compatibility entry that starts OAuth without trusting browser credentials.
- Provider credentials are read from environment settings rather than SocialApp
  records; social access/refresh tokens are not stored. Added the client-secret
  placeholder and OAuth round-trip tests in place of obsolete token tests.

## 2026-10-09: Isolated A5 preview data and database boundaries

- Removed Git tracking of `data/db.sqlite3` while retaining the local file and
  the historical A4 snapshot in `2fbfe4f`. Only `data/.gitkeep` is allowed in the
  current data directory's submission; runtime SQLite files, sidecars, backups,
  exports, environment credentials and preview password/media files are ignored
  so development or production account data does not enter future commits.
- Added `moveon.settings.a5_preview` with a fixed dedicated database and media
  directory, console email and loopback host. It skips `.env` loading and real
  Google/Gemini credentials without changing authentication or business access.
- Added `seed_a5_preview` with both settings and resolved-database-path guards.
  It creates two verified ordinary mock users and one unverified user, hashes
  generated temporary passwords, and synchronizes allauth email metadata through
  `sync_campus_email`; it creates no administrator or social identity.
- Added distinct mock listings, completed/pending/cancelled transactions and
  replied/unanswered conversations. Personal charts continue to aggregate those
  real model records; deterministic UUIDs reuse seeded objects, and reruns retain
  existing passwords, verification and business edits rather than resetting them.

## 2026-10-09: Shared navigation and account feedback

- Moved header initialization into the common marketplace base template, outside
  the page-specific script block. Listing details, forms, reports, charts and
  bundle pages now load the same unread-badge behavior as browse/profile/messages.
- Removed the duplicate browse/profile and Messages initialization entries;
  refreshed the marketplace module URL to avoid cached page scripts starting a
  second poller. Retained the 15-second poll, visibility refresh, unread-change
  event and existing permission handling without changing the messaging API.

- Made Message Seller visible to anonymous visitors on listing detail pages;
  the listing owner still does not see a self-contact button. The existing
  protected Messages URL keeps the listing in `next` while login and campus
  verification are completed, so visitors can continue to the intended item
  conversation without granting anonymous messaging access.

- Added one shared notification partial to consume Django messages on every
  full marketplace page, including account dialogs. Login feedback no longer
  waits in browser storage until Settings or Bundle is visited, preventing
  historical sign-in notices from accumulating across account changes.
- Removed the separate Settings and Bundle message loops to avoid displaying
  the same notice twice. Reused existing notification styling and retained
  success/error feedback without changing authentication or business data.

## 2026-10-10: Optional production-safe demo catalogue

- Extended `seed_account_demo` with `--include-catalog` while retaining its
  original private-chart-only behavior. Added separate available A4 stock so
  completed chart examples remain SOLD, and restored the six reference items
  required by the existing Featured Bundles scenes and static image lookup.
- Added dedicated inactive Demo Sam and MoveOn Demo identities with unusable
  passwords and `@example.invalid` emails. Mock sellers provide fictional
  inventory without gaining campus access, administrator privileges or Google
  identities; real-account authentication and teammates' Part 3 code are unchanged.
- Reused stable account-specific stock IDs and shared featured-item IDs, with
  ownership/identity checks and one transaction for the complete operation.
  Reruns preserve existing edits, and conflicts abort instead of overwriting
  accounts or records. No database snapshot, photo uploads or real credentials
  are added to Git.
