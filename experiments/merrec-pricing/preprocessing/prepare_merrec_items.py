"""Create one item-level row per item_id from filtered MerRec Home buy_comp events.

Run after inspect_merrec_multi.py, across *all* selected shards:
    python3 prepare_merrec_items.py \
      --input output/home_buycomp_multi_shard_raw.csv \
      --output output/home_items_clean.csv

Repeated buy_comp events are not assumed to be distinct sales. Conflicts in
observed price or product attributes cause an explicit stop for review.
"""
from __future__ import annotations
import argparse
from pathlib import Path
import pandas as pd

BASE_DIR = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', default=str(BASE_DIR / 'output/home_buycomp_multi_shard_raw.csv'))
    parser.add_argument('--output', default=str(BASE_DIR / 'output/home_items_clean.csv'))
    args = parser.parse_args()
    source = Path(args.input).expanduser()
    dest = Path(args.output).expanduser()

    df = pd.read_csv(source, dtype={'item_id': 'string'}, low_memory=False)
    mandatory = {'item_id', 'stime', 'price', 'name', 'c0_name', 'event_id'}
    missing = mandatory - set(df.columns)
    if missing:
        raise SystemExit(f'Missing required columns: {sorted(missing)}')
    df['item_id'] = df['item_id'].astype('string').str.strip()
    df['stime'] = pd.to_datetime(df['stime'], utc=True, errors='coerce')
    df['price'] = pd.to_numeric(df['price'], errors='coerce')
    if df['item_id'].isna().any() or df['item_id'].eq('').any():
        raise SystemExit('Missing/empty item_id: audit before deduplicating.')
    if df['stime'].isna().any():
        raise SystemExit('Missing/invalid timestamp: audit before deduplicating.')
    if df['price'].isna().any() or (df['price'] <= 0).any():
        raise SystemExit('Missing/non-positive observed price: audit before deduplicating.')
    if not df['event_id'].eq('buy_comp').all() or not df['c0_name'].str.strip().str.casefold().eq('home').all():
        raise SystemExit('Input must contain only c0_name=Home and event_id=buy_comp.')

    check_columns = [x for x in (
        'price', 'name', 'c0_name', 'c1_name', 'c2_name', 'brand_name',
        'item_condition_id', 'item_condition_name', 'shipper_name',
    ) if x in df.columns]
    differing = df.groupby('item_id', dropna=False)[check_columns].nunique(dropna=False)
    conflicts = differing.index[differing.gt(1).any(axis=1)].tolist()
    if conflicts:
        raise SystemExit(f'Conflicting attributes for {len(conflicts)} item IDs; manually review before deduplication: {conflicts[:20]}')

    # Stable sort ensures one deterministic representative record for each listing.
    items = (df.sort_values(['stime', 'item_id'], kind='stable')
               .drop_duplicates('item_id', keep='first').copy())
    if not items['item_id'].is_unique:
        raise SystemExit('Internal error: duplicate item_id remains.')
    dest.parent.mkdir(parents=True, exist_ok=True)
    items.to_csv(dest, index=False)
    print(f'Filtered buy_comp events: {len(df):,}')
    print(f'Unique item IDs: {len(items):,}')
    print(f'Extra repeated-event rows omitted: {len(df)-len(items):,}')
    print(f'Saved item-level data to: {dest}')
    print('Note: one item_id is one modeling row, not proof of one independent paid transaction.')


if __name__ == '__main__':
    main()
