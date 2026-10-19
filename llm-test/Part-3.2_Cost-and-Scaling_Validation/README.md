# Part 3, Q2 — Cost and Scaling: Input-Token Validation

This folder supports the input-token estimate in our Production Reflection. The saved countTokens run was recorded on **2026-10-18**. The English notebook was prepared on 2026-10-19 without another API run.

## Files

| File | Purpose |
|---|---|
| [English counting notebook](Part-3.2_gemini-input-token-counts.ipynb) | Request construction, official countTokens calls, and summary/export code. |
| [Input listings](inputs/listings.json) and [queries](inputs/gold_labels.json) | Exact original inputs; their SHA-256 hashes match the saved summary. |
| [Request bodies](results/count_requests.json) | Eight requests for checking the system instructions, query, and catalogue. |
| [Recorded counts](results/input_token_counts.csv) | Per-query input counts and measurement metadata. |
| [Summary](results/summary.json) | Model, scope, aggregate counts, input hashes, and unmeasured quantities. |

## Recorded result

Model: **gemini-3.6-flash**. Counts for queries 1–8: **2841, 2838, 2844, 2838, 2837, 2839, 2836, 2836**. The sum is **22,709** and the mean is **2,838.625 input tokens per request** (range 2,836–2,844).

Each request contains the application system instructions, one shopper query, and all 40 listings. Only query IDs and query text are read from the gold-label file; answer labels are excluded. Category names are available, but item types are not. The fixed catalogue does not reproduce Django's dynamic candidate retrieval.

The original inputs are retained here because their byte hashes differ from the Part 1 copies at the parent directory, although their parsed JSON content is the same. The saved summary identifies the exact files used for this measurement.

These are official preflight **input counts**, not generated outputs or observed production costs. Output tokens, thinking tokens, generation latency, concurrent capacity, and search quality were not measured. Q2's output-token allowance remains an assumption.

## Review or reproduce

Review the saved requests, CSV, and summary without calling any API. To reproduce, open the English notebook in Colab, use a standard CPU runtime, upload both files from inputs/, and enter a suitable Gemini API key through the hidden prompt. The notebook's original computation and request format are unchanged; only explanatory text and user-facing messages were translated. The cells retain blank execution outputs, so the saved results/ files are the evidence for the October 18 run.

A rerun creates a6_q2_token_results/ and downloads a new archive in the Colab runtime. Keep any rerun separate from the original evidence and record changes to the model, inputs, or date.

Sources: [Google token-count documentation](https://ai.google.dev/api/tokens); [Part 2 prompt source](https://github.com/AnniecTW/6-moveon/blob/89a0cfd14d7cb076be3f2170cb62c875c31c78ff/marketplace/local_llm.py).
