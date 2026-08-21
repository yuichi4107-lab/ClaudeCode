# -*- coding: utf-8 -*-
import csv, json

CSV = r'G:\マイドライブ\YNFactory-cc\.company\outputs\ebooks-manga\manga-career-restart\vol4\panels\comicle_output.csv'
with open(CSV, encoding='utf-8') as f:
    rows = list(csv.DictReader(f))

# パネル別の文字数を確認（テキストページ除く）
panel_chars_list = []
for row in rows:
    if row['使用するコマ割りテンプレ'] == 'テキストページ': continue
    try:
        items = json.loads(row['コマ別テキストJSON'])
        pc = {}
        for it in items:
            p = it['panel_id']
            pc.setdefault(p, 0)
            pc[p] += len(it['text'])
        for p, chars in pc.items():
            panel_chars_list.append(chars)
    except: pass

# 分布確認
from collections import Counter
bins = [0, 5, 10, 15, 20, 25, 30, 35]
print('パネル文字数分布:')
for i in range(len(bins)-1):
    cnt = sum(1 for c in panel_chars_list if bins[i] <= c < bins[i+1])
    print('  {}-{}字: {}件'.format(bins[i], bins[i+1]-1, cnt))
cnt = sum(1 for c in panel_chars_list if c >= 30)
print('  30字以上: {}件'.format(cnt))
print('総パネル: {}件'.format(len(panel_chars_list)))
print('平均: {:.1f}字'.format(sum(panel_chars_list)/len(panel_chars_list) if panel_chars_list else 0))