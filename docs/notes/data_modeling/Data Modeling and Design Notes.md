# Part 4 — Data Modeling & Admin Kickoff: Design Notes

## Project / App Naming

- `moveon` — the overall Django project (settings, URLs, WSGI/ASGI). Named after the product.
- `marketplace` — the core listing/browsing/buying/selling domain, plus the custom `User` model and `Transaction` (see rationale below).
- `bundles` — the Move-In Bundle domain: a buyer assembling a set of listings for one space (Living Room, Bedroom, etc.).
- `messaging` — buyer/seller conversations and messages, kept unified (no separate "buying inbox" vs "selling inbox").

## Environment

Development uses a dedicated conda environment, `moveon-env` (Python 3.12), with dependencies installed exactly from `../../../requirements.txt` (Django 6.1.1). This matches the README's documented setup instructions exactly, so anyone following the README ends up with the same environment used to build and test this submission.

## Model Scope

The full ER (11 models across 3 apps) was implemented rather than the assignment's smaller suggested range (3-5 models), because these models already existed in the team's agreed product design and each maps to a real workflow (listings, pricing, bundles, transactions, messaging). No models were added beyond what the ER specifies.

| App | Models |
|---|---|
| `marketplace` | `User`, `ItemCategory`, `ItemType`, `Listing`, `PriceRecommendation`, `Transaction` |
| `bundles` | `Bundle`, `BundleCategory`, `BundleItem` |
| `messaging` | `Conversation`, `Message` |

## Why `User` and `Transaction` live in `marketplace`

Considered putting `User` in a dedicated `accounts` app (a common Django convention, since `AUTH_USER_MODEL` can never be changed after the first migration without rebuilding the database) and `Transaction` in a dedicated `transactions` app. Decided against both:

- **`User`**: every other model references it via `settings.AUTH_USER_MODEL` as a string, not a direct import, which is exactly the mechanism Django provides to avoid tight coupling regardless of which app hosts it. Given this project intentionally minimizes app count, keeping `User` in `marketplace` costs nothing functionally.
- **`Transaction`**: represents purchasing a `Listing` — a core marketplace behavior, not a distinct bounded concern like payments/refunds (explicitly out of scope for this project). No Django convention pushes this into its own app the way there is for custom user models.

## `on_delete` Justifications

| Relationship | on_delete | Why |
|---|---|---|
| `ItemType.category -> ItemCategory` | `PROTECT` | A broad category shouldn't be deletable while specific item types still depend on it. |
| `Listing.seller -> User` | `CASCADE` | A listing has no meaning once its seller account is gone; acceptable simplification for Part 4. |
| `Listing.item_type -> ItemType` | `PROTECT` | Listings shouldn't lose their category classification silently. |
| `PriceRecommendation.listing -> Listing` | `CASCADE` | A recommendation has no meaning without its listing. |
| `Transaction.listing/buyer/seller` | `PROTECT` | Transactions are historical records; deleting a listing or user shouldn't erase completed marketplace history. |
| `Transaction.bundle/bundle_item` | `SET_NULL` | Optional bundle context; a transaction should survive even if its originating bundle metadata is later removed. |
| `Bundle.buyer -> User` | `CASCADE` | A bundle is meaningless without its buyer. |
| `BundleCategory.bundle -> Bundle` | `CASCADE` | Deleting a draft bundle should clear its requested categories. |
| `BundleCategory.item_type -> ItemType` | `PROTECT` | Item types are shared taxonomy; shouldn't be deletable while referenced by a bundle's requirements. |
| `BundleItem.bundle -> Bundle` | `CASCADE` | Same reasoning as `BundleCategory.bundle`. |
| `BundleItem.listing -> Listing` | `PROTECT` | A listing tied to active/historical bundle activity shouldn't be casually deleted. |
| `Conversation.listing/bundle_item` | `SET_NULL` | A conversation should be able to outlive the listing/bundle item that originally contextualized it. |
| `Conversation.buyer/seller -> User` | `CASCADE` | A conversation has no meaning without its participants. |
| `Message.conversation -> Conversation` | `CASCADE` | Messages have no standalone meaning outside their conversation. |
| `Message.sender -> User` | `CASCADE` | Same reasoning as other User-owned records. |

