# -*- coding: utf-8 -*-
import csv, json, os, re, time, random, hashlib
import urllib.request, urllib.parse

BASE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(BASE, 'nk_cache'); os.makedirs(CACHE, exist_ok=True)
OUT = os.path.join(BASE, 'results.jsonl')
LOG = os.path.join(BASE, 'scrape.log')

def log(msg):
    with open(LOG, 'a') as f:
        f.write(f"{time.strftime('%H:%M:%S')} {msg}\n")

def get(url):
    key = hashlib.md5(url.encode()).hexdigest()
    path = os.path.join(CACHE, key + '.html')
    if os.path.exists(path):
        return open(path, encoding='utf-8').read()
    time.sleep(1.5 + random.random())
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
    for attempt in range(3):
        try:
            raw = urllib.request.urlopen(req, timeout=40).read()
            html = raw.decode('euc-jp', errors='replace')
            with open(path, 'w', encoding='utf-8') as f:
                f.write(html)
            return html
        except Exception as e:
            log(f"retry{attempt} {url} {e}")
            time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"failed {url}")

def search_dam(dam):
    params = {'pid': 'horse_list', 'mare': dam.encode('euc-jp'), 'list': '100'}
    url = 'https://db.netkeiba.com/?' + urllib.parse.urlencode(params)
    html = get(url)
    return re.findall(r'href="/horse/(\d+)/?"[^>]*>([^<]+)</a>', html)

def parse_horse(hid):
    html = get(f'https://db.netkeiba.com/horse/{hid}/')
    def field(label):
        m = re.search(re.escape(label) + r'</th>\s*<td[^>]*>(.*?)</td>', html, re.S)
        return re.sub(r'<[^>]+>', '', m.group(1)).strip() if m else ''
    title = ''
    m = re.search(r'<div class="horse_title">(.*?)</div>', html, re.S)
    if m:
        title = re.sub(r'<[^>]+>|\s+', ' ', m.group(1)).strip()
    namem = re.search(r'<title>([^|<]+)', html)
    name = namem.group(1).strip() if namem else ''
    rec = field('通算成績')
    starts = wins = None
    m = re.search(r'(\d+)戦(\d+)勝', rec)
    if m:
        starts, wins = int(m.group(1)), int(m.group(2))
    def money(label):
        v = field(label)
        m = re.search(r'([\d,\.]+)万円', v)
        return float(m.group(1).replace(',', '')) if m else 0.0
    return {
        'horse_id': hid, 'reg_name': name, 'title': title,
        'record': rec, 'starts': starts, 'wins': wins,
        'prize_jra': money('獲得賞金 (中央)'), 'prize_nar': money('獲得賞金 (地方)'),
        'main_wins': field('主な勝鞍'), 'owner': field('馬主'), 'trainer_now': field('調教師'),
        'birth_full': field('生年月日'),
    }

def main():
    roster = list(csv.DictReader(open(os.path.join(BASE, 'roster.csv'), encoding='utf-8')))
    done_keys = set()
    if os.path.exists(OUT):
        for line in open(OUT, encoding='utf-8'):
            try:
                done_keys.add(json.loads(line)['key'])
            except Exception:
                pass
    dam_cache = {}
    for i, r in enumerate(roster):
        key = f"{r['year']}#{r['no']}"
        if key in done_keys:
            continue
        dam, born = r['dam'].strip(), int(r['born'])
        out = {'key': key, 'year': r['year'], 'no': r['no'], 'boshu_name': r['name'], 'dam': dam, 'status': ''}
        try:
            if dam not in dam_cache:
                dam_cache[dam] = search_dam(dam)
            cands = [(hid, nm) for hid, nm in dam_cache[dam] if hid.startswith(str(born))]
            if not cands:
                out['status'] = 'not_found'
            else:
                if len(cands) > 1:
                    out['status'] = 'ambiguous:' + ';'.join(f"{h}:{n}" for h, n in cands)
                hid = cands[0][0]
                out.update(parse_horse(hid))
                if not out['status']:
                    out['status'] = 'ok'
        except Exception as e:
            out['status'] = f'error:{e}'
        with open(OUT, 'a', encoding='utf-8') as f:
            f.write(json.dumps(out, ensure_ascii=False) + '\n')
        if (i + 1) % 10 == 0:
            log(f"progress {i+1}/{len(roster)}")
    log('DONE')

if __name__ == '__main__':
    main()
