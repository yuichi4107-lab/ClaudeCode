#!/usr/bin/env python3
"""レース一覧スクレイパーのデバッグ: 実際に何件取得できるか確認"""

from nankan_predictor.scraper.race_list import RaceListScraper
from nankan_predictor.config.settings import CACHE_DIR

scraper = RaceListScraper(use_cache=True, cache_dir=CACHE_DIR)

# 2023年1月のレースを取得
print("2023年1月のレースを取得中...")
race_ids_jan = scraper.get_race_ids_for_month(2023, 1)
print(f"  取得件数: {len(race_ids_jan)}")
if race_ids_jan:
    print(f"  例: {race_ids_jan[:3]}")

# 2023年2月のレースを取得
print("\n2023年2月のレースを取得中...")
race_ids_feb = scraper.get_race_ids_for_month(2023, 2)
print(f"  取得件数: {len(race_ids_feb)}")
if race_ids_feb:
    print(f"  例: {race_ids_feb[:3]}")

# 2023年全体の推定
print("\n【2023年全体の推定】")
total_2023 = 0
for month in range(1, 13):
    race_ids = scraper.get_race_ids_for_month(2023, month)
    total_2023 += len(race_ids)
    print(f"  2023年{month:2d}月: {len(race_ids):4d} レース")

print(f"\n2023年合計: {total_2023} レース")
print(f"期待値（250日×12レース）: 3,000 レース")
print(f"取得率: {total_2023 / 3000 * 100:.1f}%")

# パラメータを確認
print("\n【スクレイパーのURL パラメータ】")
print("  list=200 → 1ページあたり200件の制限がある可能性")
print("  → ページネーション実装が必要かもしれません")