## Multi-Field Uniqueness Constraints

- `ItemType`: `UNIQUE(category, item_type_name)` — the same item type name can exist under different categories, but not twice under the same one.
- `BundleCategory`: `UNIQUE(bundle, item_type)` — a buyer can't request the same item type twice in one bundle.
- `BundleItem`: `UNIQUE(bundle, listing)` — the same listing can't be attached to a bundle twice.
- `Conversation`: `UNIQUE(buyer, seller, listing)` — prevents duplicate threads for the same buyer/seller/listing combination (only meaningfully applies to normal-listing conversations, since `listing` is nullable for bundle-item conversations — an accepted quirk from the source design, not a bug).

## Superuser~~~~

Username `admin`, password `uiuc12345` (course-mandated password). The original assignment text gave two conflicting usernames in different sections (`mohitg2` and `tester`); `admin` was chosen instead to resolve the ambiguity cleanly rather than guessing which was authoritative.

## Validation Demonstrations (*Refer to "Constraint Validation Evidence.md")

1. **Single-field uniqueness** — `ItemCategory.category_name`: attempted to create a second `Furniture` category; Django Admin rejected the save with a "already exists" validation error before it reached the database.
2. **Multi-field uniqueness** — `ItemType (category, item_type_name)`: created `Sofa` under `Furniture` twice; second attempt was rejected. Creating `Sofa` under a *different* category (`Electronics`) succeeded, confirming the constraint is scoped to the pair, not the name alone.
3. **`PROTECT` behavior (single app)** — attempted to delete the `Furniture` `ItemCategory` while `ItemType` rows referenced it; deletion was blocked.
4. **Multi-field uniqueness (`bundles`)** — attempted to add the same `ItemType` twice to one `Bundle` via `BundleCategory`; second attempt was rejected.
5. **`PROTECT` behavior (cross-app)** — attempted to delete a `Listing` that was attached to a `Bundle` via `BundleItem`; deletion was blocked, proving `Listing -> BundleItem` uses `PROTECT` so bundle history can't silently lose its underlying listings.
6. **`CASCADE` behavior** — created a `Conversation` with 3 `Message` rows, then deleted the `Conversation`; all 3 messages were deleted along with it, confirming `Message.conversation` uses `CASCADE`.

## Seed Data

Realistic demo data is created via `python manage.py seed_demo_data` (a Django management command, `../../../marketplace/management/commands/seed_demo_data.py`), rather than only manual Admin entry, so it's reproducible and reviewable in source control. It creates:

- 4 student users (Alex, Jamie, Sam, Maya) plus the `admin` superuser.
- 4 item categories and 10 item types.
- 8 listings spread across the 4 users.
- 2 price recommendations (one pending, one modified/applied).
- 1 Living Room bundle (buyer: Sam) with 3 requested categories (Sofa/Rug/Lamp) and 3 matching bundle items sourced from Alex, Maya, and Jamie's listings — deliberately cross-seller, since Sam owns none of the three, avoiding a buyer "purchasing" their own listing.
- 1 conversation with 3 messages.
- 1 completed transaction (Desk Chair, Maya → Alex, $18 agreed vs. $24 benchmark — demonstrates the buyer-savings calculation the Profile dashboard will later derive: `24 - 18 = 6`).

The command uses `get_or_create` throughout, so re-running it is safe and won't collide with the manually-created test data used for the validation demonstrations above.

## Known Deviations From the Design Doc (Reviewed, Not Oversights)

A teammate audit flagged a few differences between this implementation and the team's original wireframes/ERD doc. Each was a deliberate call made in `MoveOn_Claude_Code_Django_Context.md` (the implementation spec this project was built from), which explicitly superseded the earlier design doc on these points:

