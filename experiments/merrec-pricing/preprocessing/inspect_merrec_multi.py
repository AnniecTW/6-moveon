"""Inspect multiple official MerRec Parquet shards for Home + buy_comp events.

No model training, no item-level deduplication, and no train/test split here.

Examples:
  python3 inspect_merrec_multi.py --months 20230501 20230601 --shards-per-month 3
  python3 inspect_merrec_multi.py --months 20230501 20230601 20230701 20230801 20230901 20231001 --shards-per-month 10

Dependencies:
  python3 -m pip install pandas pyarrow huggingface_hub

Raw output is EVENT-level. Audit repeated item_id across ALL chosen shards.
"""

from __future__ import annotations

import argparse
import random
from collections import Counter
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

REPO_ID = "mercari-us/merrec"
ALL_MONTHS = ("20230501", "20230601", "20230701", "20230801", "20230901", "20231001")
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
OUTPUT_DIR = BASE_DIR / "output"

# No user_id/session_id because they are unnecessary for this first item-level audit.
COLUMNS = [
    "item_id", "event_id", "stime", "price", "name",
    "c0_name", "c1_name", "c2_name", "brand_name",
    "item_condition_id", "item_condition_name", "shipper_name",
]


def select_shards(months: list[str], per_month: int, seed: int) -> list[str]:
    """List actual shard paths from HF; select a reproducible, growing sample."""
    from huggingface_hub import HfApi

    api = HfApi()
    selected: list[str] = []
    for month in months:
        print(f"Listing available shards in {month}...")
        tree = api.list_repo_tree(
            repo_id=REPO_ID, repo_type="dataset", path_in_repo=month,
            recursive=False,
        )
        names = sorted(
            node.path for node in tree
            if node.path.endswith(".parquet") and node.path.startswith(month + "/")
        )
        if not names:
            raise RuntimeError(f"No Parquet files found for {month}.")

        # Stable random order: increasing per_month retains previously selected files.
        random.Random(f"{seed}-{month}").shuffle(names)
        chosen = names[:per_month]
        print(f"  Found {len(names)}; selected {len(chosen)}")
        selected.extend(chosen)
    return selected


def inspect_shard(parquet_path: Path, shard_name: str, raw_csv: Path, write_header: bool):
    """Stream one file and append only Home + buy_comp events."""
    parquet = pq.ParquetFile(parquet_path)
    missing = set(COLUMNS) - set(parquet.schema_arrow.names)
    if missing:
        raise ValueError(f"Missing columns in {shard_name}: {sorted(missing)}")

    row_count = 0
    selected_count = 0
    event_counts = Counter()
    home_event_counts = Counter()

    for batch in parquet.iter_batches(batch_size=50_000, columns=COLUMNS):
        frame = batch.to_pandas()
        row_count += len(frame)
        event_counts.update(frame["event_id"].fillna("<missing>").value_counts().to_dict())

        home = frame.loc[
            frame["c0_name"].astype("string").str.strip().str.casefold().eq("home").fillna(False)
        ]
        home_event_counts.update(home["event_id"].fillna("<missing>").value_counts().to_dict())
        selected = home.loc[home["event_id"].eq("buy_comp")].copy()
        if not selected.empty:
            # Preserve IDs as identifiers, never coerce to floats.
            selected["item_id"] = selected["item_id"].astype("string")
            selected["source_shard"] = shard_name
            selected.to_csv(raw_csv, mode="a", header=not write_header, index=False)
            write_header = True
            selected_count += len(selected)

    return row_count, selected_count, event_counts, home_event_counts, write_header


