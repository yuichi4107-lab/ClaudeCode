# -*- coding: utf-8 -*-
import csv, json, re, urllib.parse
from scrape_results import get, parse_horse

def parse_search(dam):
    params = {'pid':'horse_list','mare':dam.encode('euc-jp'),'list':'100'}
    url = 'https://db.netkeiba.com/?' + urllib.parse.urlencode(params)
    html = get(url)
    rows = []
    for m in re.finditer(
        r'<a href="/horse/(\d+)/?" title="([^"]+)">.*?sire=[^"]*" title="([^"]+)".*?mare=[^"]*" title="([^"]+)"',
        html, re.S):
        rows.append({'id':m.group(1),'name':m.group(2),'sire':m.group(3),'dam':m.group(4)})
    return rows

def norm(s):
    return (s or '').strip().replace('　','')

roster = list(csv.DictReader(open('roster.csv', encoding='utf-8')))
out = []
need_fetch = []
for r in roster:
    key = f"{r['year']}#{r['no']}"
    dam, born, sire = norm(r['dam']), r['born'], norm(r['sire'])
    variants = [dam]
    if 'Ⅱ' in dam:
        variants = [dam.replace('Ⅱ','II'), dam.replace('Ⅱ','')]
    rows = []
    seen = set()
    for v in variants:
        try:
            for row in parse_search(v):
                if row['id'] not in seen:
                    seen.add(row['id']); rows.append(row)
        except Exception as e:
            pass
    # match: born year + sire + dam exact
    cands = [row for row in rows if row['id'].startswith(born)]
    exact = [row for row in cands if norm(row['sire']) == sire and norm(row['dam']).replace('II','Ⅱ') in (dam, dam.replace('Ⅱ',''), dam.replace('Ⅱ','II'))]
    if not exact:
        exact = [row for row in cands if norm(row['sire']) == sire]
    o = {'key':key}
    if len(exact) == 1:
        o['match_id'] = exact[0]['id']; o['match_name'] = exact[0]['name']; o['match_status'] = 'ok'
    elif len(exact) > 1:
        o['match_status'] = 'multi:' + ';'.join(x['id'] for x in exact)
    else:
        o['match_status'] = 'none' + ('' if not cands else ':sire_mismatch:' + ';'.join(f"{x['name']}({x['sire']})" for x in cands[:3]))
    out.append(o)

json.dump(out, open('match2.json','w',encoding='utf-8'), ensure_ascii=False)
from collections import Counter
print(Counter(o['match_status'].split(':')[0] for o in out))
for o in out:
    if o['match_status'] != 'ok':
        print(o['key'], o['match_status'][:120])
