#!/usr/bin/env python3
"""Conservative, auditable title-based refinement of MerRec -> MoveOn REVIEW items.

Usage (run from experiments/merrec-pricing):
    python3 preprocessing/refine_merrec_titles.py \
      --input preprocessing/output/mapping_v1_1/home_items_for_manual_review.csv \
      --output-dir preprocessing/output/title_refinement_v1

Only evaluates REVIEW rows. Does NOT claim final paid prices, split data or train models.
AUTO_CANDIDATE means plausible after deterministic title rules, NOT human-verified.
Dependencies: Python standard library only.
"""
from __future__ import annotations
import argparse
import csv
from collections import Counter, defaultdict
from pathlib import Path
import random
import re

BASE_DIR = Path(__file__).resolve().parent.parent

# Regular expressions purposefully restrictive. Match a concrete item, not the broad theme.
# Exclude 'seasonal' from ordinary object matching; used only as fallback after specifics.
RULES = [
    ('coffee_machine', 'Appliances', 'Coffee & Espresso Machine', r'\b(?:coffee\s*(?:maker|machine|percolator)|espresso\s*(?:maker|machine)|keurig|k-?cup\s*(?:coffee\s*)?maker|coffee\s*brewer|cappuccino\s*(?:maker|machine)|percolator)\b'),
    ('microwave', 'Appliances', 'Microwave', r'\bmicrowave\s*(?:oven)?\b'),
    ('refrigerator', 'Appliances', 'Refrigerator', r'\b(?:mini\s*(?:fridge|refrigerator)|refrigerator|fridge|wine\s*cooler\s*(?:fridge|refrigerator)?)\b'),
    ('air_care', 'Appliances', 'Air Care & Climate', r'\b(?:space\s*heater|humidifier|dehumidifier|air\s*purifier|air\s*conditioner|portable\s*(?:a/?c|ac)\s*unit|tower\s*fan|room\s*fan)\b'),
    ('kitchen_appliance', 'Appliances', 'Kitchen Appliance', r'\b(?:blender|toaster|air\s*fryer|bread\s*maker|food\s*processor|juicer|stand\s*mixer|hand\s*mixer|electric\s*(?:kettle|skillet|can\s*opener|grill)|slow\s*cooker|instant\s*pot|pressure\s*cooker|waffle\s*maker|popcorn\s*(?:maker|machine)|vacuum\s*sealer|electric\s*griddle|rotisserie|rice\s*cooker|water\s*distiller)\b'),
    ('lamp', 'Home Decor', 'Lamp & Lighting', r'\b(?:floor\s*lamp|table\s*lamp|desk\s*lamp|lava\s*lamp|lamp|night\s*light|mood\s*light|chandelier|light\s*fixture|sconce)\b'),
    ('mirror', 'Home Decor', 'Mirror', r'\b(?:mirror|wall\s*mirror|vanity\s*mirror)\b'),
    ('clock', 'Home Decor', 'Clock', r'\b(?:clock|alarm\s*clock)\b'),
    ('wall_art', 'Home Decor', 'Wall Art & Frames', r'\b(?:wall\s*art|wall\s*hang(?:ing)?|canvas\s*(?:art|print|painting)|framed?\s*(?:art|print|picture|photo)|picture\s*frame|photo\s*frame|art\s*print|painting|wall\s*tapestry|wall\s*sign|wall\s*decor)\b'),
    ('rug', 'Home Decor', 'Rug & Mat', r'\b(?:area\s*rug|floor\s*rug|bath\s*mat|bath\s*rug|doormat|door\s*mat|welcome\s*mat|throw\s*rug)\b'),
    ('curtain', 'Home Decor', 'Curtains & Window Treatments', r'\b(?:curtains?|drapes?|window\s*blinds?|window\s*shade)\b'),
    ('decorative_pillow', 'Home Decor', 'Decorative Pillow', r'\b(?:throw\s*pillows?|decorative\s*pillows?|accent\s*pillows?)\b'),
    ('decorative_accessory', 'Home Decor', 'Decorative Accessories', r'\b(?:figurines?|vases?|artificial\s*(?:plants?|flowers?)|fake\s*(?:plants?|flowers?)|faux\s*(?:plants?|flowers?)|flower\s*pot|potted\s*(?:plants?|flowers?)|candle\s*holders?|candelabra|centerpieces?|tiered?\s*trays?|decorative\s*(?:tray|statue|sign)|statues?|pottery)\b'),
    ('candle', 'Home Decor', 'Candles', r'\b(?:candles?|tea\s*lights?|tealights?|votive\s*candles?|pillar\s*candles?)\b'),
    ('home_fragrance', 'Home Decor', 'Home Fragrance', r'\b(?:wax\s*melts?|wax\s*(?:bar|cubes?)|room\s*sprays?|reed\s*diffuser|scent\s*circles?|essential\s*oils?|fragrance\s*oils?|air\s*freshener|scented\s*sachets?)\b'),
    ('photo_album', 'Home Decor', 'Photo Albums', r'\b(?:photo\s*album|scrapbook|picture\s*album)\b'),
    ('mugs', 'Kitchen & Dining', 'Mugs & Cups', r'\b(?:mugs?|coffee\s*cups?|tea\s*cups?|teacups?|espresso\s*cups?|cups?\s*(?:and|&)\s*saucers?)\b'),
    ('bottles', 'Kitchen & Dining', 'Bottles & Tumblers', r'\b(?:water\s*bottle|tumblers?|thermos|insulated\s*(?:bottle|jug|travel\s*cup)|travel\s*mug|hip\s*flask)\b'),
    ('dinnerware', 'Kitchen & Dining', 'Dinnerware', r'\b(?:dinner\s*plates?|plates?\s*sets?|plates?|soup\s*bowls?|cereal\s*bowls?|serving\s*bowls?|bowls?|saucers?|dinnerware|dishes|dish\s*set|dinner\s*set)\b'),
    ('serveware', 'Kitchen & Dining', 'Servingware', r'\b(?:serving\s*sets?|serving\s*trays?|serving\s*platters?|pitchers?|gravy\s*boats?|salt\s*(?:and|&)\s*pepper\s*shakers?|serving\s*bowls?)\b'),
    ('cookware', 'Kitchen & Dining', 'Cookware', r'\b(?:frying\s*pans?|saucepans?|skillets?|dutch\s*ovens?|cooking\s*pots?|woks?|roasters?|stockpots?|non\s*stick\s*pans?)\b'),
    ('bakeware', 'Kitchen & Dining', 'Bakeware', r'\b(?:cookie\s*cutters?|muffin\s*(?:tins?|pans?)|baking\s*(?:pans?|trays?|sheets?)|cake\s*pans?|bundt\s*pans?|silicone\s*molds?|cookie\s*molds?|pie\s*dishes?|casserole\s*dishes?)\b'),
    ('kitchen_tools', 'Kitchen & Dining', 'Kitchen Utensils & Tools', r'\b(?:kitchen\s*utensils?|spatulas?|whisks?|graters?|can\s*opener|chopsticks?|cutting\s*boards?|kitchen\s*tongs?|food\s*grinders?|bottle\s*openers?|measuring\s*cups?|measuring\s*spoons?)\b'),
    ('food_storage', 'Kitchen & Dining', 'Food Storage', r'\b(?:food\s*storage|tupperware|food\s*containers?|cookie\s*jars?|storage\s*canisters?|coffee\s*canisters?|cereal\s*containers?|cereal\s*storage|cake\s*taker|lunch\s*boxes?)\b'),
    ('table_linens', 'Kitchen & Dining', 'Kitchen & Table Linens', r'\b(?:table\s*runners?|table\s*cloths?|tablecloths?|placemats?|cloth\s*napkins?|kitchen\s*towels?|tea\s*towels?|dish\s*towels?)\b'),
    ('sheets', 'Bedding & Bath', 'Sheets & Pillowcases', r'\b(?:bed\s*sheets?|sheet\s*sets?|fitted\s*sheets?|flat\s*sheets?|pillowcases?|pillow\s*cases?)\b'),
    ('blankets', 'Bedding & Bath', 'Blankets & Comforters', r'\b(?:blankets?|comforters?|quilts?|duvet\s*(?:covers?|sets?)|throw\s*blankets?|bed\s*sets?)\b'),
    ('bath_towels', 'Bedding & Bath', 'Bath Towels', r'\b(?:bath\s*towels?|bath\s*sheets?|hand\s*towels?|washcloths?)\b'),
    ('bath_accessories', 'Bedding & Bath', 'Bathroom Accessories', r'\b(?:shower\s*(?:curtain|head|caddy|rod)|soap\s*dispenser|towel\s*(?:bar|rack|hook)|toilet\s*paper\s*holder|robe\s*hook|toilet\s*seat|bathroom\s*set)\b'),
    ('bins_baskets', 'Storage & Organization', 'Storage Bins & Baskets', r'\b(?:storage\s*(?:bins?|baskets?|boxes?)|stackable\s*(?:bins?|boxes?)|storage\s*containers?)\b'),
    ('closet', 'Storage & Organization', 'Closet Organizers', r'\b(?:closet\s*organizers?|closet\s*storage|clothes\s*hangers?|wooden\s*hangers?|garment\s*racks?|garment\s*bags?)\b'),
    ('jewelry_storage', 'Storage & Organization', 'Jewelry Storage', r'\b(?:jewelry\s*(?:boxes?|cases?|chests?|organizers?)|necklace\s*(?:organizers?|holders?|stands?)|ring\s*boxes?|watch\s*boxes?)\b'),
    ('shelves', 'Storage & Organization', 'Storage Shelves & Racks', r'\b(?:storage\s*shelves?|shelving\s*units?|storage\s*racks?|wire\s*shelving)\b'),
    ('sofa', 'Furniture', 'Sofa', r'\b(?:sofas?|couches?|loveseats?|sectional\s*sofas?)\b'),
    ('desk', 'Furniture', 'Desk', r'\b(?:standing\s*desk|office\s*desk|writing\s*desk|computer\s*desk|desks?)\b'),
    ('chair', 'Furniture', 'Chair', r'\b(?:office\s*chairs?|dining\s*chairs?|accent\s*chairs?|armchairs?|chairs?)\b'),
    ('dresser', 'Furniture', 'Dresser', r'\b(?:dressers?|chest\s*of\s*drawers?)\b'),
    ('bed_frame', 'Furniture', 'Bed Frame', r'\b(?:bed\s*frames?|platform\s*beds?)\b'),
    ('nightstand', 'Furniture', 'Nightstand', r'\b(?:nightstands?|bedside\s*tables?)\b'),
    ('table', 'Furniture', 'Table', r'\b(?:coffee\s*tables?|dining\s*tables?|side\s*tables?|end\s*tables?|accent\s*tables?)\b'),
    ('furniture_shelf', 'Furniture', 'Shelf & Storage Furniture', r'\b(?:bookshelves?|bookcases?|wall\s*shelves?|floating\s*shelves?|wall\s*racks?)\b'),
]
RULES = [(rid, cat, typ, re.compile(pat, re.IGNORECASE)) for rid, cat, typ, pat in RULES]

