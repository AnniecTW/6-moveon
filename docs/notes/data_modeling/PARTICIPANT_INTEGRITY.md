# Participant integrity rules

This P1 follow-up implements A1–A5 and the agreed A6 creation rule.

## Transactions and conversations

- Buyer and seller must be different users. Database CheckConstraints also enforce this when model validation is bypassed.
- The seller must own the referenced Listing; its owner cannot be the buyer.
- Conversation creation requires an explicitly selected Listing, including bundle conversations. An optional BundleItem must point to that same Listing.
- Conversation.listing remains nullable with SET_NULL: deleting a listing preserves existing conversations and messages. Existing orphaned history can be edited. Manually clearing a still-existing listing is rejected.
- Existing null-listing historical records, including unchanged legacy bundle-only conversations, are accepted; the database does not record whether they became null through deletion. A new null-listing conversation is rejected by validated creation. Adding/changing bundle context on an orphan requires selecting its Listing.
- Listing ownership cannot change once transactions or conversations reference it. A BundleItem's listing cannot change while a conversation references it. These guards avoid making existing participant records inconsistent through parent edits.

## Messages and editing

Only the conversation's buyer or seller may be Message.sender. Both participants can send messages, including in retained historical conversations. Changing participants is rejected when it would leave existing messages attributed to a nonparticipant.

Model clean() supplies field-level errors to Django Admin. Ordinary instance save() and objects.create() also run full_clean(). Partial saves validate the resulting stored field combination rather than unrelated unsaved values omitted from update_fields.

## Enforcement boundaries

QuerySet.update(), bulk_create(), bulk_update(), raw SQL and concurrent cross-record edits do not receive the same cross-table validation guarantees. Only the two buyer/seller CheckConstraints provide database enforcement here. Use validated instance writes for relationship changes. A future API should derive roles from the authenticated user and listing, validate inside its write operation, and add suitable concurrency control; no API or authentication workflow is introduced by this P1 change.

Do not interpret model validation as authorization of the logged-in user. Admin permissions remain Django's standard administrative permissions.

## Migration and verification

Follow-up migrations marketplace 0006 and messaging 0003 add the participant CheckConstraints. Existing uniqueness rules, transaction status/lifecycle, account deletion policy and message timestamp constraints are unchanged.

Before applying the migrations, inspect existing participant records; invalid records must not be silently reassigned or deleted. New migrations should be applied with manage.py migrate after backup.

Run python manage.py test. Regression coverage includes valid/invalid role combinations, hidden self-purchases with a fake seller, nonparticipant senders, database rejection of identical participants, partial writes, parent edits, Listing/BundleItem consistency, new conversations without a listing, historical SET_NULL preservation, and Admin validation.
