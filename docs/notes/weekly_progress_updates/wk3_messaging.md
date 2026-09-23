# Week 3: Messaging phase two

This update covers the desktop `/messages/` MVP and its integration with the
existing Django accounts, listings, and Bundle data. It uses the approved
exported HTML, scoped CSS, and vanilla JavaScript with the shared marketplace
header. The real page reads Django APIs; it has no mock-data fallback.

## Access and conversation rules

Messages requires an active, unblocked, locally verified `@illinois.edu`
account. Django Admin login alone does not grant campus access. The server
determines participants and roles, checks them on conversation and attachment
requests, and retains CSRF protection on writes. A listing's **Message seller**
link creates or reuses a conversation at `/messages/?listing=<id>`.

The conversation list covers All, Buying, and Selling, with server-side search
across accessible listing titles and contact names. History loads 30 messages
at a time and polls for newer messages. Only incoming messages actually shown
are marked read. The shared header polls the authorized unread total and uses
the shopping bag badge style. Product removal or unavailability does not erase
the saved chat history.

## Local workflow

Install dependencies as described in the [README](../../../README.md). From
the repository root in PowerShell, use an isolated preview database:

```powershell
& .\.venv\Scripts\python.exe manage.py migrate --settings=moveon.settings.messaging_preview
& .\.venv\Scripts\python.exe manage.py seed_messaging_preview --settings=moveon.settings.messaging_preview
& .\.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8000 --settings=moveon.settings.messaging_preview
```

The seed command prints temporary passwords for `alex` and `maya`. Run it only
when you need those accounts: rerunning can reset their passwords. Open
`http://127.0.0.1:8000/messages/`. Preview settings use
`data/messaging_preview.sqlite3` and `data/messaging_preview_media/`; they do
not touch the normal `data/db.sqlite3`. Both preview paths are Git-ignored.
Switching branches does not itself erase them, but a different checkout or
machine has its own local data.

You can also register a new campus account in preview. Its verification code
appears in the server terminal, with no real email delivery. After verification
and login it uses the same page and APIs. Google login needs a configured web
client ID and authorized local origin; a first successful Google token creates
an account that still needs MoveOn's campus verification. Existing password
accounts are not automatically linked to Google by matching email.

## Messaging behavior and integration

- API route templates are passed from Django to JavaScript. Draft text and
  pending attachments stay per conversation in browser memory for the tab.
  Stable client request UUIDs make retries idempotent.
- A message can contain text or up to three JPEG, PNG, WebP, or GIF images, each
  at most 10 MiB. When composed together, images are saved first as one
  message, then text as a second message. An upload in progress or in error
  blocks the incomplete send.
- Images are stored under private `MEDIA_ROOT` and retrieved through the
  participant-checked attachment endpoint. Clicking a chat image opens a
  blurred-background viewer with a close button and mouse-wheel zoom.
  Run `manage.py cleanup_message_uploads` periodically to remove unbound
  uploads older than 24 hours.
- Bundle request cards use `BundleItem` state and the saved offer or snapshot
  price, so later listing price changes do not rewrite the historical request.
  Only the relevant seller may decide that specific request. Acceptance creates
  a `Transaction` in `PENDING_PICKUP` and reserves the listing; it does not
  mark the transaction completed. Decline updates that item. Repeated or stale
  decisions return the saved result or a conflict.
- The supplied Bundle builder snapshot has not been merged into this branch.
  For an existing assembled Bundle, the protected `bundle_send_requests`
  endpoint sends requests once and returns a Messages link. When the builder
  is merged, its summary submission should call that endpoint or service.

The project has no listing creation or Profile page yet. **Sell** keeps its
existing explanatory dialog; **Bundle** opens the existing bundle-filtered
marketplace. Tests live under `tests/messaging/` and `tests/marketplace/`.
Preview settings and the seed command remain Django runtime entry points
because the local server uses them. No public deployment or production
database migration was performed for this update.

## Manual testing

This is a roughly 10-minute hands-on check. Use two verified campus accounts
A and B in separate browsers or private sessions, plus one active listing from
B. The preview seed supplies accounts if needed; record the passwords it
prints. To create disposable PNGs of about 6.4 MiB and 12.6 MiB in the system
temporary directory, run:

```powershell
& .\.venv\Scripts\python.exe tests/messaging/manual_test_images.py
```

1. **Guest return route:** Log out and click **Message seller** on B's
   listing. After one failed login, close the account overlay, click the
   profile icon, and log in successfully: the destination should be home.
   Log out again, use **Message seller**, and log in successfully: the
   destination should be that listing's Messages conversation. Switching
   **Create account / Log in** must preserve the active destination.
2. **Messages and unread badge:** A sends B a text message. On B's home page,
   the Messages badge should increase within 15 seconds and match the bag
   badge's color. Open the conversation, view the message, and confirm the
   badge falls. Refresh to confirm that the conversation persists.
3. **Image plus text:** B selects a valid image and enters text. Sending
   should produce two messages in order: image, then text. Refresh and check
   both. Click the image; the background should blur, the wheel should zoom,
   and the upper-right × should close the viewer.
4. **Desktop layout and navigation:** At 1366×768 and 1440×900, the composer
   should stay visible while the list and history scroll independently.
   Check the Logo, Messages navigation, and browser back/forward.
5. **Limits and pending uploads:** A file above 10 MiB and a fourth image
   should be rejected. Sending while an upload is pending or failed must not
   silently send only the text.
6. **Conversation isolation and retry:** Select an image in conversation A,
   switch to B, and confirm B has no A attachment. Returning to A should
   retain its draft and attachment. Temporarily disconnect the network,
   send, reconnect, and use **Retry**; only one copy of each message should
   persist. If an image part fails, its text part should wait.
7. **Permissions:** A third user must not read the conversation or attachment
   URL (attachment request returns 404). Inactive, blocked, and unverified
   users cannot enter Messaging. Optionally register a fresh campus account,
   read its code in the terminal, verify it, and confirm access afterward.

Automated regression commands:

```powershell
& .\.venv\Scripts\python.exe manage.py test tests.messaging --settings=moveon.settings.development
& .\.venv\Scripts\python.exe manage.py test --settings=moveon.settings.development
& .\.venv\Scripts\python.exe manage.py check --settings=moveon.settings.development
& .\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run --settings=moveon.settings.development
```

These tests use a disposable Django test database and do not call real email
or Google services. The preview uses its own local SQLite database and media.

## Test evidence and remaining checks

On 2026-09-23, the full local suite passed 98 tests in 41.484 seconds.
`check` reported no issues, `makemigrations --check --dry-run` found no model
changes, and both Messaging and shared-header JavaScript passed `node --check`.
The earlier desktop browser pass checked the login return route, unread badge,
split image/text send, image viewer, and composer visibility at 1366×768 and
1440×900. The offline retry and a real Google/SMTP round trip still need
hands-on checks in their corresponding environments.
