#!/usr/bin/env python3
"""NAR トップページを詳しく解析"""

import requests
from bs4 import BeautifulSoup
import re

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

url = "https://nar.netkeiba.com/"
print(f"取得中: {url}")

try:
    resp = requests.get(url, headers=headers, timeout=10)
    print(f"ステータス: {resp.status_code}\n")
    
    soup = BeautifulSoup(resp.text, "html.parser")
    
    # タイトルを表示（エンコーディング確認）
    title = soup.find("title")
    if title:
        print(f"タイトル: {title.text}\n")
    
    # リンク一覧を抽出
    print("ページ内のリンク（最初の30個）:")
    print("=" * 80)
    links = soup.find_all("a", href=True)
    
    race_links = []
    month_links = []
    
    for link in links[:50]:
        href = link.get("href", "")
        text = link.get_text(strip=True)[:30]
        
        if "/race/" in href:
            race_links.append((href, text))
            print(f"  [RACE] {href:.<50} {text}")
        elif "/month/" in href or "/schedule/" in href:
            month_links.append((href, text))
            print(f"  [MONTH] {href:.<50} {text}")
    
    print(f"\n合計リンク数: {len(links)}")
    print(f"レースリンク: {len(race_links)} 個")
    print(f"月別リンク: {len(month_links)} 個")
    
    # テーブルを探す
    print("\n" + "=" * 80)
    print("テーブル内容:")
    tables = soup.find_all("table")
    print(f"テーブル数: {len(tables)}")
    
    if tables:
        table = tables[0]
        rows = table.find_all("tr")
        print(f"最初のテーブルの行数: {len(rows)}")
        
        # 最初の3行を表示
        for i, row in enumerate(rows[:3]):
            cells = row.find_all(["td", "th"])
            print(f"\n行{i}: {len(cells)} 列")
            for j, cell in enumerate(cells[:3]):
                text = cell.get_text(strip=True)[:40]
                link = cell.find("a")
                if link:
                    href = link.get("href", "")
                    print(f"  列{j}: {text}... → {href}")
                else:
                    print(f"  列{j}: {text}...")
    
    # JavaScriptで動的に生成されているかを確認
    if "javascript" in resp.text.lower() or "react" in resp.text.lower():
        print("\n⚠️ このページはJavaScriptで動的に生成されている可能性があります")
        print("   → Seleniumなどの動的スクレイピングが必要")
    
    # ファイルに保存
    with open("data/debug_nar_top.html", "w", encoding="utf-8", errors="ignore") as f:
        f.write(resp.text)
    print("\nHTMLを保存: data/debug_nar_top.html")

except Exception as e:
    print(f"エラー: {e}")
