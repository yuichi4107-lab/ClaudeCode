#!/usr/bin/env python3
"""NAR（地方競馬統一）ページからレース一覧を取得してみる"""

import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import re

# NAR の南関東レース検索ページ
# https://nar.netkeiba.com/race/top.html などを探索

urls_to_test = [
    # NAR トップページ
    "https://nar.netkeiba.com/",
    
    # NAR レースノート
    "https://nar.netkeiba.com/race/top.html",
    
    # NAR データベース検索
    "https://nar.netkeiba.com/db/race/",
    
    # 月別検索（試例：2026年2月）
    "https://nar.netkeiba.com/race/month/2026/2/",
    
    # 別形式
    "https://nar.netkeiba.com/race/shutuba.html",
]

print("NAR ページにアクセス可能性を確認:")
print("=" * 80)

for url in urls_to_test:
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        resp = requests.get(url, headers=headers, timeout=10)
        print(f"\n{url}")
        print(f"  ステータス: {resp.status_code}")
        print(f"  サイズ: {len(resp.text)} bytes")
        
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "lxml")
            
            # レースリンクを探す
            race_links = resp.text.count("/race/")
            print(f"  /race/ を含む行数: {race_links}")
            
            # テーブルを探す
            tables = soup.find_all("table")
            print(f"  テーブル数: {len(tables)}")
            
            # タイトルを取得
            title = soup.find("title")
            if title:
                print(f"  ページタイトル: {title.text[:60]}")
    
    except Exception as e:
        print(f"\n{url}")
        print(f"  エラー: {str(e)[:80]}")

print("\n" + "=" * 80)
print("\n南関東4競馬場（浦和45・船橋46・大井47・川崎48）のいずれかで")
print("レースが出ているページを特定したら、そこからスクレイパーを作成します")
