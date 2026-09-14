# Django frontend architecture

The browse page uses the reference Next.js frontend as a visual blueprint.
The running application is Django templates, authored CSS, and browser JavaScript
modules. It does not require Next.js, React, TypeScript, npm, or a frontend build.

## Responsibilities

- `marketplace/forms.py`: validate query parameters and supply choices from the database.
- `marketplace/browse.py`: active-listing queries, related-object loading, sorting, and removable filter links.
- `marketplace/views.py`: preserve the four course view styles with a shared context.
- `templates/marketplace/base.html`: document shell and stylesheet entry point.
- `templates/marketplace/partials/`: header, hero/carousel, filter form, results, listing cards.
- `static/css/marketplace.css`: CSS entry point importing theme, layout, and component styles.
- `static/js/marketplace.js`: initialization only.
- `static/js/marketplace/browse.js`: enhanced GET submissions, result replacement, history, dependent item types, grid/list mode.
- `static/js/marketplace/drawer.js`: native modal dialog, keyboard/focus behavior, and backdrop dismissal.
- `static/js/marketplace/carousel.js`: navigation and optional autoplay, respecting reduced motion, focus, hover, and hidden tabs.
- `static/js/marketplace/favorites.js`: browser-local saved IDs, count, saved-only view, and cross-tab synchronization.
- `marketplace/featured.py`: scene composition, listing image presentation, and Decimal savings calculations.
- `marketplace/scene_contours.py`: hand-traced SVG silhouettes in the square reference images' native coordinates, with separate price-label anchors.
- `static/js/marketplace/hotspots.js`: hover, focus, and tap listing previews with viewport-aware placement.
- `static/js/marketplace/header.js`: status dialogs for Sell Item, Messages, and Profile buttons.
- `static/css/marketplace/featured.css`: reference fonts, image highlights, summary boxes, and preview styling.
- `static/img/reference/`: scene and product images copied from the model frontend.

The existing marketplace, bundles, and messaging apps retain ownership of their
models and business rules. Migration 0006 removes the Either fulfillment choice
and converts existing Either listings to Pickup. Its data conversion is not
reversed on rollback, since original Pickup records cannot be distinguished.

## Request flow

Browser GET -> view -> validated BrowseForm -> active Listing queryset -> template.
With JavaScript enabled, fetch requests the same HTML and replaces only results
and validation messages. Django remains the authority for filtering and sorting.
Without JavaScript, the visible filter form and search submit normally.
The carousel remains horizontally scrollable; script-dependent buttons are hidden.

Supported filters: category, item type, price bounds, condition, bundle eligibility,
and fulfillment (Pickup or Delivery). Fulfillment is not shown on listing cards.
Popular sorting ranks by the count of buyer inquiry conversations, breaking ties
by newest creation date and then primary key. Favorites remain browser-local.
Selected filters have shareable URLs and removable chips. Invalid filters show
validation messages without widening the results.

## Python requirements compared with the reference

The reference has two additional dependencies:

| Package | Purpose | Needed here? |
| --- | --- | --- |
| Pillow==11.3.0 | ImageField validation and image processing | No. Current listings use image_url; reference illustrations are static files. Add when implementing image uploads or processing. |
| django-cors-headers==4.9.0 | Cross-origin browser access to Django | No. This design serves pages and requests from one origin. Add only for an intentionally separate frontend origin. |

All other pins match. requirements.txt is deliberately unchanged.
The old Tailwind package.json, input.css, and generated app.css are retained
for reference; the new page does not load them. TypeScript is optional if browser
logic grows; its source would belong in frontend/src and compiled output in static/js.
Do not maintain duplicate handwritten JavaScript and TypeScript implementations.

## Scope and extension points

- Favorites persist in this browser, not a user account. Storage failures fall back to in-memory selections.
- Run `python manage.py seed_featured_bundles` after migrations to add six demo
  listings (three per scene). The command is idempotent and preserves edited prices.
  Scene composition is editorial configuration, while item prices and availability
  come from the database. Bundle price is the sum of the three listing prices;
  You save is their combined retail price minus the bundle price, floored at zero;
  Overall discount uses the combined retail price as its denominator.
  A missing retail price suppresses the savings calculation. An unavailable or
  non-eligible item suppresses that scene rather than advertising an incomplete bundle.
  Hover/tap previews link to the corresponding listing in the browse page.
- The hero copies the reference's three steps. A complete builder, negotiated
  discounts, checkout, seller forms, account screens, and messaging screens remain
  separate feature work. Sell Item, Messages, and Profile currently open explicit
  coming-next dialogs; the shopping bag toggles the saved-items view.
- Fonts use Inter and Cormorant Garamond, loaded from Google Fonts with local
  fallback families if the network is unavailable. Featured-image prices and the
  bundle total use Inter; listing prices retain Cormorant Garamond.
- Space and distance filters are omitted because the current Listing model does not
  contain the necessary room/location data. No distances are invented.
- Price bounds use two accessible native number inputs rather than a custom dual-thumb slider.
- Existing listing photos are used as provided; missing photos have an explicit placeholder.
- Results currently render all matches. Add server pagination before scaling to a large catalog.
- Validate permissions and CSRF-protect writes when adding account-backed favorites,
  listing creation, messaging, or bundle submissions.

## Verification

Run `python manage.py test` and `python manage.py check` from the project directory
with the project's environment activated and a local SECRET_KEY configured.
`marketplace/test_browse.py` covers all four view styles, active-only visibility,
combined filters, fulfillment semantics, invalid inputs, escaping, removable
filters, free listings, and bounded database queries.

Browser checks: desktop/mobile layouts, opening and dismissing filters (including
Escape), search and sort, back/forward navigation, favorites, carousel pause,
and the no-JavaScript form flow.

Validation performed: 46 Django tests passed, including existing integrity tests
and an idempotent demo-seed test. Django system checks and JavaScript syntax
checks passed. Browser review covered desktop and 390px mobile layouts, live
search, combined category filters, Escape dismissal, local favorites, grid/list
switching, and back navigation. Native GET behavior is covered by Django tests;
a browser run with JavaScript disabled was not performed.

The demo seed command now uses Decimal arithmetic for money so strict model
validation accepts benchmark and minimum prices without float precision errors.

`marketplace/test_featured.py` covers discount edge cases, bundle totals, edited
prices, unavailable items, idempotent seeding, and inquiry-based Popular ordering.

Featured-scene browser verification: desktop and 390px mobile preview placement,
keyboard Tab into the listing link, Escape dismissal, original/discounted prices,
three outlined items per scene, Pickup/Delivery-only filters, and the Sell Item
status dialog. Preview windows prefer an adjacent position so opening on hover
does not put a clickable link underneath the pointer.

Item outlines use SVG silhouettes rather than rectangular borders. Even-odd
subpaths preserve the openings between furniture legs; pointer targets follow
the painted shapes and their price labels. Native buttons retain keyboard
access, with focus emphasized on the SVG stroke. The contours and images share
one coordinate system so they stay aligned across desktop and mobile sizes.
The silhouettes use thin round-dotted strokes, including their hover/focus states.
Price labels share a higher stacking layer than all image contours and overlays;
hotspot wrappers do not isolate labels in separate stacking contexts.
