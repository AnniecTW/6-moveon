"""Apply a manually reviewable MerRec-to-MoveOn c1/c2 mapping to deduplicated items.

Usage (run from experiments/merrec-pricing):
    python3 preprocessing/apply_merrec_mapping.py \
      --input preprocessing/output/home_items_clean.csv \
      --mapping mapping/merrec_to_moveon_mapping_v1_1.csv \
      --output-dir preprocessing/output/mapping_v1_1

Mapping decisions:
 KEEP    -> pilot item-level data (titles still merit spot checks)
 REVIEW  -> needs title-level human review; not used for training yet
 EXCLUDE -> out of this MVP's core product scope

No train/test split and no model training are performed here.
"""
from __future__ import annotations
import argparse
import csv
from collections import Counter, defaultdict
from pathlib import Path
import re

BASE_DIR = Path(__file__).resolve().parent.parent

NEEDS_REVIEW = re.compile(
    r'\b(?:replacement|refill|spare(?:\s+part)?|parts?\s+only|parts?\s+for|'
    r'attachments?\s+only|accessories\s+only|empty\s+box|'
    r'filter(?:s)?|lid\s+only|remote\s+only|cover\s+only)\b',
    re.IGNORECASE,
)

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--input', default=str(BASE_DIR / 'preprocessing/output/home_items_clean.csv'))
parser.add_argument('--mapping', default=str(BASE_DIR / 'mapping/merrec_to_moveon_mapping_v1_1.csv'))
parser.add_argument('--output-dir', default=str(BASE_DIR / 'preprocessing/output/mapping_v1_1'))
args=parser.parse_args()
input_path=Path(args.input).expanduser()
mapping_path=Path(args.mapping).expanduser()
out=Path(args.output_dir).expanduser();out.mkdir(parents=True,exist_ok=True)

with mapping_path.open(newline='',encoding='utf-8-sig') as f:
    rows=list(csv.DictReader(f))
mapping={}
required_mapping={'c1_name','c2_name','moveon_category','moveon_item_type','decision','review_reason'}
if not rows or required_mapping-set(rows[0]):
    raise SystemExit(f'Wrong mapping CSV header; missing {required_mapping-set(rows[0] if rows else [])}')
for r in rows:
    key=(r['c1_name'].strip(),r['c2_name'].strip())
    if key in mapping:
        raise SystemExit(f'Duplicate mapping key: {key}')
    if r['decision'] not in {'KEEP','REVIEW','EXCLUDE'}:
        raise SystemExit(f'Invalid decision at {key}: {r["decision"]}')
    if r['decision']=='KEEP' and (not r['moveon_category'] or not r['moveon_item_type']):
        raise SystemExit(f'KEEP without target category/type: {key}')
    mapping[key]=r

with input_path.open(newline='',encoding='utf-8-sig') as f:
    reader=csv.DictReader(f)
    cols=list(reader.fieldnames or [])
    needed={'item_id','stime','price','name','c1_name','c2_name'}
    if needed-set(cols):
        raise SystemExit(f'Missing input columns: {needed-set(cols)}')
    items=list(reader)
seen=set()
for r in items:
    item_id=r['item_id'].strip()
    if not item_id or item_id in seen:
        raise SystemExit('Input must be item-level: item_id unique and nonblank. Run deduplication first.')
    seen.add(item_id)
    try:
        if float(r['price'])<=0: raise ValueError()
    except (ValueError, TypeError):
        raise SystemExit(f'Missing/invalid observed price for item_id={item_id}')

addition=['observed_price_at_buy_comp','moveon_category','moveon_item_type',
          'mapping_decision','mapping_reason','title_qc_flag','effective_decision']
fields=cols+[c for c in addition if c not in cols]
records=[]
for item in items:
    key=(item['c1_name'].strip(),item['c2_name'].strip())
    rule=mapping.get(key)
    r=dict(item)
    r['observed_price_at_buy_comp']=r['price']
    r['moveon_category']=rule['moveon_category'].strip() if rule else ''
    r['moveon_item_type']=rule['moveon_item_type'].strip() if rule else ''
    r['mapping_decision']=rule['decision'] if rule else 'REVIEW'
    r['mapping_reason']=rule['review_reason'] if rule else 'No mapping rule for source c1/c2.'
    flagged=bool(NEEDS_REVIEW.search(r.get('name','')))
    r['title_qc_flag']='possible_part_filter_or_accessory' if flagged else ''
    # Conservative: never silently send title-flagged items to the training candidate CSV.
    r['effective_decision']='REVIEW' if flagged and r['mapping_decision']=='KEEP' else r['mapping_decision']
    if flagged and r['mapping_decision']=='KEEP':
        r['mapping_reason'] += ' Title contains a possible component/consumable keyword; check it manually.'
    records.append(r)

files={
    'KEEP':'home_items_mapping_candidates.csv',
    'REVIEW':'home_items_for_manual_review.csv',
    'EXCLUDE':'home_items_out_of_scope.csv',
}
for decision, filename in files.items():
    sub=[r for r in records if r['effective_decision']==decision]
    with (out/filename).open('w',encoding='utf-8',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore')
        writer.writeheader();writer.writerows(sub)

counts=defaultdict(Counter)
for r in records:
    key=(r['moveon_category'] or '(unassigned)',r['moveon_item_type'] or '(unspecified)')
    counts[key][r['effective_decision']]+=1
with (out/'moveon_type_counts_actual.csv').open('w',newline='',encoding='utf-8') as f:
    writer=csv.DictWriter(f,fieldnames=['moveon_category','moveon_item_type','n_keep','n_review','n_exclude'])
    writer.writeheader()
    for (cat,typ),ct in sorted(counts.items(),key=lambda z: -sum(z[1].values())):
        writer.writerow(dict(moveon_category=cat,moveon_item_type=typ,
                             n_keep=ct['KEEP'],n_review=ct['REVIEW'],n_exclude=ct['EXCLUDE']))

summary=Counter(r['effective_decision'] for r in records)
print(f'Input unique item IDs: {len(records):,}; mapped c1/c2 rules: {len(mapping)}')
for decision in ('KEEP','REVIEW','EXCLUDE'):
    print(f'{decision:7s}: {summary[decision]:,} items -> {out/files[decision]}')
print(f'Title flags: {sum(bool(r["title_qc_flag"]) for r in records):,}; flags within KEEP were moved to REVIEW.')
print('Type counts:',out/'moveon_type_counts_actual.csv')
print('IMPORTANT: KEEP = candidates for experiments, not error-free labels or confirmed final paid prices.')
print('IMPORTANT: before evaluating models, chronological holdout + item_id disjoint train/valid/test.')
