#!/usr/bin/env python3
"""レース一覧HTML の実際のレースリンククパターンを調査"""

from pathlib import Path
import re

html_file = Path("data/debug_race_list_2023_01.html")
with open(html_file, "r", encoding="euc-jp", errors="ignore") as f:
    html = f.read()

# テーブルを抽出
table_start = html.find("<table")
if table_start == -1:
    print("テーブルが見つかりません")
    exit(1)

table_end = html.find("</table>", table_start) + len("</table>")
table_html = html[table_start:table_end]

# テーブル内のリンクパターンを探す
links = re.findall(r'href="([^"]*)"', table_html)
print(f"テーブル内のリンク数: {len(links)}")
print("\n最初の10個のリンク:")
for link in links[:10]:
    print(f"  {link}")

# /race/ を含むリンク
race_links = [l for l in links if '/race/' in l]
print(f"\n/race/ を含むリンク: {len(race_links)} 件")
if race_links:
    print("例:")
    for link in race_links[:5]:
        print(f"  {link}")

# その他のパターンを探す
print("\n【パターン分析】")
for pattern, desc in [
    (r'/race/\d{12}/', "/race/12桁番号/ パターン"),
    (r'race_id=\d+', "race_id=数字 パターン"),
    (r'\?race_id=', "?race_id= パターン"),
    (r'/horse/', "/horse/ マスタ"),
]:
    matches = re.findall(pattern, html)
    print(f"  {desc}: {len(matches)} 件")

# テーブル内容をもっと詳しく表示
print("\n【テーブル内の<tr>（最初の3行）】")
rows = re.findall(r"<tr[^>]*>.*?</tr>", table_html[:3000], re.DOTALL)
for i, row in enumerate(rows[:3]):
    # 短縮版を表示
    cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.DOTALL)
    print(f"\n行{i+1}: {len(cells)} 列")
    for j, cell in enumerate(cells[:3]):
        # HTMLタグを削除
        text = re.sub(r"<[^>]*>", "", cell).strip()[:50]
        links_in_cell = re.findall(r'href="([^"]*)"', cell)
        if links_in_cell:
            print(f"  列{j+1}: {text}... → {links_in_cell[0]}")
        else:
            print(f"  列{j+1}: {text}...")
