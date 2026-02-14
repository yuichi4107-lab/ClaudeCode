#!/usr/bin/env python3
"""HTML構造を確認して払戻金セレクタを修正"""

from bs4 import BeautifulSoup
from nankan_predictor.scraper.base import BaseScraper

scraper = BaseScraper()

# サンプルレース
race_id = "202644012901"
url = f"https://db.netkeiba.com/race/{race_id}/"

print(f"Fetching {url}...")
html = scraper.get(url)

if not html:
    print("Failed to fetch HTML")
    exit(1)

# Save HTML to file for inspection
with open(f"d:\\debug_race_{race_id}.html", "w", encoding="utf-8") as f:
    f.write(html)
print(f"Saved to debug_race_{race_id}.html")

soup = BeautifulSoup(html, "lxml")

# Find all tables
tables = soup.find_all("table")
print(f"\nFound {len(tables)} tables")

# Look for tables containing "払戻" or "馬単"
print("\nSearching for payout-related tables...")
for i, table in enumerate(tables):
    text = table.get_text()
    if "払戻" in text or "馬単" in text or "単勝" in text:
        print(f"\nTable {i}: contains payout/exacta/win info")
        print(f"  Classes: {table.get('class', [])}")
        print(f"  First 200 chars: {text[:200]}")

# Look for any div/section with "pay" keyword
print("\n\nSearching for pay-related divs/sections...")
for elem in soup.find_all(class_=True):
    classes = " ".join(elem.get("class", []))
    if "pay" in classes.lower() or "payout" in classes.lower():
        print(f"Found element with class '{classes}': {elem.get_text()[:100]}")
