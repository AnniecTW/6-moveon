#!/usr/bin/env python3
"""Create a CONSERVATIVE, ITEM-LEVEL MoveOn/MerRec initial pricing subset.

Usage (run from experiments/merrec-pricing):
  python3 preprocessing/build_stable_merrec_v1.py \
    --review preprocessing/output/title_refinement_v1/home_items_title_refined_review.csv \
    --qc mapping/title_qc_sample_edited.csv \
    --keep preprocessing/output/mapping_v1_1/home_items_mapping_candidates.csv \
    --output-dir preprocessing/output/final_v1

Outputs: stable_pricing_items_v1.csv, deferred_items_v1.csv,
         moveon_item_type_counts_v1.csv, and dataset_audit_v1.txt in the output directory.

Does not establish final paid price, make model splits, or guarantee correct labels.
No training data is overwritten. Uses Python standard library.
"""
import argparse
import csv
from collections import Counter
from datetime import datetime
from pathlib import Path
import re

BASE = Path(__file__).resolve().parent

# Exclude from pricing experiments, NOT necessarily from MoveOn product catalog.
# Flag doubtful product identity, mixed product-kind bundles, parts, or unusual collectibles.
PRICE_RISK_PATTERNS = [
    ('part_or_accessory', r'\b(?:replacement|refills?|filters?|spare\s*(?:parts?)?|parts?\s*(?:only|for)|power\s*(?:cord|adapter)|remote\s*only|no\s*remote|attachments?\s*(?:only|for)|fridge\s*fan|refrigerator\s*fan|air\s*conditioner\s*(?:support|bracket|stand|mount)|a\s*/\s*c\s*(?:bracket|support)|a\/?c\s*(?:bracket|support)|support\s*(?:bracket|for\s*air\s*conditioner)|sofa\s*(?:covers?|slipcovers?)|couch\s*cover|slipcovers?|chair\s*cover|refrigerator\s*water\s*filter|lamp\s*shades?|empty\s*box|box\s*only|empty\s*packaging|for\s*parts|food\s*grinder\s*attachments?)\b'),
    ('ambiguous_holder', r'\b(?:candle\s*(?:holders?|sleeves?|snuffers?|lids?|toppers?)|tea\s*light\s*holders?|tealight\s*holders?|mug\s*(?:holders?|toppers?)|votive\s*hurricane)\b'),
    ('mixed_product_bundle', r'\b(?:blankets?\s*(?:and|&|\+|with)\s*pillows?|pillows?\s*(?:and|&|\+|with)\s*blankets?|creamers?\s*(?:and|&|\+|with)\s*(?:a\s*)?mugs?|mugs?\s*(?:and|&|\+|with)\s*(?:creamers?|plates?|spoons?)|measuring\s*cups?.*\bbundle\b|mixed\s*bundle|mystery\s*(?:box|bundle)|random\s*lot|assorted\s*items?|kitchen\s*towels?\s*(?:and|&|\+)\s*oven\s*mitts?)\b'),
    ('collector_pricing_risk', r'\b(?:vintage|antique|rare|vhtf|htf|retired|limited\s*edition|discontinued|signed|autographed?|collectors?|collectibles?|museum\s*quality|one\s*of\s*a\s*kind)\b'),
    ('not_ordinary_functional_item', r'\b(?:genie\s*lamp|oil\s*lamp\s*decor|display\s*curio\s*cabinet\s*with\s*mirror|display\s*only|prop\s*only|non\s*working|not\s*working|broken|damaged|cracked|missing\s*parts?|for\s*display)\b'),
    ('non_home_item', r'\b(?:phone\s*cases?|video\s*games?|trading\s*cards?|shoe\s*charms?|earrings?|necklaces?|cosmetics?)\b'),
]
RISK_RE = [(name, re.compile(expr, re.IGNORECASE)) for name, expr in PRICE_RISK_PATTERNS]

# Explicit user decisions after reviewing a sample. Catalog classification is separated
# from whether to include unusual items in the *initial pricing model*.
USER_OVERRIDES = {
    '25649039': dict(decision='ACCEPT', category='Home Decor', item_type='Decorative Accessories', note='Candle sleeve/holder, not the candle itself.'),
    '185999475': dict(decision='REJECT', category='Kitchen & Dining', item_type='Mugs & Cups', note='Candy-corn sugar creamer with mug is a mixed product bundle.'),
    '111781470': dict(decision='REJECT', category='Home Decor', item_type='Decorative Accessories', note='Vintage fused-glass art bowl; collector-driven pricing.'),
    '173556984': dict(decision='CORRECT', category='Kitchen & Dining', item_type='Servingware', note='Salt pig is a tabletop salt vessel, not general food storage; rare-title warning retained.'),
    '125851731': dict(decision='REJECT', category='Appliances', item_type='Appliance Parts & Accessories', note='Air-conditioner mounting/support bracket, not a complete air-care appliance.'),
}