SEASONAL = re.compile(r'\b(?:ornaments?|wreaths?|garlands?|tree\s*toppers?|stockings?|snow\s*globes?|holiday\s*figurines?|christmas\s*village|holiday\s*decoration|seasonal\s*decor|halloween\s*decor|christmas\s*decor|easter\s*decor|trick\s*or\s*treat\s*(?:sign|decoration)|blow\s*molds?)\b', re.I)
RISK_PATTERNS = [
    ('possible_part_or_accessory', re.compile(r'\b(?:replacement|refill|filter\b|parts?\s*only|parts?\s*for|spare\s*parts?|power\s*cord|power\s*adapter|blades?\s*(?:only|replacement)|attachment|shade\s*only|cover\s*only|lid\s*only|supports?\s*(?:for|only)|wallpaper\s*sample)\b', re.I)),
    ('cover_or_accessory_not_whole_item', re.compile(r'\b(?:sofa\s*cover|couch\s*cover|sectional\s*cover|chair\s*cover|sofa\s*slipcover|slipcovers?|lamp\s*shade|mug\s*hat|mug\s*topper|cup\s*holder|book\s*ends?|bookends|chair\s*cushion|shoe\s*box|gift\s*box|dust\s*bag|drinking\s*straw\s*topper|tea\s*light\s*holder|tealight\s*holder|candle\s*lid|candle\s*snuffer|wick\s*trimmer|lunch\s*tote|cooler\s*bag)\b', re.I)),
    ('possibly_mixed_bundle', re.compile(r'\b(?:mixed\s*bundle|random\s*lot|mystery\s*(?:box|bundle)|assorted\s*items?|bundle\s*-|bundle\s*of\s*random)\b', re.I)),
    ('collectible_or_rare', re.compile(r'\b(?:rare|collectibles?|limited\s*edition|signed|autograph(?:ed)?|keepsake|retired|discontinued|vintage)\b', re.I)),
    ('visible_damage_or_condition_issue', re.compile(r'\b(?:broken|damaged|cracked|missing\s*(?:part|handle|lid)|not\s*working|for\s*parts)\b', re.I)),
    ('possibly_holder_not_object', re.compile(r'\b(?:candle\s*(?:[\w/-]+\s+){0,5}holders?|candle\s*/\s*soap\s*holder|candle\s*sleeve|candle\s*topper|quilt\s*rack|blanket\s*(?:rack|holder)|bowl\s*holder|stocking\s*holders?|mug\s*display|mug\s*holders?)\b', re.I)),
]
# Catch explicit non-home objects in very broad/erroneous source categories (manual review only).
NON_HOME = re.compile(r'\b(?:shoe\s*charm|necklace|earrings?|bracelets?|purses?|cosmetics?|tooth\s*whiten(?:ing|er)|video\s*games?|trading\s*cards?|action\s*figures?|phone\s*cases?)\b',re.I)

