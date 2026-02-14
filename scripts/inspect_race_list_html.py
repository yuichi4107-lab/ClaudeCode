#!/usr/bin/env python3
"""スクレイプされたレース一覧HTMLを確認"""

from nankan_predictor.scraper.race_list import RaceListScraper
from nankan_predictor.config.settings import CACHE_DIR
from pathlib import Path

scraper = RaceListScraper(use_cache=True, cache_dir=CACHE_DIR)

# 2023年1月のHTMLを取得
print("2023年1月のレース一覧HTMLを取得中...")
html = scraper.get("https://db.netkeiba.com/?pid=race_list&start_year=2023&start_mon=1&end_year=2023&end_mon=1&list=200&jyo[]=01&jyo[]=02&jyo[]=03&jyo[]=04")

# HTMLサイズを確認
print(f"HTML サイズ: {len(html)} bytes")

# レースリンク数を確認
import re
race_links = re.findall(r'/race/\d{12}/', html)
print(f"レースリンク数: {len(race_links)}")

# 最初の5リンクを表示
print(f"最初のレースリンク:")
for link in race_links[:5]:
    print(f"  {link}")

# URlパラメータの確認
print(f"\n【URL パラメータの解析】")
print(f"  list=200 が指定されているが、取得は20件程度")
print(f"  → list パラメータの意味が異なるか、ページネーションが必要な可能性")

# HTMLの一部を表示（テーブル行の確認）
import re
if "<table" in html:
    table_start = html.find("<table")
    table_end = html.find("</table>", table_start) + len("</table>")
    table_html = html[table_start:table_end]
    rows = len(re.findall(r"<tr", table_html))
    print(f"\n【テーブル内容】")
    print(f"  <table> 内の行数: {rows}")
else:
    print(f"\n【WARNING】 <table> が見つかりません")

# save HTML for manual inspection if needed
output_file = Path("data/debug_race_list_2023_01.html")
with open(output_file, "w", encoding="utf-8") as f:
    f.write(html)
print(f"\nHTMLを保存: {output_file}")
