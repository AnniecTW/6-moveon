# Week 4: Messaging offers and trade status

This note describes the current `/messages/` deal flow. The original
[Week 3 Messaging note](wk3_messaging.md) records the
earlier chat MVP; its snapshot statements are kept for historical context.

## Where the data lives

- `Conversation` identifies the buyer, seller, and listing. Existing `Message`
  records still hold chat text and images; offer cards are not chat messages.
- [`DealProposal`](../../../messaging/models.py) stores each seller's final price,
  status, previous version, request UUID, and eventual transaction link.
  Migration `messaging.0007_deal_proposal` adds this table without rewriting old
  conversations. At most one offer per conversation can await the buyer.
- The existing `Transaction` records the real buyer, seller, agreed price, and
  `PENDING_PICKUP` status. The listing becomes `RESERVED` after a successful
  confirmation; its public price is not changed.
- [`trade_data()`](../../../messaging/api.py) gives the conversation list and
  detail pane one server-derived state and set of allowed actions. It checks
  this conversation's real pending transaction first, then listing availability,
  then the current offer or Bundle request. An unrelated buyer sees
  **Unavailable** without the other buyer's price.

## Pending Pickup: current reservation behavior

**Pending Pickup means the item has been reserved for an agreed transaction.**
It is a transaction state, not a prediction inferred from chat text.

| Record or entry point | Current behavior after successful confirmation |
| --- | --- |
| `Transaction.status` | `PENDING_PICKUP`; records the actual participants and agreed price. |
| `Listing.status` | Changes from `ACTIVE` to `RESERVED` in the same database transaction. It is not changed to `INACTIVE`. |
| Public Marketplace list/search | The item is excluded because `browse_context()` selects only `ACTIVE` listings. |
| Public listing detail URL | Returns 404 because `ListingDetailView.get_queryset()` selects only `ACTIVE` listings, including for the transaction participants using that public route. |
| Existing Messaging conversation | Remains available to its participants; shows Pending Pickup and the agreed price. Chat and attachments remain usable. |
| Other buyers' conversations | Show Unavailable without revealing the winning buyer's transaction price; waiting ordinary offers become unusable. |

The listing is not deleted. `RESERVED` describes a transaction reservation;
`INACTIVE` describes a separate unavailable listing state. Pending Pickup does
not mean payment has been collected, the item has been picked up, or the sale
has been completed. This MVP has no completion/cancellation flow, reservation
expiry, or automatic restoration to `ACTIVE`.

Source checks: [`browse_context()`](../../../marketplace/browse.py),
[`ListingDetailView`](../../../marketplace/views.py), and
[`reserve_listing()` / `trade_data()`](../../../messaging/api.py).

## Ordinary listing flow

1. Buyer and seller chat. The seller selects **Start Deal**, enters a final
   price, and confirms willingness to sell. The server validates the Decimal
   price, seller identity, listing, and `clientRequestId` before storing an
   `awaiting_buyer` proposal.
2. **Edit Offer** creates a new proposal and marks the old one `superseded`.
   **Withdraw** and buyer **Decline** end the current proposal. Historical
   cards remain readable but cannot be confirmed.
3. The buyer's **Accept** action names one proposal ID. In one database
   transaction, the server checks that version, conditionally reserves an
   `ACTIVE` listing, creates the Transaction, marks the proposal `confirmed`,
   and invalidates other buyers' waiting offers for that listing. A repeated
   successful confirmation returns the original transaction.
4. If the listing is saved as non-`ACTIVE`, `Listing.save()` permanently marks
   waiting offers `unavailable` in the same transaction. Returning the listing
   to `ACTIVE` does not reactivate those offers.

SQLite does not provide row-lock behavior equivalent to PostgreSQL here. Both
ordinary confirmation and Bundle acceptance use the same conditional
`ACTIVE` → `RESERVED` update, so only one path can reserve a listing. Offer
creation and revision also serialize their listing check with that write.

## Bundle and interface behavior

Bundle requests still follow **buyer sends → seller accepts or declines**.
Acceptance creates a pending-pickup Transaction with the existing Bundle price
rules; there is no second buyer confirmation. A pending Bundle request blocks
new or revised ordinary offers in that conversation. If an ordinary offer
already exists when a Bundle request arrives, neither is cancelled
automatically; the first successful reservation wins. The other offer becomes
unavailable, while the Bundle request record remains in history.

The compact UI shows one status badge beside the listing title, role tags under
sidebar thumbnails, Bundle and offer cards above the chat messages, and deal
dialogs. Buttons follow `trade.allowedActions`; the browser never decides the
transaction price or displays Pending Pickup before the server confirms it.
Polling refreshes offers and trade state even without new chat messages, while
keeping drafts and an open dialog's input. If that dialog's proposal changes,
its old confirmation controls are disabled.

## Local verification

Use the [README Messaging steps](../../../README.md#testing-message-seller--messaging-locally)
for the isolated preview database and manual flows. Its seed command adds
these named examples for Alex (seller) and Maya (buyer):

| Preview listing | Alex sees | Maya sees |
| --- | --- | --- |
| Negotiating desk | Negotiating | Negotiating |
| Bundle request pending | Action needed | Waiting for response |
| Revised offer awaiting buyer | Waiting for response | Action needed |
| Offer reserved for pickup | Pending pickup | Pending pickup |
| Bundle accepted for pickup | Pending pickup | Pending pickup |
| Bundle request declined | Declined | Declined |
| Unavailable listing | Unavailable | Unavailable |

Jamie has a separate conversation for the accepted Bundle listing and sees
Unavailable without Maya's price. Rerunning the seed adds missing examples
without duplicating them or replacing existing preview passwords.

Focused automated checks:

```powershell
& .\.venv\Scripts\python.exe manage.py test tests.messaging --settings=moveon.settings.messaging_preview
& .\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run --settings=moveon.settings.messaging_preview
node --check static/messaging/messaging.js
```

## Verification snapshot (2026-09-28)

- The focused `tests.messaging` and
  `tests.marketplace.test_listing_detail_messaging` suites passed **45 tests**
  using an isolated Django test database and temporary media. Neither existing
  development nor preview data was used for test writes.
- Migration consistency (`makemigrations --check --dry-run`), JavaScript syntax,
  and `git diff --check` passed.
- A delayed-response Node check passed **12 dialog cases**: create, edit,
  confirm, and decline with the original dialog open, closed, or replaced.
  Offer and decision callbacks now close only their own dialog; their results
  still update the original conversation. This check did not add a test file.
- Earlier implementation work reported 184 full-suite tests and browser checks
  at 1366×768 and 1440×900. Those checks were not rerun for this snapshot.

A read-only check found `messaging.0007_deal_proposal` applied in both the
regular development and isolated preview databases. This review did not run
migrations or write either database. Payment, pickup scheduling, completion,
and cancellation remain outside this Messaging update.
