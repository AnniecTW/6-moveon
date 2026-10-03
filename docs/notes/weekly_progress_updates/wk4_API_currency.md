# Week 4: Keyless API Integration

Added a public, read-only JSON endpoint at `/api/listings/converted/`. It accepts a currency and the existing browse filters, reads matching active listings from the database, and fetches a USD exchange rate from Frankfurter without an API key.

The endpoint converts listing and retail prices with `Decimal`, rounds them to two decimal places, and returns the converted prices with the rate and its date. It uses a five-second timeout, checks the upstream HTTP status, and returns clear errors if the service fails. Exchange rates and converted prices are not stored.

Added a currency selector to the homepage listing toolbar. Changing it updates the visible prices while preserving the current search and filters. Price range filters remain in USD and are labeled accordingly.

Added endpoint tests for successful conversion, invalid currencies, and timeouts.