- **`Bundle.selected_tier`, not `source_tier`** — the design doc used `source_tier` in places, but the implementation spec explicitly says: "For Part 4, stay aligned with the current ER and use `selected_tier`."
- **`BundleCategory.item_type -> ItemType`, not `-> ItemCategory`** — the design doc's relationship summary describes a broad-category link, but the implementation spec explicitly clarifies: "The ER concept `BundleCategory` refers to a bundle's selected *specific item types* (Sofa, Rug, Lamp, Television) ... Do not link BundleCategory to the broad ItemCategory model." Examples throughout are specific item types, not broad categories.
- **`Transaction` has no uniqueness constraint against `Listing`** (i.e. a listing can have more than one `Transaction` row) — the spec's own relationship summary states "Listing 1 -> zero/many transaction records depending [on] implementation/history," leaving this intentionally unconstrained rather than limited to one completed sale per listing.
- **Login uses `username`, not `email`** — the spec explicitly allows this: "it is acceptable for `username` to remain Django's standard login/admin identifier while `email` is unique and represents the university email."
- **`image_url` / `meetup_location` use `blank=True` (empty string) rather than `null=True`** — standard Django convention for optional text fields (avoids two different "no value" states, `NULL` vs. `''`, for the same field); not a data-loss or validation gap.

If the team's canonical ERD doc is later revised to remove these allowances, these five points are exactly what would need to change in `../../../marketplace/models.py` / `bundles/models.py`.

## Participant Integrity Follow-Up

A later review identified several participant-integrity gaps in the original Part 4 model implementation. These issues were addressed in the separate `PARTICIPANT_INTEGRITY` follow-up. If the team submits or preserves the original code without merging that follow-up, the points below should remain documented as known issues rather than being treated as already enforced by the base model.

### Key Issues Identified and Fixed in the Follow-Up

1. **Buyer and seller could be the same user**
   - The original models did not prevent a `Transaction` or `Conversation` from using the same `User` as both buyer and seller.
   - The follow-up adds validation and database `CheckConstraint`s requiring buyer and seller to be different users.

2. **Transaction / conversation seller could disagree with the Listing owner**
   - The original models allowed a record such as a `Transaction` whose `seller` was not the actual `Listing.seller`.
   - The follow-up requires the seller to own the referenced `Listing`, and the Listing owner cannot simultaneously be the buyer.

3. **Conversation context could be incomplete or inconsistent**
   - The original model allowed a new `Conversation` with no selected `Listing`, and a supplied `BundleItem` could theoretically point to a different Listing from `Conversation.listing`.
   - The follow-up requires new conversations to have an explicitly selected `Listing`. If a `BundleItem` is supplied, it must reference that same Listing.
   - Existing historical conversations whose Listing later becomes `NULL` through `SET_NULL` remain valid so message history can be preserved.

4. **A nonparticipant could be recorded as the sender of a Message**
   - The original `Message.sender` was only a foreign key to `User`; it did not ensure that the sender was either the conversation buyer or seller.
   - The follow-up restricts `Message.sender` to the two participants in the referenced `Conversation`.

5. **Later edits could silently invalidate existing participant relationships**
   - In the original model, changing `Listing.seller`, changing `BundleItem.listing`, or changing conversation participants could make already-existing transactions, conversations, or messages inconsistent.
   - The follow-up blocks these edits when dependent participant records already exist, including participant changes that would leave old messages attributed to a nonparticipant.

### Enforcement Notes

The follow-up uses model validation for the cross-table relationship rules and database `CheckConstraint`s for the direct buyer/seller inequality rules. Operations that bypass normal model validation—such as `QuerySet.update()`, bulk operations, raw SQL, or certain concurrent writes—do not receive all of the same cross-table guarantees.

The follow-up does **not** change transaction lifecycle/uniqueness policy, account deletion policy, or timestamp-based message uniqueness rules. Those remain separate design decisions.

## Reproducing This Setup From Scratch

```bash
conda create -n moveon-env python=3.12 -y
conda activate moveon-env
pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser   # username: admin, password: uiuc12345
python manage.py seed_demo_data
python manage.py runserver
```
