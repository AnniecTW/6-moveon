# MerRec Pricing Dataset for MoveOn

**Status:** Preliminary dataset for noncommercial pricing experiments; not production-ready.

## Source and dataset summary

- **Original dataset:** [Mercari US MerRec](https://huggingface.co/datasets/mercari-us/merrec)
- **License:** [CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/) (attribution required; noncommercial use only).
- **Attribution:** Lichi Li, Zainul Abi Din, Zhen Tan, Sam London, Tianlong Chen, and Ajay Daptardar, [“MerRec: A Large-scale Multipurpose Mercari Dataset for Consumer-to-Consumer Recommendation Systems”](https://doi.org/10.1145/3690624.3709394), KDD 2025.

| Stage | Count |
|---|---:|
| Events scanned (60 Parquet shards) | 35,244,555 |
| `event_id == "buy_comp"` and `c0_name == "Home"` | 2,706 events |
| Unique items after deduplication | 2,697 |
| **Final `stable_pricing_items_v1.csv`** | **1,409 items** |

## Sampling and downloading original data

MerRec stores events in monthly folders containing multiple Parquet **shards** (files). We sampled **10 shards per month from May through October 2023**, for **60 shards total**, using a fixed seed (`42`). The script sorts available shard paths before seeded selection. The exact sampled paths are recorded in `data/merrec_selected_shards.txt`; when the script runs, it writes a fresh manifest to `preprocessing/output/merrec_selected_shards.txt`.

From the repository root, download and reproduce the **filtered event-level data** using `inspect_merrec_multi.py`:

```bash
cd experiments/merrec-pricing
python3 -m pip install pandas pyarrow huggingface_hub
python3 preprocessing/inspect_merrec_multi.py \
  --months 20230501 20230601 20230701 20230801 20230901 20231001 \
  --shards-per-month 10 --seed 42
```

The script writes the filtered event CSV and a fresh shard manifest under `preprocessing/output/`. The raw Parquet data is **not** committed to this repository. This command recreates the filtered events, **not** the final cleaned CSV.

Re-running the inspection script replaces its previous raw CSV, duplicate report, and generated manifest. The manifest records shard paths but does not pin a dataset revision or file hashes, so selection depends on the current MerRec repository listing.

To continue from those filtered events and rebuild the item-level dataset, run these commands from `experiments/merrec-pricing` in order:

```bash
python3 preprocessing/prepare_merrec_items.py \
  --input preprocessing/output/home_buycomp_multi_shard_raw.csv \
  --output preprocessing/output/home_items_clean.csv
python3 preprocessing/apply_merrec_mapping.py \
  --input preprocessing/output/home_items_clean.csv \
  --mapping mapping/merrec_to_moveon_mapping_v1_1.csv \
  --output-dir preprocessing/output/mapping_v1_1
python3 preprocessing/refine_merrec_titles.py \
  --input preprocessing/output/mapping_v1_1/home_items_for_manual_review.csv \
  --output-dir preprocessing/output/title_refinement_v1
python3 preprocessing/build_stable_merrec_v1.py \
  --review preprocessing/output/title_refinement_v1/home_items_title_refined_review.csv \
  --qc mapping/title_qc_sample_edited.csv \
  --keep preprocessing/output/mapping_v1_1/home_items_mapping_candidates.csv \
  --output-dir preprocessing/output/final_v1
```

The rebuilt CSV is `preprocessing/output/final_v1/stable_pricing_items_v1.csv`; the checked-in experiment copy is `data/stable_pricing_items_v1.csv`. Intermediate files and downloaded shards are local outputs and are not included in this repository.

## Preprocessing workflow

1. **Filter events:** Keep only `event_id == "buy_comp"` and `c0_name == "Home"` from the 60 sampled shards (2,706 events).
2. **Audit and deduplicate:** Check repeated `item_id`s and price conflicts across shards. Nine items appeared twice with no observed price differences; retain the earliest valid `buy_comp` event per item (2,697 unique items). Repeated events are not treated as independent sales.
3. **Map categories:** Combine existing MoveOn categories with selected categories from Mercari's taxonomy, using `c1_name` and `c2_name` to define more suitable item types while preserving the original labels.
4. **Refine with titles:** Apply conservative title-based rules (e.g., reclassify a seasonal mug as *Mugs & Cups*), limited manual QC, and flags for accessories, bundles, collectibles, or ambiguous items.
5. **Build stable v1:** Retain only sufficiently clear candidates for initial modeling; defer uncertain records rather than forcing classifications. Final output: **1,409 unique items** in `stable_pricing_items_v1.csv`.

The final classifications are **not fully human-verified**, and items deferred from modeling are not necessarily out of scope for the MoveOn marketplace.

## Using the CSV

Use `data/stable_pricing_items_v1.csv` as the item-level experiment dataset. For an initial pricing task, use `price` as the prediction target; it is only the observed price associated with a `buy_comp` event, not a confirmed final payment. `observed_price_at_buy_comp` currently duplicates `price`, so do not include either column among input features. Reasonable starting features include `name`, `moveon_category`, `moveon_item_type`, `brand_name`, and `item_condition_name`. Treat `item_id` as an identifier for deduplication and split checks, and exclude it and `source_shard` from model features.

## Notes and limitations

- **Condition imbalance:** In the stable dataset, **968/1,409 items (68.7%) are New**; only **9 Fair and 1 Poor** items remain.
- **Category imbalance:** In the original 2,706 filtered events, `Home decor` (668) and `Seasonal decor` (653) account for **48.8%**. Only **15 Furniture items** remain in stable v1.
- **Price meaning:** `price` is the **observed item price at a `buy_comp` event**, **not a confirmed final transaction payment**. We have contacted the dataset author and are awaiting clarification.
- **Coverage:** Historical US-wide listings may differ from current student-market prices. The shared subset does not include full descriptions, images, or reliable item-age fields.

## Future evaluation

**No split has been made yet.** Reserve **later `stime` values for testing**, keep the same `item_id` out of multiple train/validation/test sets, and fit preprocessing and comparable-item retrieval on training data only. Compare against simple price baselines and report errors by condition and item type.