# Resolve ambiguities where one title refers to multiple distinct product kinds.
# These precise expressions are stronger than generic source category but NOT stronger than a flagged part.
DECOR_AS_FALLBACK = {'Seasonal decor', 'Home decor'}


def classify(row):
    title = (row.get('name') or '').strip()
    source1 = (row.get('c1_name') or '').strip()
    old_cat = (row.get('moveon_category') or '').strip()
    old_type = (row.get('moveon_item_type') or '').strip()
    risks = [name for name, rgx in RISK_PATTERNS if rgx.search(title)]
    if NON_HOME.search(title):
        risks.append('possible_non_home_item')
    # Most generic literal cues should not trigger when used as adjectives or for accessories.
    hits=[]
    for rid, cat, typ, pat in RULES:
        m=pat.search(title)
        if m:
            # A 'Halloween mug' also matches holiday *conceptually* but isn't a seasonal decoration.
            hits.append((rid,cat,typ,m.group(0)))
    by_type=defaultdict(list)
    for rid,cat,typ,matched in hits:
        by_type[(cat,typ)].append((rid,matched))

    # Rules that often match phrases nested in other product types.
    if ('Kitchen & Dining','Bottles & Tumblers') in by_type and ('Kitchen & Dining','Mugs & Cups') in by_type:
        # travel mugs belong in Bottles, not ordinary Mugs; otherwise ambiguous.
        if re.search(r'\btravel\s*mug\b',title,re.I) and not re.search(r'\b(?:ceramic|coffee\s*mug|tea\s*mug)\b',title,re.I):
            del by_type[('Kitchen & Dining','Mugs & Cups')]
    if ('Kitchen & Dining','Servingware') in by_type and ('Kitchen & Dining','Dinnerware') in by_type:
        # Serving bowl is not unequivocally one type; flag for review below.
        pass
    if ('Home Decor','Decorative Accessories') in by_type and ('Home Decor','Candles') in by_type:
        # candle holder is not a candle: keep holder, but remain conservative if also candle contents
        if re.search(r'\bcandle\s*holders?\b',title,re.I) and not re.search(r'\b(?:candle\s*set|scented\s*candle|with\s*candles?)\b',title,re.I):
            del by_type[('Home Decor','Candles')]
    if ('Appliances','Coffee & Espresso Machine') in by_type and ('Kitchen & Dining','Mugs & Cups') in by_type:
        # 'Coffee maker + mugs' is a multi-item bundle rather than an individual coffee machine.
        risks.append('mixed_machine_and_drinkware')
    if ('Furniture','Desk') in by_type and ('Home Decor','Lamp & Lighting') in by_type:
        # desk lamp is lighting not furniture
        if re.search(r'\bdesk\s*lamp\b',title,re.I):
            del by_type[('Furniture','Desk')]
    if ('Kitchen & Dining','Kitchen Appliance') in by_type:
        pass

    seasonal_hit = SEASONAL.search(title) if source1=='Seasonal decor' else None
    if not by_type and seasonal_hit:
        by_type[('Home Decor','Seasonal Decorations')].append(('seasonal_object',seasonal_hit.group(0)))

    # IMPORTANT: if obvious season-only items show no concrete keyword, don't auto-label them.
    matches = sorted(by_type.items(), key=lambda x:(x[0][0],x[0][1]))
    if len(matches)==1:
        (cat,typ), reasons=matches[0]
        rules=';'.join(dict.fromkeys(rid for rid,_ in reasons))
        cues='; '.join(dict.fromkeys(match for _,match in reasons))
        if risks:
            status='MANUAL_REVIEW'
            why='Title matches one type but contains a risk cue that needs verification.'
        elif len(title) < 6:
            status='MANUAL_REVIEW'
            why='Very short/ambiguous title.'
        else:
            status='AUTO_CANDIDATE'
            why='Concrete product keyword found; still requires sampled QC before model training.'
    elif len(matches)>1:
        cat=old_cat
        typ=old_type
        rules='multiple: '+ ';'.join(sorted(dict.fromkeys(rid for reasons in by_type.values() for rid,_ in reasons)))
        cues='; '.join(sorted(set(m for reasons in by_type.values() for _,m in reasons)))
        status='MANUAL_REVIEW'
        why='Multiple distinct product types matched; no forced classification.'
    else:
        cat=old_cat
        typ=old_type
        rules='none'
        cues=''
        status='MANUAL_REVIEW'
        why='No reliable specific product keyword; keep taxonomy suggestion unverified.'
    if 'possible_non_home_item' in risks and len(matches)==0:
        status='POSSIBLE_OUT_OF_SCOPE'
        why='Title may describe a non-home item; human review required before exclusion.'

    return {
        'proposed_moveon_category':cat,
        'proposed_moveon_item_type':typ,
        'title_review_status':status,
        'title_action': ('PROPOSE_RECLASSIFICATION' if status=='AUTO_CANDIDATE' and (cat,typ)!=(old_cat,old_type) else
                         'PROPOSE_CONFIRMATION' if status=='AUTO_CANDIDATE' else
                         'NEEDS_MANUAL_DECISION'),
        'title_rule_ids':rules,
        'title_matches':cues,
        'title_risk_flags':';'.join(dict.fromkeys(risks)),
        'title_review_note':why,
        'human_verified':'NO',
    }


