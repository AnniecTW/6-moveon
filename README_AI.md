# AI System Design Documentation

## Contents

- [S2.1: AI Workflow Write-Up](#s21-ai-workflow-write-up) · [Listing search](#natural-language-listing-search) · [Bundling](#ai-bundle-builder) · [Pricing suggestions](#pricing-suggestions) · [Photo autofill](#listing-photo-autofill)
- [Guardrails and Error Handling](#guardrails-and-error-handling) · [Search](#search-guardrails) · [Bundling](#bundling-guardrails) · [Pricing](#pricing-guardrails) · [Photo autofill](#photo-autofill-guardrails)
- [S2.2: Architecture Explanation](#s22-architecture-explanation) · [Listing search diagram](#natural-language-listing-search-diagram) · [Bundling diagram](#ai-bundle-builder-diagram)
- [S2.3: Model Selection Rationale](#s23-model-selection-rationale) · [Setup](#setup)

## S2.1: AI Workflow Write-Up

Natural-language listing search and the AI Bundle Builder address two main buyer needs in MoveOn. Search helps buyers find listings that match a request, while the Bundle Builder helps them furnish a space and compare sets of items. A locally hosted Llama model powers the primary AI search. Gemini provides optional bundle recommendations alongside a price-based fallback. [Search workflow][search-entry] · [Bundle generation][bundle-generation]

### AI Feature Explanation

#### Natural-Language Listing Search

1. **User input.** Buyers enter a request on the home page or `/listings/` and choose AI mode. The browser sends the query as `q`, sets `search_mode=ai`, and includes the selected filters for price, category, condition, and fulfillment. Buyers use these controls to specify exact constraints such as a maximum price. [Search mode][search-entry] · [Filter form][browse-form]
2. **Input preprocessing.** Django starts with active listings that meet the selected filters. It prioritizes listings whose titles, descriptions, categories, or item types match query terms and fills any remaining slots with recent eligible listings. The candidate pool contains at most 40 listings. The application normalizes whitespace and serializes the query and candidate IDs, titles, category or type labels, prices, conditions, and descriptions as JSON. The payload omits separate seller identity and contact fields. [Candidate selection][search-candidates] · [Model payload][search-payload]
3. **Model.** The local `meta-llama/Llama-3.2-3B-Instruct` model ranks candidates against the buyer's request. Django prepares the input using the Transformers chat template. [Model configuration][ai-settings] · [Local inference][search-generation]
4. **Output generation.** The prompt asks the model to return up to five candidate IDs in a JSON `ids` array ordered by relevance. The array may be empty when there is no suitable match. Django applies the [search validation checks](#search-guardrails) and queries the database for the remaining listings. [Output prompt][search-prompt] · [Final listing query][search-result-query]
5. **User response.** Django preserves the model's relative ordering and renders the listings as cards on the home or browse page. [Search Guardrails](#search-guardrails) explains the empty-result and fallback states. [Result ordering][search-result-query] · [Listing card template][search-result-cards]

#### AI Bundle Builder

1. **User input.** Buyers choose a space and item types in the bundle wizard, such as a bed frame and a desk for a bedroom. The wizard provides the available spaces and item types. [Wizard selections][bundle-wizard]
2. **Input preprocessing.** Django groups active, bundle-eligible listings from other sellers by the selected item types. Each candidate includes its ID, title, price, condition, and description. The application also includes available context such as days until move-out, average completed-sale prices, and benchmark price ranges. [Eligible candidates][bundle-candidates] · [Candidate fields][bundle-payload]
3. **Model.** With `GEMINI_API_KEY` configured, the application uses `gemini-3.6-flash`. The prompt asks Gemini to pick listings for Budget, Best Value, and Premium tiers and provide a short rationale for each tier. [Tier prompt][bundle-prompt] · [Gemini request][bundle-request]
4. **Output generation.** Gemini returns JSON containing the selected listing IDs and rationale for each tier. Django [validates the choices](#bundling-guardrails) and stores the tier suggestions in the session. It computes the bundle total by adding the listing prices of the selected items. [Tier validation][bundle-validation] · [Session cache][bundle-cache] · [Total calculation][bundle-total]
5. **User response.** The bundle page displays the items, total, and available rationale for the selected tier. Buyers can switch tiers or swap items. Django persists the current selection as `BundleItem` records. [Bundle page][bundle-display] · [Selected-item persistence][bundle-items]

#### Pricing Suggestions

1. **User input.** Sellers enter a listing title and can also provide a category, item type, condition, or brand.
2. **Input preprocessing.** The application builds candidate type descriptions from type and category names and representative titles with historical price records. [Type descriptions][pricing-semantic]
3. **Model.** The local `sentence-transformers/all-MiniLM-L6-v2` encoder embeds the seller's query and the type descriptions, then ranks candidate item types by similarity. [Semantic type matching][pricing-semantic]
4. **Output generation.** Pricing rules compute a reference price from historical observations for the matched type, condition, and brand where supported. A seller who has selected a type can also request its price guide directly. [Historical price calculation][pricing-calc] · [Selected-type price endpoint][pricing-preview]
5. **User response.** The seller form displays suggested types and available price guides. Sellers can accept, edit, or decline a price recommendation. [Pricing Guardrails](#pricing-guardrails) covers limited evidence and minimum-price protection. [Type suggestion cards][pricing-form-ui] · [Seller decision and save][pricing-save]

#### Listing Photo Autofill

1. **User input.** Sellers upload listing photos. Analysis starts after the upload completes, and the **Fill details from photos** button can also start it. [Analysis triggers][photo-trigger]
2. **Input preprocessing.** The browser submits the first three photo IDs, or all available IDs if there are fewer than three. The service resizes each image to fit within 1024 by 1024 pixels, converts them to RGB, and prepares the allowed item types and conditions. [Photo selection][photo-selection] · [Image preparation][photo-preparation]
3. **Model.** The application uses `gemini-3.5-flash-lite` to suggest listing details from the images and allowed field values. [Photo model configuration][photo-model]
4. **Output generation.** The model returns structured JSON with suggestions for the title, description, item type ID, and condition. [Field prompt and options][photo-prompt]
5. **User response.** The browser inserts usable suggestions into the editable form. Sellers can review the values and submit the form normally. [Photo Autofill Guardrails](#photo-autofill-guardrails) explains how the browser handles changed photos and existing field values. [Browser autofill][photo-fill]

## Guardrails and Error Handling

### Search Guardrails

- **Input and candidate limits.** `BrowseForm` limits the query to 200 characters. An empty query skips model inference and shows the normal browse results. A missing or invalid search mode defaults to keyword search. An AI query with an empty initial candidate pool shows an empty result without running inference. [Query validation][browse-form] · [Search mode and empty input][search-entry]
- **Model input and generation limits.** The model payload limits titles and category labels to 200 characters each, condition values to 50 characters, and descriptions to 1,000 characters. Generation is limited to 128 new tokens. Timing starts after model loading and tokenization. The application passes `max_time=30` and checks elapsed generation time when the model call returns. [Field limits][search-payload] · [Generation timing][search-generation]
- **Result validation.** Django parses the `ids` array, discards noninteger, duplicate, and noncandidate IDs, and keeps at most five. Malformed JSON, an invalid response structure, or a nonempty array containing no valid IDs enters the corresponding error path. Valid IDs pass through a lexical relevance check based on query terms and synonym groups. Django then rechecks that the listings remain active and satisfy the selected filters. [ID parsing][search-parse] · [Lexical relevance check][search-relevance] · [Database recheck][search-result-query]
- **No results and fallback.** If the model call fails, the ranking is unusable, or a candidate or result query fails, Django attempts to display up to five randomly selected listings that meet the filters. The page labels these as fallback results. If the fallback query fails or returns no listings, the page displays the corresponding message. [Fallback query and messages][search-fallback] · [Fallback notice][search-fallback-ui]

### Bundling Guardrails

- **Result validation.** Each accepted listing ID must belong to the candidate set for the corresponding item type. Every tier needs at least one usable item. If some types have no eligible listings, the page reports that categories were skipped. If none of the selected types has an eligible listing, the wizard asks the buyer to adjust the selection. [Tier ID validation][bundle-validation] · [Empty candidate handling][bundle-empty]
- **Request limits and fallback.** The Gemini request has a 10-second timeout and SDK retries are disabled. When the key is missing, the call fails, or the response fails validation, the application builds tiers from the lowest-priced, middle-ranked, and highest-priced listings in each item type. The page labels the recommendation source. Changing tiers loads the IDs saved in the session, and a manual swap checks the eligibility of the replacement listing. [Request settings][bundle-request] · [Price-based fallback][bundle-fallback] · [Swap validation][bundle-swap]

### Pricing Guardrails

- **Match and evidence limits.** The type suggestion endpoint reads the first 80 characters of the title and asks for more text if fewer than three characters remain. It returns up to five types that meet the 0.40 similarity threshold. The price guide uses historical price observations from 2023 outside the local market. Sparse groups receive an evidence warning. The application omits the corresponding estimate when it lacks supporting data. [Title validation][pricing-type-view] · [Similarity cutoff][pricing-similarity] · [Pricing evidence][pricing-calc]
- **Saving and fallback.** On submission, Django recalculates the reference price and records the seller's decision. It checks the seller's minimum price before applying an accepted recommendation. If semantic encoding fails, the interface prompts the seller to choose the item type manually. [Minimum price and save][pricing-save] · [Encoder error handling][pricing-type-view]

### Photo Autofill Guardrails

- **Upload and analysis checks.** The upload endpoint rejects empty, oversized, unreadable, or unsupported images, with a limit of 5 MiB per file. The analysis endpoint requires a signed-in user, validates ownership and the submitted IDs, and accepts one to three uploaded photos. A seller with a URL-only photo can upload the image or enter the details manually. A cache-based limit allows five analyses per user in a 600-second window. [Upload validation][photo-upload] · [Analysis checks and rate limit][photo-analysis]
- **Request limits and field validation.** Each Gemini attempt has a 15-second timeout and a 512-token output limit. The application retries once on `ServiceUnavailable`. For recognizable items, the service trims titles and descriptions and clears invalid item type or condition values. Sellers can enter the details manually if analysis fails or produces no usable suggestions. [Request and retry][photo-request] · [Field validation][photo-validate]
- **Autofill and changed photos.** After a successful response, the browser compares the complete current photo ID sequence with the sequence captured before the request. A change in length or in any ID position skips autofill and prompts the seller to analyze the photos again. Uploading, removing, or reordering photos updates the ID list immediately. The browser fills empty fields by default. If all four target fields already contain values, it asks for confirmation before replacing them. [Photo comparison][photo-change] · [Photo ID updates][photo-ids] · [Field updates][photo-fill]

## S2.2: Architecture Explanation

### Natural-Language Listing Search Diagram

**AI model** `meta-llama/Llama-3.2-3B-Instruct`

```mermaid
flowchart LR
    U["Enter query and select filters"] --> F["Django validates input and search mode"]
    F -->|"Keyword mode or empty query"| K["Browse or use ORM keyword search"]
    F -->|"Invalid input"| I["Show form errors"]
    F -->|"Valid nonempty AI query"| C["Retrieve up to 40 eligible listings"]
    C -->|"No candidates"| E["Show empty results without inference"]
    C -->|"Query failed"| B["Query up to five random eligible listings"]
    C -->|"Candidates found"| P["Normalize fields and build JSON prompt"]
    P --> M["Local Llama generates ranked listing IDs"]
    M -->|"Load or generation failed"| B
    M --> V["Parse JSON, filter IDs, and check lexical relevance"]
    V -->|"Invalid response or no relevant IDs"| B
    V -->|"Valid IDs"| D["Recheck listing status and selected filters"]
    D -->|"Results remain in rank order"| R["Render listing cards"]
    D -->|"No results or query failed"| B
    B -->|"Fallback listings found"| L["Display labeled fallback results"]
    B -->|"No fallback listings or query failed"| X["Show the empty or error state"]
    K --> R
```

[Search Guardrails](#search-guardrails) describes the query limits, result checks, and random-listing fallback. [Search request handling][search-entry] · [Model ranking][search-rank]

### AI Bundle Builder Diagram

**AI model** `gemini-3.6-flash`

```mermaid
flowchart LR
    buyer["Choose a space and item types"] --> candidates["Django filters eligible listings by type"]
    candidates -->|"Candidates and API key available"| gemini["Gemini suggests bundle tiers"]
    candidates -->|"Candidates available without a key"| pricingRules["Django builds tiers by price"]
    candidates -->|"No eligible candidates"| selectAgain["Ask buyer to adjust item types"]
    gemini -->|"Response passes validation"| bundlePage["Display tiers and selected bundle total"]
    gemini -->|"Request or validation fails"| pricingRules
    pricingRules --> bundlePage
```

[Bundling Guardrails](#bundling-guardrails) describes tier validation, the request timeout, and the price-based fallback. [Generation and fallback][bundle-generation]

## S2.3: Model Selection Rationale

### Natural-Language Listing Search

MoveOn uses `meta-llama/Llama-3.2-3B-Instruct` for local natural-language listing search. A6 evaluated a 40-listing catalog with eight labeled queries and prioritized strict output structure, usable nDCG@5, and median generation time in that order. The zero-shot Llama configuration produced valid structured responses on all eight queries, reached 0.483 usable nDCG@5, and had a median generation time of 3.33 seconds. `Qwen/Qwen3-1.7B` also met the structure requirement on all eight queries with eight prompt examples, reaching 0.458 usable nDCG@5 and a 5.24-second median. The one-shot `microsoft/Phi-4-mini-instruct` configuration met the requirement on six queries, with 0.433 usable nDCG@5 and a 6.26-second median. A7 provides a separate text-extraction comparison in which Qwen3 4B, Phi-4 mini, and Llama scored 7.68, 7.35, and 6.41 respectively. The team set the scoring criteria and used AI-assisted scoring with targeted review. The A6 comparison directly measures ranking a set of listings, which is the task the application needs. Llama runs locally and returns ranked IDs that Django can validate and render as listing cards. [A6 selection criteria][a6-findings] · [A6 n-shot results][a6-summary] · [A7 extraction results][a7-extraction] · [A7 scoring method][a7-scoring]

### AI Bundle Builder

MoveOn uses `gemini-3.6-flash`, a hosted multimodal model available through the Gemini Developer API free tier, to recommend bundle tiers from the candidate listings' prices, conditions, descriptions, and available move-out context. Its text input and structured output capabilities fit the wizard's need for candidate IDs and short rationales. The A7 purchase-advice results for Qwen3 4B and Mistral-Nemo provide reference points for local text models. The application also implements price-based tier generation as an alternative. The Best Value prompt asks Gemini to weigh price against condition and explain its selection. Django can then validate the IDs, calculate the total using listing prices, and show the tier choices in the buyer's wizard. [Gemini Developer API pricing](https://ai.google.dev/gemini-api/docs/pricing) · [Bundle prompt][bundle-prompt] · [A7 purchase-advice comparison][a7-purchase] · [Gemini 3.6 Flash specifications](https://ai.google.dev/gemini-api/docs/models/gemini-3.6-flash) · [Bundling design notes](https://github.com/AnniecTW/6-moveon/blob/970ceddefd34c18aaefcf361dafa46f807e2ba0d/docs/notes/weekly_progress_updates/wk3_note_srinath.md#L39)

### Pricing Suggestions

MoveOn uses the local `sentence-transformers/all-MiniLM-L6-v2` encoder to match seller titles to item types supported by historical records. The lexical candidate selection used for the A6 search workflow provides a matching baseline. Embeddings let the pricing workflow compare seller wording with the descriptions in the type catalog. Since that catalog is relatively stable, Django can cache its embeddings and encode only the new seller input on repeat queries. This fits the listing form because sellers can confirm the proposed type before the application computes a traceable price guide from the type, condition, and historical observations. The implementation tests exercised semantic matching with a controlled encoder and checked the form's pricing path. [Type matching][pricing-semantic] · [Pricing implementation notes][pricing-notes]

### Listing Photo Autofill

MoveOn uses `gemini-3.5-flash-lite`, a hosted multimodal model available through the Gemini Developer API free tier, to suggest a title, description, item type, and condition from listing photos and the allowed form options. Qwen3 4B and Phi-4 mini provide A7 reference points for structured extraction from text. Photo autofill adds visual input to that task. Gemini's multimodal design allows the service to send images with the field options and request structured output in the same call. Google positions Flash-Lite for low-latency, high-throughput processing, which fits the short fields needed by the listing form. The feature shares the Gemini SDK and API key with Bundling. Django validates the proposed values and the seller can edit them before submitting the listing. [Gemini Developer API pricing](https://ai.google.dev/gemini-api/docs/pricing) · [Photo model request][photo-request] · [A7 text extraction results][a7-extraction] · [Gemini multimodal design](https://blog.google/innovation-and-ai/technology/ai/google-gemini-ai/) · [Flash-Lite model specifications](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/gemini/3-5-flash-lite) · [Flash-Lite release notes](https://blog.google/innovation-and-ai/models-and-research/gemini-models/gemini-3-6-flash-3-5-flash-lite-3-5-flash-cyber/)

### Setup

The project README explains environment setup, server startup, and model downloads. [AI feature setup][ai-setup]

Local search uses `LOCAL_LLM_MODEL_ID` and `HF_TOKEN`. Bundling and photo autofill share `GEMINI_API_KEY`. [AI settings][ai-settings]

[search-entry]: https://github.com/AnniecTW/6-moveon/blob/523e484f4e4af3a09bc7cafaa5c9c2cdacb5dbda/marketplace/browse.py#L149
[bundle-generation]: https://github.com/AnniecTW/6-moveon/blob/523e484f4e4af3a09bc7cafaa5c9c2cdacb5dbda/bundles/services.py#L31
[browse-form]: https://github.com/AnniecTW/6-moveon/blob/523e484f4e4af3a09bc7cafaa5c9c2cdacb5dbda/marketplace/forms.py#L48
[search-candidates]: https://github.com/AnniecTW/6-moveon/blob/523e484f4e4af3a09bc7cafaa5c9c2cdacb5dbda/marketplace/browse.py#L85
[search-payload]: https://github.com/AnniecTW/6-moveon/blob/523e484f4e4af3a09bc7cafaa5c9c2cdacb5dbda/marketplace/local_llm.py#L86
[ai-settings]: https://github.com/AnniecTW/6-moveon/blob/523e484f4e4af3a09bc7cafaa5c9c2cdacb5dbda/moveon/settings/base.py#L34
[search-generation]: https://github.com/AnniecTW/6-moveon/blob/523e484f4e4af3a09bc7cafaa5c9c2cdacb5dbda/marketplace/local_llm.py#L222
[search-prompt]: https://github.com/AnniecTW/6-moveon/blob/523e484f4e4af3a09bc7cafaa5c9c2cdacb5dbda/marketplace/local_llm.py#L145
[search-result-query]: https://github.com/AnniecTW/6-moveon/blob/523e484f4e4af3a09bc7cafaa5c9c2cdacb5dbda/marketplace/browse.py#L191
[search-result-cards]: https://github.com/AnniecTW/6-moveon/blob/523e484f4e4af3a09bc7cafaa5c9c2cdacb5dbda/templates/marketplace/partials/_results.html#L22
[bundle-wizard]: https://github.com/AnniecTW/6-moveon/blob/523e484f4e4af3a09bc7cafaa5c9c2cdacb5dbda/bundles/views.py#L145
[bundle-candidates]: https://github.com/AnniecTW/6-moveon/blob/523e484f4e4af3a09bc7cafaa5c9c2cdacb5dbda/bundles/services.py#L86
[bundle-payload]: https://github.com/AnniecTW/6-moveon/blob/523e484f4e4af3a09bc7cafaa5c9c2cdacb5dbda/bundles/services.py#L118
[bundle-prompt]: https://github.com/AnniecTW/6-moveon/blob/523e484f4e4af3a09bc7cafaa5c9c2cdacb5dbda/bundles/services.py#L144
[bundle-request]: https://github.com/AnniecTW/6-moveon/blob/523e484f4e4af3a09bc7cafaa5c9c2cdacb5dbda/bundles/services.py#L201
[bundle-validation]: https://github.com/AnniecTW/6-moveon/blob/523e484f4e4af3a09bc7cafaa5c9c2cdacb5dbda/bundles/services.py#L220
[bundle-cache]: https://github.com/AnniecTW/6-moveon/blob/523e484f4e4af3a09bc7cafaa5c9c2cdacb5dbda/bundles/views.py#L22
[bundle-total]: https://github.com/AnniecTW/6-moveon/blob/523e484f4e4af3a09bc7cafaa5c9c2cdacb5dbda/bundles/views.py#L381
[bundle-display]: https://github.com/AnniecTW/6-moveon/blob/523e484f4e4af3a09bc7cafaa5c9c2cdacb5dbda/templates/bundles/builder.html#L26
[bundle-items]: https://github.com/AnniecTW/6-moveon/blob/523e484f4e4af3a09bc7cafaa5c9c2cdacb5dbda/bundles/views.py#L300
[pricing-semantic]: https://github.com/AnniecTW/6-moveon/blob/523e484f4e4af3a09bc7cafaa5c9c2cdacb5dbda/marketplace/pricing/semantic.py#L48
[pricing-calc]: https://github.com/AnniecTW/6-moveon/blob/523e484f4e4af3a09bc7cafaa5c9c2cdacb5dbda/marketplace/pricing/initial.py#L105
[pricing-preview]: https://github.com/AnniecTW/6-moveon/blob/523e484f4e4af3a09bc7cafaa5c9c2cdacb5dbda/marketplace/views.py#L361
[pricing-form-ui]: https://github.com/AnniecTW/6-moveon/blob/523e484f4e4af3a09bc7cafaa5c9c2cdacb5dbda/templates/marketplace/listing_form.html#L123
[pricing-save]: https://github.com/AnniecTW/6-moveon/blob/523e484f4e4af3a09bc7cafaa5c9c2cdacb5dbda/marketplace/forms.py#L251
[photo-trigger]: https://github.com/AnniecTW/6-moveon/blob/523e484f4e4af3a09bc7cafaa5c9c2cdacb5dbda/templates/marketplace/listing_form.html#L324
[photo-selection]: https://github.com/AnniecTW/6-moveon/blob/523e484f4e4af3a09bc7cafaa5c9c2cdacb5dbda/templates/marketplace/listing_form.html#L255
[photo-preparation]: https://github.com/AnniecTW/6-moveon/blob/523e484f4e4af3a09bc7cafaa5c9c2cdacb5dbda/marketplace/image_analysis.py#L27
[photo-model]: https://github.com/AnniecTW/6-moveon/blob/523e484f4e4af3a09bc7cafaa5c9c2cdacb5dbda/marketplace/image_analysis.py#L15
[photo-prompt]: https://github.com/AnniecTW/6-moveon/blob/523e484f4e4af3a09bc7cafaa5c9c2cdacb5dbda/marketplace/image_analysis.py#L60
[photo-fill]: https://github.com/AnniecTW/6-moveon/blob/523e484f4e4af3a09bc7cafaa5c9c2cdacb5dbda/templates/marketplace/listing_form.html#L292
[search-parse]: https://github.com/AnniecTW/6-moveon/blob/523e484f4e4af3a09bc7cafaa5c9c2cdacb5dbda/marketplace/local_llm.py#L57
[search-relevance]: https://github.com/AnniecTW/6-moveon/blob/523e484f4e4af3a09bc7cafaa5c9c2cdacb5dbda/marketplace/local_llm.py#L124
[search-fallback]: https://github.com/AnniecTW/6-moveon/blob/523e484f4e4af3a09bc7cafaa5c9c2cdacb5dbda/marketplace/browse.py#L223
[search-fallback-ui]: https://github.com/AnniecTW/6-moveon/blob/523e484f4e4af3a09bc7cafaa5c9c2cdacb5dbda/templates/marketplace/partials/_results.html#L3
[bundle-empty]: https://github.com/AnniecTW/6-moveon/blob/523e484f4e4af3a09bc7cafaa5c9c2cdacb5dbda/bundles/views.py#L207
[bundle-fallback]: https://github.com/AnniecTW/6-moveon/blob/523e484f4e4af3a09bc7cafaa5c9c2cdacb5dbda/bundles/services.py#L259
[bundle-swap]: https://github.com/AnniecTW/6-moveon/blob/523e484f4e4af3a09bc7cafaa5c9c2cdacb5dbda/bundles/views.py#L319
[pricing-type-view]: https://github.com/AnniecTW/6-moveon/blob/523e484f4e4af3a09bc7cafaa5c9c2cdacb5dbda/marketplace/views.py#L382
[pricing-similarity]: https://github.com/AnniecTW/6-moveon/blob/523e484f4e4af3a09bc7cafaa5c9c2cdacb5dbda/marketplace/pricing/semantic.py#L74
[photo-upload]: https://github.com/AnniecTW/6-moveon/blob/523e484f4e4af3a09bc7cafaa5c9c2cdacb5dbda/marketplace/views.py#L524
[photo-analysis]: https://github.com/AnniecTW/6-moveon/blob/523e484f4e4af3a09bc7cafaa5c9c2cdacb5dbda/marketplace/views.py#L605
[photo-request]: https://github.com/AnniecTW/6-moveon/blob/523e484f4e4af3a09bc7cafaa5c9c2cdacb5dbda/marketplace/image_analysis.py#L80
[photo-validate]: https://github.com/AnniecTW/6-moveon/blob/523e484f4e4af3a09bc7cafaa5c9c2cdacb5dbda/marketplace/image_analysis.py#L98
[photo-change]: https://github.com/AnniecTW/6-moveon/blob/523e484f4e4af3a09bc7cafaa5c9c2cdacb5dbda/templates/marketplace/listing_form.html#L287
[photo-ids]: https://github.com/AnniecTW/6-moveon/blob/523e484f4e4af3a09bc7cafaa5c9c2cdacb5dbda/static/marketplace/listing_photos.js#L51
[search-rank]: https://github.com/AnniecTW/6-moveon/blob/523e484f4e4af3a09bc7cafaa5c9c2cdacb5dbda/marketplace/local_llm.py#L249
[a6-findings]: https://github.com/AnniecTW/6-moveon/blob/523e484f4e4af3a09bc7cafaa5c9c2cdacb5dbda/llm-test/Part-1.2_Study-results_N-shot-prompt-engineering/findings.txt#L3
[a6-summary]: https://github.com/AnniecTW/6-moveon/blob/523e484f4e4af3a09bc7cafaa5c9c2cdacb5dbda/llm-test/Part-1.2_Study-results_N-shot-prompt-engineering/summary.csv#L2
[a7-extraction]: https://github.com/AnniecTW/6-moveon/blob/523e484f4e4af3a09bc7cafaa5c9c2cdacb5dbda/docs/A7-part1/output/summary.csv#L41
[a7-scoring]: https://github.com/AnniecTW/6-moveon/blob/523e484f4e4af3a09bc7cafaa5c9c2cdacb5dbda/docs/A7-part1/system_design.md#L14
[a7-purchase]: https://github.com/AnniecTW/6-moveon/blob/523e484f4e4af3a09bc7cafaa5c9c2cdacb5dbda/docs/A7-part1/system_design.md#L98
[pricing-notes]: https://github.com/AnniecTW/6-moveon/blob/523e484f4e4af3a09bc7cafaa5c9c2cdacb5dbda/docs/pricing/implementation_notes.md#L37
[ai-setup]: https://github.com/AnniecTW/6-moveon/blob/523e484f4e4af3a09bc7cafaa5c9c2cdacb5dbda/README.md#L88
