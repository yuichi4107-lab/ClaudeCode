# -*- coding: utf-8 -*-
import csv, json

CSV = r'G:\マイドライブ\YNFactory-cc\.company\outputs\ebooks-manga\manga-career-restart\vol4\panels\comicle_output.csv'
with open(CSV, encoding='utf-8') as f:
    rows = list(csv.DictReader(f))

over30_list = []
for row in rows:
    if row['使用するコマ割りテンプレ'] == 'テキストページ': continue
    j = row['コマ別テキストJSON']
    if j == '[]': continue
    items = json.loads(j)
    pc = {}
    for it in items:
        pid = it['panel_id']
        pc.setdefault(pid, 0)
        pc[pid] += len(it['text'])
    for pid, chars in pc.items():
        if chars > 30:
            panel_items = [x for x in items if x['panel_id'] == pid]
            all_text = ' / '.join(x['text'] for x in panel_items)
            over30_list.append('P{} コマ{}: {}字 | {}'.format(row['ページ番号'], pid, chars, all_text[:60]))

print('30字超過: {}件'.format(len(over30_list)))
for x in over30_list[:20]:
    print(x)