# -*- coding: utf-8 -*-
import json, re, urllib.parse
from scrape_results import get
from dams2026 import dams

def mare_rows(w):
    q = urllib.parse.quote(w.encode('euc-jp', errors='replace'))
    html = get(f'https://db.netkeiba.com/?pid=horse_list&mare={q}&list=100')
    return re.findall(r'<a href="/horse/([0-9a-zA-Z]+)/?" title="([^"]+)">[^<]*</a>', html)

def dam_from_ped(hid):
    html = get(f'https://db.netkeiba.com/horse/ped/{hid}/')
    m = re.search(r'<td[^>]*rowspan="16"[^>]*class="b_fml"[^>]*>(.*?)</td>', html, re.S)
    if not m: return None
    blk = m.group(1)
    a = re.search(r'href="[^"]*/horse/([0-9a-zA-Z]+)/"[^>]*>\s*([^<\r\n]+)', blk)
    y = re.search(r'<br\s*/?>\s*(\d{4})', blk)
    return {'id': a.group(1), 'name': a.group(2).strip(), 'born': int(y.group(1))} if a and y else None

def count_offspring(dam_id):
    html = get(f'https://db.netkeiba.com/horse/mare/{dam_id}/')
    years = []
    for m in re.finditer(r'<a href="/horse/([0-9a-zA-Z]+)/?" title="[^"]*"', html):
        i = m.group(1)
        if i[:4].isdigit(): years.append(int(i[:4]))
        else: years.append(0)  # 外国産まれ=2025以前扱い
    return years

old = json.load(open('dams2026_v2.json', encoding='utf-8'))
out = {}
for d in dams:
    variants = [d] if 'Ⅱ' not in d else [d.replace('Ⅱ','II'), d.replace('Ⅱ','')]
    rows = []
    for v in variants:
        try:
            rows = mare_rows(v)
            if rows: break
        except Exception: pass
    if not rows:
        v2 = old.get(d, {})
        out[d] = {'dam_born': v2.get('dam_born'), 'dam_age': v2.get('dam_age'),
                  'ordinal': 1 if v2.get('dam_born') else None, 'method': 'word検索のみ(産駒登録なし→初仔扱い)'}
        print(d, out[d], flush=True); continue
    foal25 = [r for r in rows if 'の2025' in r[1]]
    numeric = sorted([r for r in rows if r[0][:4].isdigit()], key=lambda r: r[0])
    target = foal25[0] if foal25 else (numeric[-1] if numeric else rows[0])
    info = dam_from_ped(target[0])
    if not info:
        out[d] = {'dam_born': None, 'dam_age': None, 'ordinal': None, 'method': 'ped解析失敗'}
        print(d, out[d], flush=True); continue
    try:
        years = count_offspring(info['id'])
        n_before = len([y for y in years if y <= 2024])
        ordinal = n_before + 1
        method = 'mare_id産駒一覧'
    except Exception as e:
        ordinal = None; method = f'mare页失敗:{e}'
    out[d] = {'dam_id': info['id'], 'dam_born': info['born'], 'dam_age': 2025 - info['born'],
              'ordinal': ordinal, 'method': method}
    print(d, out[d], flush=True)
json.dump(out, open('dams2026_v3.json','w',encoding='utf-8'), ensure_ascii=False)
print('V3 DONE')
