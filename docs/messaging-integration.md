# Messaging phase two integration

The desktop `/messages/` page uses the approved handoff HTML, scoped CSS, and a vanilla JavaScript controller. It shares the marketplace header and requires the existing campus account checks. The production page has no mock data path.

## Local preview

From the repository root in PowerShell:

```powershell
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt
& .\.venv\Scripts\python.exe manage.py migrate --settings=moveon.settings.messaging_preview
& .\.venv\Scripts\python.exe manage.py seed_messaging_preview --settings=moveon.settings.messaging_preview
& .\.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8000 --settings=moveon.settings.messaging_preview
```

The seed command prints temporary passwords for `alex` and `maya`. Visit `http://127.0.0.1:8000/messages/`. This settings module uses `data/messaging_preview.sqlite3`, private media in `data/messaging_preview_media`, and an in-memory email backend. It does not touch `data/db.sqlite3`.

Run tests with:

```powershell
& .\.venv\Scripts\python.exe manage.py test marketplace messaging bundles --settings=moveon.settings.development
```

## Integration points

- A marketplace listing card links to `/messages/?listing=<id>`. The page calls the protected create-or-reuse endpoint and opens the conversation.
- The server supplies route templates to the JavaScript controller through `messaging_config`; CSRF remains enabled. The API checks campus eligibility and conversation participation.
- Conversation lists search all accessible records. Message history loads in pages of 30, polls incrementally, and marks only visible incoming message IDs as read.
- Images are JPEG, PNG, WebP, or GIF, at most 5 MB each and three per message. Files stay under `MEDIA_ROOT` and are served only through the participant-checked attachment endpoint. Run `manage.py cleanup_message_uploads` periodically to remove unbound uploads older than 24 hours.
- Client request UUIDs make message retries idempotent. Browser drafts are kept in memory per conversation for this tab.
- Bundle request cards use `BundleItem` state and its saved offer/snapshot price. Accepting one creates a `Transaction` in `PENDING_PICKUP` and reserves the listing; it does not mark the transaction completed. Declining updates that specific item. A repeated decision returns the existing result or a conflict.
- The supplied Bundle snapshot is not merged into this branch. For already assembled Bundles, the protected `bundle_send_requests` endpoint sends requests once and returns a Messages link. When the Bundle builder is merged, its summary submission should call that endpoint or its service rather than copying the snapshot's non-idempotent loop.

The existing project has no listing creation or Profile page. The shared Sell action retains its existing explanatory dialog; Bundle links to the existing bundle-filtered marketplace view. No public deployment or project database migration was performed.
