#!/usr/bin/env python3
"""スクレイパーのpayouts抽出をステップごとにデバッグ"""

from bs4 import BeautifulSoup
from nankan_predictor.scraper.base import BaseScraper
import re

scraper = BaseScraper()
race_id = "202644012901"
url = f"https://db.netkeiba.com/race/{race_id}/"

print(f"Fetching {url}...")
html = scraper.get(url)
soup = BeautifulSoup(html, "lxml")

# テーブルを検索
tables = soup.select("table.pay_table_01")
print(f"Found {len(tables)} pay_table_01 tables\n")

for t_idx, table in enumerate(tables):
    print(f"=== Table {t_idx} ===")
    rows = table.select("tr")
    print(f"Rows in table: {len(rows)}")
    
    for r_idx, tr in enumerate(rows):
        cells = tr.select("td, th")
        print(f"\n  Row {r_idx}: {len(cells)} cells")
        
        for c_idx, cell in enumerate(cells):
            text = cell.get_text(strip=True)
            print(f"    Cell {c_idx}: '{text}'")
        
        # パース試行
        if len(cells) >= 3:
            bet_type_text = cells[0].get_text(strip=True)
            combo_text = cells[1].get_text(strip=True)
            amount_text = cells[2].get_text(strip=True)
            
            print(f"  → bet_type:'{bet_type_text}' combo:'{combo_text}' amount:'{amount_text}'")
            
            if "馬単" in bet_type_text or "単勝" in bet_type_text:
                combo_m = re.search(r"(\d+)[→\-]+(\d+)", combo_text)
                amount_m = re.search(r"([\d,]+)", amount_text)
                
                if combo_m:
                    print(f"    → Combo matched: {combo_m.group(1)}-{combo_m.group(2)}")
                else:
                    print(f"    → Combo NOT matched")
                
                if amount_m:
                    print(f"    → Amount matched: {amount_m.group(1)}")
                else:
                    print(f"    → Amount NOT matched")