REQUIRED = {'item_id','name','c1_name','c2_name','stime','price','moveon_category','moveon_item_type'}
OUTPUT_COLUMNS = [
    'item_id','stime','price','name','c0_name','c1_name','c2_name',
    'brand_name','item_condition_id','item_condition_name','shipper_name',
    'observed_price_at_buy_comp','source_shard',
    'moveon_category','moveon_item_type','classification_source',
    'classification_evidence','human_verified','price_risk_flags',
    'training_eligibility','exclusion_reason',
]


def read_csv(path, required=REQUIRED):
    with Path(path).open('r', newline='', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        fields = set(reader.fieldnames or [])
        if required - fields:
            raise ValueError(f'Missing fields in {path}: {sorted(required-fields)}')
        return list(reader)


def write_csv(path, rows, fields=OUTPUT_COLUMNS):
    with Path(path).open('w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore')
        w.writeheader()
        w.writerows(rows)


def initial_risks(title):
    return [name for name, pattern in RISK_RE if pattern.search(title or '')]


def classify_review(row, qc):
    out = dict(row)
    item = out['item_id'].strip()
    title = out['name'].strip()
    risks = initial_risks(title)
    title_status = out.get('title_review_status','').strip()
    proposed_cat = out.get('proposed_moveon_category','').strip()
    proposed_type = out.get('proposed_moveon_item_type','').strip()
    manual = qc.get(item, {})
    decision = manual.get('reviewer_decision','').strip().upper()
    cat = proposed_cat
    typ = proposed_type
    method = 'title_rule'
    evidence = out.get('title_rule_ids','').strip()
    human_verified = 'NO'
    excluded_reason = ''

    if item in USER_OVERRIDES:
        override = USER_OVERRIDES[item]
        decision = override['decision']
        cat,typ=override['category'],override['item_type']
        method = 'user_override'
        evidence = override['note']
        human_verified = 'YES'
    elif decision in {'ACCEPT','CORRECT','REJECT'}:
        method = 'reviewer_qc'
        evidence = (manual.get('reviewer_notes','') or '').strip() or 'Reviewed sample decision'
        human_verified = 'YES'
        if decision=='CORRECT':
            cat = manual.get('reviewer_category','').strip() or proposed_cat
            typ = manual.get('reviewer_item_type','').strip() or proposed_type
    elif decision=='UNSURE':
        excluded_reason='unresolved_manual_review'
    elif decision:
        excluded_reason=f'invalid_qc_decision:{decision}'

    if decision=='REJECT':
        excluded_reason='explicitly_rejected_from_pricing'
    elif decision in {'ACCEPT','CORRECT'}:
        # Human-reviewed classification can override a general title risk.
        if not cat or not typ:
            excluded_reason='human_label_incomplete'
        if 'non_home_item' in risks and item not in USER_OVERRIDES:
            excluded_reason='non_home_item_even_after_review'
    else:
        # No manual decision: conservative auto inclusion ONLY if the original title
        # pipeline proposed exactly one type, with no risk cues.
        if title_status!='AUTO_CANDIDATE':
            excluded_reason=excluded_reason or f'unresolved_{title_status.lower() or "title"}'
        elif not cat or not typ:
            excluded_reason='missing_proposed_type'
        elif risks or out.get('title_risk_flags','').strip():
            excluded_reason='title_risk_requires_review'
        elif len(title)<6:
            excluded_reason='ambiguous_title'

    if not cat or not typ:
        excluded_reason=excluded_reason or 'missing_type'
    out.update(moveon_category=cat, moveon_item_type=typ,
               classification_source=method, classification_evidence=evidence,
               human_verified=human_verified,
               price_risk_flags=';'.join(risks),
               training_eligibility='INCLUDE' if not excluded_reason else 'DEFER',
               exclusion_reason=excluded_reason)
    return out


def classify_keep(row):
    out=dict(row)
    risks=initial_risks(out.get('name',''))
    excluded=''
    if out.get('effective_decision','')!='KEEP':
        excluded='not_keep_after_mapping'
    elif out.get('title_qc_flag','').strip():
        excluded='previous_title_quality_flag'
    elif risks:
        excluded='title_risk_requires_review'
    elif not out.get('moveon_category','').strip() or not out.get('moveon_item_type','').strip():
        excluded='missing_taxonomy_label'
    out.update(classification_source='category_mapping_v1_1',
               classification_evidence=out.get('mapping_reason',''),
               human_verified='NO', price_risk_flags=';'.join(risks),
               training_eligibility='INCLUDE' if not excluded else 'DEFER',
               exclusion_reason=excluded)
    return out


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--review',default=str(BASE/'output/title_refinement_v1/home_items_title_refined_review.csv'))
    p.add_argument('--qc',default=str(BASE.parent/'mapping/title_qc_sample_edited.csv'))
    p.add_argument('--keep',default=str(BASE/'output/mapping_v1_1/home_items_mapping_candidates.csv'))
    p.add_argument('--review-only',action='store_true',help='Build subset from REVIEW rows only (not the complete 2697-item dataset).')
    p.add_argument('--output-dir',default=str(BASE/'output/final_v1'))
    args=p.parse_args()
    outdir=Path(args.output_dir).expanduser()
    outdir.mkdir(parents=True,exist_ok=True)
    review=read_csv(args.review)
    qclist=read_csv(args.qc, required={'item_id','reviewer_decision'})
    qc={r['item_id'].strip():r for r in qclist if (r.get('reviewer_decision') or '').strip()}
    if len(qc)!=len([r for r in qclist if (r.get('reviewer_decision') or '').strip()]):
        raise ValueError('Duplicate reviewed item_id found in QC CSV.')
    if len({r['item_id'] for r in review})!=len(review):
        raise ValueError('REVIEW file must contain unique item_id values.')
    ids={r['item_id'] for r in review}
    if not set(qc).issubset(ids):
        raise ValueError(f'QC contains item IDs not present in REVIEW data: {set(qc)-ids}')
    records=[classify_review(r,qc) for r in review]
    if not args.review_only:
        keepfile=Path(args.keep).expanduser()
        if not keepfile.is_file():
            raise FileNotFoundError(f'Missing KEEP input: {keepfile}. Run apply_merrec_mapping.py first or use --keep PATH.')
        keep=read_csv(keepfile)
        ids2={r['item_id'] for r in keep}
        if len(ids2)!=len(keep):
            raise ValueError('KEEP must have unique item_id values.')
        if ids2 & ids:
            raise ValueError(f'KEEP and REVIEW overlap on item IDs: {ids2 & ids}')
        records += [classify_keep(r) for r in keep]
    for r in records:
        if not r['item_id'].strip(): raise ValueError('Missing item_id.')
        try:
            if float(r['price'])<=0: raise ValueError('nonpositive price')
            datetime.fromisoformat(r['stime'].strip().replace('Z','+00:00'))
        except (TypeError,ValueError):
            raise ValueError(f'Invalid price or timestamp for item_id={r["item_id"]}')
    records.sort(key=lambda r:(r['stime'],r['item_id']))
    stable=[r for r in records if r['training_eligibility']=='INCLUDE']
    deferred=[r for r in records if r['training_eligibility']!='INCLUDE']
    write_csv(outdir/'stable_pricing_items_v1.csv',stable)
    write_csv(outdir/'deferred_items_v1.csv',deferred)
    typecounts=Counter((r['moveon_category'],r['moveon_item_type']) for r in stable)
    write_csv(outdir/'moveon_item_type_counts_v1.csv',
        [dict(moveon_category=c,moveon_item_type=t,n_items=n) for (c,t),n in sorted(typecounts.items(),key=lambda x:(-x[1],x[0]))],
        ['moveon_category','moveon_item_type','n_items'])
    counts=Counter(r['classification_source'] for r in stable)
    reasons=Counter(r['exclusion_reason'] for r in deferred)
    txt=[
        'MERREC / MOVEON PRICING SUBSET v1 (PRELIMINARY, NOT PRODUCTION)',
        f'Input mode: {"REVIEW ONLY (incomplete)" if args.review_only else "REVIEW + KEEP"}',
        f'REVIEW source rows: {len(review)}',
        f'Rows processed: {len(records)}',
        f'INCLUDE candidate items: {len(stable)}',
        f'DEFER candidate items: {len(deferred)}',
        f'Unique included item IDs: {len(set(r["item_id"] for r in stable))}',
        f'Newest included time: {max((r["stime"] for r in stable),default="n/a")}',
        'Included classification sources: '+str(dict(counts)),
        'Defer reasons: '+str(dict(reasons)),
        'price is OBSERVED item price on buy_comp event, NOT confirmed final payment.',
        'NO train/test split was performed. Later split chronologically by stime with item_id disjoint across splits.',
        'Price/condition/class coverage may be biased, especially New and Home decor / seasonal listings.',
        'Source: https://huggingface.co/datasets/mercari-us/merrec ; CC BY-NC 4.0; noncommercial use only.',
        'Manual ACCEPT means classification checked for that record; rule-based INCLUDE is NOT human verified.',
        'DEFER means exclude from this PRICING experiment, not from the MoveOn product catalog.',
    ]
    (outdir/'dataset_audit_v1.txt').write_text('\n'.join(txt)+'\n',encoding='utf-8')
    print('\n'.join(txt[:11]))
    print('Wrote outputs to:',outdir)


if __name__=='__main__':main()
