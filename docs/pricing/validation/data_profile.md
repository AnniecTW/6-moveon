# Phase 1 source profile

Reproduce with `python experiments/merrec-pricing/analysis/run_phase1.py` from the
repository root using `experiments/merrec-pricing/requirements.txt`. Machine
readable counts are in `data_profile.json`; the derived, normalized records are
in `experiments/merrec-pricing/data/pricing_clean_v1.csv`. The source CSV is
unchanged (SHA-256 `160c363b9df39c6007beecbfcfe1c49547ac7e4d3d9aaf5a3947bfdd2b8d7640`).
The derived CSV omits item titles, which are only used in memory to check
train/holdout name overlap.

## Source and semantics

The source is 60 selected MerRec Parquet shards containing 2023 `buy_comp`
events. Its `price` is the item price observed at that event, **not a verified
completed payment**. `observed_price_at_buy_comp` equals `price` in every
source row and is not used as a predictor. `human_verified` describes category
classification review, not sale verification. The source is US-wide, not a
sample of current UIUC sales. Shipping payer (`shipper_name`) is known, but
shipping cost and delivered total are not. There is no seller identifier,
reliable item age, model identity, or local pickup context. The source is
CC BY-NC 4.0 and unsuitable for commercial deployment without license review.

## Quality and cleaning

| Check | Result |
|---|---:|
| Source rows / columns | 1,409 / 21 |
| Unique item IDs / exact duplicate rows | 1,409 / 0 |
| Eligible source rows | 1,409 |
| Price-risk rows excluded | 2 (ambiguous holder; collector pricing risk) |
| Invalid or nonpositive prices | 0 |
| Cleaned rows | 1,407 |
| Price range | $1–$700 |
| Observation dates | 2023-05-01 to 2023-10-30 UTC |
| Unique shards | 60 |
| Unique names / names repeated across rows | 1,394 / 14 |
| Brand missing / fine subtype missing | 403 / 75 |
| Classification human verified | 15 |

The pipeline normalizes category, type, brand, name, and condition, checks
finite positive prices and timezone aware timestamps, respects eligibility,
excludes the two explicitly flagged price-risk rows, and deduplicates item IDs
by earliest observation. It performs no blind outlier removal or imputation.
Excluding flagged rows changes the modeled population slightly; the original
flags remain in the unchanged source for review. The CSV is already a selected
subset: 2,697 unique items existed before stable-v1 filtering, so selection
bias remains possible.

Category counts: Kitchen & Dining 670, Home Decor 407, Bedding & Bath 207,
Appliances 92, Storage & Organization 18, Furniture 15. Condition counts:
New 968, Good 230, Like new 201, Fair 9, Poor 1. There are 42 mapped item
types; several have fewer than five records. `shipper_name` is Buyer for 1,255
and Seller for 154. No shipping-cost adjustment is supported. No item-age
adjustment is inferred from `stime`.

## Data dictionary for pricing

- `item_id`: source item identifier, used only for deduplication and split checks.
- `stime`: timezone aware event timestamp, used for chronological splitting and
  age of the *observation*, never age of the product.
- `price`: observed event price, the statistical target.
- `name`, `brand_name`, `item_condition_name`, `moveon_category`,
  `moveon_item_type`: candidate matching/predictor attributes. Brand may be
  absent; name is used only to check duplicate product descriptions.
- `source_shard`: source traceability and cluster audit; not a predictor.
- `training_eligibility`, `price_risk_flags`, `exclusion_reason`:
  data-quality policy inputs. Every stable-v1 row is `INCLUDE`; the two risk
  flags are explicitly excluded from fitting and comparables.
- `classification_source`, `classification_evidence`, `human_verified`:
  taxonomy provenance, not verified transaction evidence.
- `c0_name`, `c1_name`, `c2_name`, `item_condition_id`, `shipper_name`,
  `observed_price_at_buy_comp`: retained source context, not model inputs.
