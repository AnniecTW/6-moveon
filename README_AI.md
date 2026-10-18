## 1. Local LLM: Natural-Language Listing Search

### Data Input

The shared search bar is available on the home page (`/`) and `/listings/`. It sends the search text as `q` and the selected mode as `search_mode=keyword` or `search_mode=ai`. Keyword search is the default when the mode is missing or invalid.

### Keyword Search

Keyword search keeps the existing browse behavior. It does not load the local model.

### AI Search

AI search does not use the full query as a keyword filter. Django retrieves active listings from the `Listing` ORM and applies the selected non-text filters. To limit the prompt size, it **selects up to 40 listings** that match at least one meaningful query term in their title, description, item type, or category, then fills any remaining slots with the most recent eligible listings. These recent listings are only candidates for the model to evaluate.

The model can return zero to five listing IDs. It does not extract exact price or category filters from the query; users can set those in the existing filter controls.

### Preprocessing

Django sends the trimmed query and each candidate’s ID, title, combined category/item-type label, price, condition, and description. It collapses whitespace, limits field lengths, and serializes the catalog as compact JSON. The existing browse form limits the query to 200 characters. Seller details, contact information, images, and unrelated fields are not sent to the model.

### Output Handling

Django keeps unique IDs from the candidate set, rechecks active status and selected filters, and preserves the model’s ranking order. A lexical relevance gate checks listing text against the query using maintained synonym groups rather than embeddings, so it may exclude relevant listings with unfamiliar wording.

If no valid, relevant IDs remain, the page shows a message and up to five random active listings matching the selected filters. These are fallback listings, not AI recommendations, and may not match the query. If candidate retrieval, result lookup, or model loading/inference fails, the app logs the error and may show similar fallback listings with a separate message that AI search could not be completed. If the fallback lookup fails or returns no listings, the page shows an error and no results; it does not silently switch to keyword search.

### Safety Guardrails

The query is limited to 200 characters, and listing fields are cleaned and length-limited before inference. The prompt treats the query and listing text as untrusted data, and the model receives only the fields needed for ranking. Search controls are disabled while an AI request is running.

### Setup

Install dependencies with `pip install -r requirements.txt`, set your own `HF_TOKEN` in the local environment or `.env`, and start Django with `python manage.py runserver`. Before downloading the gated model, accept its license and confirm that your Hugging Face account has access to `meta-llama/Llama-3.2-3B-Instruct`. The first AI search downloads the tokenizer and model weights to the Hugging Face cache, so allow several gigabytes of disk space and enough RAM or accelerator memory. Keep tokens and other secrets out of source control, and do not commit model weights.

## 2. External API: AI Bundle Builder

### Data Input

Buyers choose a home space and available item types from predefined options; they do not enter a free-form prompt. The service uses those selections to find eligible listings, which the builder displays in Budget, Best Value, and Premium tiers.

### Preprocessing

Candidates are grouped by item type and must be active, bundle-eligible, and not owned by the buyer. The request includes the selected space, item type IDs and names, listing IDs, titles, prices, conditions, and descriptions, along with available move-out and pricing context. Buyer and seller identity fields are omitted.

### External API Request

`bundles.services` calls Google’s Gemini API using the model ID `gemini-3.6-flash`. The prompt asks Gemini to select candidate listings for the `BUDGET`, `BEST_VALUE`, and `PREMIUM` tiers and provide a short rationale. The request asks for JSON, uses a 10-second timeout, and disables SDK retries.

### Response Handling

The service parses the JSON and accepts only IDs that belong to the submitted item type’s candidate set. Each tier must contain at least one valid item. The validator does not require exact keys or every item type in every tier, and it does not enforce the prompt’s rationale word limit. Rationales are limited to 280 characters.

The builder uses accepted IDs to display the selected tier and calculate its total price. Buyers can switch tiers or swap in another eligible listing.

### Safety Guardrails and Error Handling

Space and item type selections are checked against configured options, and bundle routes require an authenticated campus-access-eligible user. Candidate retrieval excludes inactive, ineligible, and buyer-owned listings.

If the API key is missing, Gemini is skipped. API errors or unusable responses are logged and handled with a price-based heuristic. The builder labels those results `Price-based pick — AI suggestions unavailable right now`. If none of the selected item types has eligible listings, the UI returns to category selection with an explanatory message. A failed browser request displays `Something went wrong generating your bundle` and a link to try again.

### Configuration / API Key Setup

Set `GEMINI_API_KEY` in the project-root `.env` file or deployment environment. The variable is listed in `.env.example`. Keep the key private and out of source control. If it is unset, the app skips Gemini and uses the price-based heuristic.
