#!/usr/bin/env python3
"""NAR レースID形式を分析"""

import re
import requests
from bs4 import BeautifulSoup
from datetime import datetime

# NARトップページからレースIDを抽出
headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
resp = requests.get("https://nar.netkeiba.com/", headers=headers, timeout=10)
race_ids = set(re.findall(r'race_id=(\d{12})', resp.text))

print(f"取得したレースID: {len(race_ids)} 個")
if race_ids:
    ids_sorted = sorted(list(race_ids))
    print(f"サンプル: {ids_sorted[:5]}")
    
    # レースIDのフォーマットを分析
    print("\nレースID フォーマット分析:")
    print("=" * 80)
    
    for rid in sorted(list(race_ids))[:3]:
        print(f"\nレースID: {rid}")
        
        # 既存DBの仮説（YYYYAANNRRNN）
        # 新しい仮説を試す
        
        # パターン1: YYYY-AANNRRNN または YYYYAA-NNRRNN
        year = rid[0:4]
        
        # 日付を特定（ネットケイバ形式を逆算）
        # 202655021404: 2026年？
        # 01 = January-ish?
        # 2026-02-14 らしいので...
        # 2026 55 02 14 04?
        
        print(f"  年: {year}")
        
        # リバースエンジニアリング: 2026-02-14 から 202655021404を作ると
        # ここはもっと詳しい情報がいりますね
        
        # 試しに別パターン: YYYY（年）+ month(01-12) + ...
        test_patterns = [
            ("YYYY+MM+DD+...", f"{rid[0:4]}-{rid[4:6]}-{rid[6:8]}"),
            ("YYYY+????+...", f"{rid[0:4]}-{rid[4:8]}-{rid[8:12]}"),
        ]
        
        for pattern, potential_date in test_patterns:
            print(f"  {pattern}: {potential_date}")

# もっと詳しく調べるため、NAR の月別ページを探索
print("\n" + "=" * 80)
print("別アプローチ: NAR API または月別ページを探索")

# NAR のOdds APIを試す（一般的なパターン）
test_urls = [
    "https://nar.netkeiba.com/odds/",
    "https://nar.netkeiba.com/race/list/2026/02/",
    "https://nar.netkeiba.com/race/list/",
]

for test_url in test_urls:
    try:
        r = requests.head(test_url, timeout=5)
        print(f"  {test_url}: {r.status_code}")
    except:
        print(f"  {test_url}: 接続失敗")

print("\n💡 次のステップ: NetkeibaPythonライブラリの確認またはSeleniumでの動的取得")
