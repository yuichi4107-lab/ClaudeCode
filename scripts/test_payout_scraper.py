#!/usr/bin/env python3
"""スクレイパーの払戻金抽出テスト"""

from nankan_predictor.scraper.race_result import RaceResultScraper

# サンプルレース（最近のレース）
test_races = [
    "202644012901",  # 診断で使ったレース
    "202447123103",  # 2024年最後
]

scraper = RaceResultScraper()

for race_id in test_races:
    print(f"\n=== Testing race {race_id} ===")
    try:
        result = scraper.scrape(race_id)
        payouts = result.get("payouts", [])
        print(f"Payouts found: {len(payouts)}")
        if payouts:
            for p in payouts[:3]:
                print(f"  {p['bet_type']}: {p['combination']} → {p['payout']}")
        else:
            print("  (No payouts found)")
    except Exception as e:
        print(f"Error: {e}")