def audit(raw_csv: Path, duplicate_csv: Path):
    if not raw_csv.exists() or raw_csv.stat().st_size == 0:
        print("\nNo Home buy_comp records found in selected shards.")
        return

    buy = pd.read_csv(raw_csv, dtype={"item_id": "string"}, low_memory=False)
    if buy.empty:
        print("\nNo Home buy_comp records found in selected shards.")
        return

    buy["price"] = pd.to_numeric(buy["price"], errors="coerce")
    buy["stime"] = pd.to_datetime(buy["stime"], utc=True, errors="coerce")
    buy["item_id"] = buy["item_id"].astype("string").str.strip()
    buy.loc[buy["item_id"].eq(""), "item_id"] = pd.NA

    groups = buy.dropna(subset=["item_id"]).groupby("item_id", sort=False)
    counts = groups.size()
    repeats = counts[counts > 1]
    varying_prices = groups["price"].nunique(dropna=True)
    different_price_ids = varying_prices[varying_prices > 1]

    print("\n=== HOME + BUY_COMP QUALITY AUDIT (ALL SELECTED SHARDS) ===")
    print(f"Purchase-complete event rows: {len(buy):,}")
    print(f"Unique item IDs: {buy['item_id'].nunique():,}")
    print(f"Repeated item IDs (>1 event): {len(repeats):,}")
    print(f"Extra event rows from repeated item IDs: {int((repeats - 1).sum()):,}")
    print(f"Item IDs with different observed prices: {len(different_price_ids):,}")
    print(f"Missing/non-positive prices: {(buy['price'].isna() | (buy['price'] <= 0)).sum():,}")
    print(f"Missing item IDs: {buy['item_id'].isna().sum():,}")
    print(f"Missing timestamps: {buy['stime'].isna().sum():,}")
    print(f"Timestamp range: {buy['stime'].min()} to {buy['stime'].max()}")

    print("\nRecords by month (based on event timestamps):")
    print(buy["stime"].dt.strftime("%Y-%m").fillna("<missing>").value_counts().sort_index().to_string())
    print("\nHome subcategories (top 20):")
    print(buy["c1_name"].fillna("<missing>").value_counts().head(20).to_string())
    print("\nCondition labels:")
    print(buy["item_condition_name"].fillna("<missing>").value_counts().to_string())
    print("\nPositive price distribution (USD):")
    print(buy.loc[buy["price"] > 0, "price"].describe(percentiles=[.25, .5, .75, .95]).to_string())

    if not repeats.empty:
        repeated_ids = set(repeats.index)
        buy.loc[buy["item_id"].isin(repeated_ids)].sort_values(
            ["item_id", "stime"], kind="stable"
        ).to_csv(duplicate_csv, index=False)
        print(f"\nRepeated-item event details: {duplicate_csv}")

    print(f"\nRaw EVENT data: {raw_csv}")
    print("NOT deduplicated; NOT yet suitable for direct model training.")
    print("Do not assume 'price' is a verified final transaction payment.")
    print("Later split: the same item_id must not cross train/test, and newer items form the time holdout.")


def main():
    parser = argparse.ArgumentParser(description="Inspect multiple MerRec Parquet shards")
    parser.add_argument("--months", nargs="+", choices=ALL_MONTHS,
                        default=["20230501", "20230601"],
                        help="Month folders to sample (default: May and June 2023)")
    parser.add_argument("--shards-per-month", type=int, default=3,
                        help="Number of Parquet shards per selected month (default: 3)")
    parser.add_argument("--seed", type=int, default=42,
                        help="Reproducible shard selection; keep unchanged when expanding")
    args = parser.parse_args()
    if args.shards_per_month < 1:
        parser.error("--shards-per-month must be at least 1")
    if len(set(args.months)) != len(args.months):
        parser.error("Do not repeat months")

    from huggingface_hub import hf_hub_download
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    raw_csv = OUTPUT_DIR / "home_buycomp_multi_shard_raw.csv"
    duplicate_csv = OUTPUT_DIR / "repeated_buycomp_item_ids.csv"
    shard_manifest = OUTPUT_DIR / "merrec_selected_shards.txt"
    for path in (raw_csv, duplicate_csv, shard_manifest):
        if path.exists():
            path.unlink()

    shards = select_shards(args.months, args.shards_per_month, args.seed)
    shard_manifest.write_text("\n".join(shards) + "\n", encoding="utf-8")

    print(f"\nSelected {len(shards)} shards. Individual files are often ~70–90 MB.")
    print("Downloads are cached locally; large runs may take some time and disk space.")

    total_events = 0
    total_home_buy = 0
    all_events = Counter()
    home_events = Counter()
    wrote_header = False

    for i, shard in enumerate(shards, 1):
        print(f"\n[{i}/{len(shards)}] Downloading/using {shard}")
        parquet_path = Path(hf_hub_download(
            repo_id=REPO_ID, filename=shard, repo_type="dataset", local_dir=str(DATA_DIR)
        ))
        n, n_buy, event_counts, home_counts, wrote_header = inspect_shard(
            parquet_path, shard, raw_csv, wrote_header
        )
        total_events += n
        total_home_buy += n_buy
        all_events.update(event_counts)
        home_events.update(home_counts)
        print(f"  Events: {n:,}; Home buy_comp: {n_buy:,}; cumulative Home buy_comp: {total_home_buy:,}")

    print("\n=== EVENT FREQUENCIES (ALL SELECTED SHARDS) ===")
    print(f"Shards read: {len(shards):,}")
    print(f"Total events: {total_events:,}")
    print("All event types:", dict(all_events))
    print("Home event types:", dict(home_events))
    audit(raw_csv, duplicate_csv)
    print(f"\nSelected shard list: {shard_manifest}")


if __name__ == "__main__":
    main()