def write_csv(path, rows, fields):
    with path.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore')
        w.writeheader()
        w.writerows(rows)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input',default=str(BASE_DIR/'preprocessing/output/mapping_v1_1/home_items_for_manual_review.csv'))
    p.add_argument('--output-dir',default=str(BASE_DIR/'preprocessing/output/title_refinement_v1'))
    args=p.parse_args()
    src=Path(args.input).expanduser()
    out=Path(args.output_dir).expanduser()
    out.mkdir(parents=True,exist_ok=True)
    with src.open(encoding='utf-8-sig',newline='') as f:
        rd=csv.DictReader(f)
        cols=list(rd.fieldnames or [])
        rows=list(rd)
    required={'item_id','name','c1_name','c2_name','moveon_category','moveon_item_type','effective_decision','stime'}
    if required-set(cols):
        raise SystemExit(f'Missing fields: {sorted(required-set(cols))}')
    if len({row['item_id'] for row in rows}) != len(rows):
        raise SystemExit('Duplicated item_id: input must be item-level.')
    if any(row['effective_decision']!='REVIEW' for row in rows):
        raise SystemExit('Input must contain REVIEW rows only; provide home_items_for_manual_review.csv.')
    enriched=[{**r,**classify(r)} for r in rows]
    extra=list(classify(rows[0]).keys()) if rows else []
    fields=cols+extra
    write_csv(out/'home_items_title_refined_review.csv',enriched,fields)
    for name, allowed in [
        ('title_auto_candidates.csv',{'AUTO_CANDIDATE'}),
        ('title_still_needs_review.csv',{'MANUAL_REVIEW','POSSIBLE_OUT_OF_SCOPE'}),
    ]:
        write_csv(out/name,[r for r in enriched if r['title_review_status'] in allowed],fields)
    ct=Counter(r['title_review_status'] for r in enriched)
    by_type=Counter((r['proposed_moveon_category'] or '(unassigned)',r['proposed_moveon_item_type'] or '(unassigned)',r['title_review_status']) for r in enriched)
    write_csv(out/'title_type_counts.csv',[
        {'moveon_category':cat,'moveon_item_type':typ,'title_review_status':s,'n_items':n}
        for (cat,typ,s),n in sorted(by_type.items(),key=lambda x:(-x[1],x[0]))],
        ['moveon_category','moveon_item_type','title_review_status','n_items'])
    by_rule=Counter((r['title_rule_ids'] or 'none',r['title_review_status']) for r in enriched)
    write_csv(out/'title_rule_counts.csv',[
        {'rule_id':rid,'status':s,'n_items':n}
        for (rid,s),n in sorted(by_rule.items(),key=lambda x:-x[1])],['rule_id','status','n_items'])
    # Deterministic QC sample: up to 6 per rule; also up to 20 flagged/uncertain examples.
    rng=random.Random(20261009)
    grouped=defaultdict(list)
    for r in enriched:
        if r['title_review_status']=='AUTO_CANDIDATE':
            grouped[r['title_rule_ids']].append(r)
    audit=[]
    for rule, sample_rows in sorted(grouped.items()):
        audit.extend(rng.sample(sample_rows,min(6,len(sample_rows))))
    amb=[r for r in enriched if r['title_review_status']!='AUTO_CANDIDATE']
    audit.extend(rng.sample(amb,min(24,len(amb))))
    audit.sort(key=lambda x:(x['title_review_status'],x['title_rule_ids'],x['item_id']))
    for row in audit:
        row.update({'reviewer_decision':'', 'reviewer_category':'', 'reviewer_item_type':'', 'reviewer_notes':''})
    audit_cols=['item_id','name','c1_name','c2_name','price','item_condition_name',
                'moveon_category','moveon_item_type',
                'proposed_moveon_category','proposed_moveon_item_type','title_review_status',
                'title_rule_ids','title_risk_flags','reviewer_decision','reviewer_category','reviewer_item_type','reviewer_notes']
    write_csv(out/'title_qc_sample.csv',audit,audit_cols)
    print(f'REVIEW items read: {len(rows):,}; unique item IDs: {len(set(r["item_id"] for r in rows)):,}')
    for status in ('AUTO_CANDIDATE','MANUAL_REVIEW','POSSIBLE_OUT_OF_SCOPE'):
        print(f' {status:22s}: {ct[status]:,}')
    print(' Auto-proposed reclassifications:',sum(r['title_action']=='PROPOSE_RECLASSIFICATION' for r in enriched))
    print(' Rule QC sample rows:',len(audit))
    print(' Outputs:',out)
    print('No final classification or training readiness assumed. No split performed.')

if __name__=='__main__':
    main()
