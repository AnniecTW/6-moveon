# Week 3: Listing and Message seller

## This week

MoveOn now lets verified sellers create, preview, and publish listings from the site. Buyers can open an active listing and start a private conversation with its seller.

## Create a listing

- Sign in with an active, verified `@illinois.edu` account and choose **Sell Item** in the top navigation.
- Add up to 8 photos. Upload JPG, PNG, or WebP files up to 5 MB each, or paste an HTTP/HTTPS photo URL.
- Enter a title (required, up to 80 characters), price (required, up to 6 whole-number digits and 2 decimal places), condition, and category.
- Choose Pickup, Delivery, or both. At least one option is required.
- Description (up to 1,000 characters), minimum price, move-out date, bundle participation, and **Sell no matter what** are optional.
- The price fields show a `$0` minimum and accept cents. The minimum price is private and is not shown to buyers.
- Choose **Save Draft** to save and return to the home page, or **Preview Listing** to view the draft.
- From preview, choose **Back to edit** or **Publish**. Publishing opens the active listing's detail page.

## Listing detail

- An active listing page shows its cover photo (or a no-photo placeholder), title, category, asking price, condition, and pickup/delivery options.
- It also shows the seller's display name, description, and move-out date when one is set.
- Retail and benchmark prices appear only when those values exist. Bundle eligibility and similar items also appear when available.
- Minimum price is not shown. Only active listings have a public detail page.
- The **Message Seller** button appears for everyone except the listing owner. The owner does not see it; a direct link to their own listing opens Messages but cannot start a conversation.
- Guests and signed-in users without campus access can still view the listing and see the button, but cannot enter Messages until they have campus access.

## Message seller

- As a verified buyer, choose **Message Seller**. The address changes to `/messages/?listing=<id>` and the matching conversation opens.
- The first visit starts a conversation. Returning as the same buyer to that listing opens the existing conversation instead of creating another one.
- Send text or attach up to 3 JPEG, PNG, WebP, or GIF images, up to 10 MB each.
- The seller sees the conversation in the Messages list and the unread count in the header. Open the conversation to read and reply.
- As a guest, choosing **Message Seller** opens the account screen. After creating an account, verifying the campus email, and signing in, MoveOn returns to the listing conversation.
- A signed-in but unverified account is sent to the campus-access screen. It must sign out, verify through login, and gain campus access before using Messages.
- If a listing becomes unavailable, an existing conversation remains in Messages with its history. A conversation that already has messages remains usable; an empty one shows the unavailable notice.
- An unavailable listing with no existing conversation cannot start a new one. The request shows an unavailable notice and creates no conversation.

## Try it

Use the setup instructions in the [README](../../../README.md).
Sign in as B and publish an active listing, then sign in as A in another browser.
Open B's detail page, choose **Message Seller**, send a message, and confirm B sees the unread count and can reply.
The README also covers the guest sign-in return flow.

## Current limits

- A listing can hold up to 8 photos, but its detail page currently displays only the cover photo; the other thumbnail slots are placeholders.
- A pasted photo URL is checked for URL format and HTTP/HTTPS only; MoveOn does not confirm that it points to a working image.
- The price field shows a `$0` minimum, but the server does not explicitly reject a negative price.
- The detail page's **Share** buttons do not perform an action yet.