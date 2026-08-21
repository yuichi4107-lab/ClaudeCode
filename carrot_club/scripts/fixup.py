# -*- coding: utf-8 -*-
import csv, json, re, sys
from scrape_results import get, search_dam, parse_horse

roster = {f"{r['year']}#{r['no']}": r for r in csv.DictReader(open('roster.csv', encoding='utf-8'))}
fix_keys = ['2020#62','2020#66','2020#81','2020#82','2021#47','2022#38','2022#39','2022#49','2022#84']

def sire_of(hid):
    html = get(f'https://db.netkeiba.com/horse/{hid}/')
    m = re.search(r'href="/horse/ped/[^"]+"[^>]*>', html)
    # blood table: first b_ml link is sire
    m = re.search(r'<td[^>]*rowspan="2"[^>]*class="b_ml"[^>]*>\s*<a href="/horse/(\w+)/?"[^>]*>([^<]+)', html)
    return m.group(2).strip() if m else ''

out = []
for key in fix_keys:
    r = roster[key]
    dam, born, sire = r['dam'].strip(), r['born'], r['sire'].strip()
    variants = [dam, dam.replace('Ⅱ','II'), dam.replace('Ⅱ',''), dam.replace('Ⅱ','2')]
    cands = []
    seen = set()
    for v in variants:
        try:
            for hid, nm in search_dam(v):
                if hid.startswith(born) and hid not in seen:
                    seen.add(hid); cands.append((hid, nm))
        except Exception as e:
            print(key, 'variant fail', v, e, flush=True)
    result = {'key': key, 'year': r['year'], 'no': r['no'], 'boshu_name': r['name'], 'dam': dam}
    picked = None
    for hid, nm in cands:
        s = sire_of(hid)
        print(key, 'cand', hid, nm, 'sire=', s, flush=True)
        if s and (s == sire or sire in s or s in sire):
            picked = hid; break
    if picked is None and len(cands) == 1:
        picked = cands[0][0]
    if picked:
        result.update(parse_horse(picked)); result['status'] = 'ok_fixup'
    else:
        result['status'] = 'not_found_final'
    out.append(result)
    print(key, '->', result.get('reg_name', 'NOT FOUND'), flush=True)

with open('results_fixup.jsonl', 'w', encoding='utf-8') as f:
    for o in out:
        f.write(json.dumps(o, ensure_ascii=False) + '\n')
print('fixup done')
