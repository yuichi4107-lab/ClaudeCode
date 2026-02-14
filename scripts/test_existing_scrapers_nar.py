#!/usr/bin/env python3
"""既存スクレイパーの NAR 対応テスト"""

import sys
sys.path.insert(0, '/app')

from nankan_predictor.scraper.race_entry import RaceEntryScraper
from nankan_predictor.scraper.race_result import RaceResultScraper
from nankan_predictor.scraper.nar_race_list import NARRaceListScraper

def test_existing_scrapers():
    """既存スクレイパーが NAR に対応しているかテスト"""
    
    # NAR レースID を取得
    list_scraper = NARRaceListScraper(use_cache=False)
    race_ids = list_scraper.get_latest_races()
    
    if not race_ids:
        print("❌ NAR レースが取得できませんでした")
        return
    
    race_id = race_ids[0]
    print(f"✅ テスト対象レースID: {race_id}\n")
    
    # 既存 RaceEntryScraper でテスト
    print("【RaceEntryScraper テスト】")
    try:
        entry_scraper = RaceEntryScraper(use_cache=False)
        entries = entry_scraper.scrape(race_id)
        
        # 結果を確認
        print(f"✅ race_info: {entries.get('race_info', {}).get('race_id')}")
        print(f"   出走馬数: {len(entries.get('entries', []))}")
        
        if entries.get('entries'):
            entry = entries['entries'][0]
            print(f"   最初の出走馬: {entry.get('horse_name')} ({entry.get('jockey')})")
        
    except Exception as e:
        print(f"❌ エラー: {e}")
        import traceback
        traceback.print_exc()
    
    # 既存 RaceResultScraper でテスト
    print("\n【RaceResultScraper テスト】")
    try:
        result_scraper = RaceResultScraper(use_cache=False)
        results = result_scraper.scrape(race_id)
        
        print(f"✅ 結果取得成功")
        print(f"   着順数: {len(results.get('results', []))}")
        
        if results.get('results'):
            result = results['results'][0]
            print(f"   1着: {result.get('horse_name')} (タイム: {result.get('time')})")
        
    except Exception as e:
        print(f"❌ エラー: {e}")
        print(f"   (db.netkeiba.com に NAR データがないため失敗は予期される)")

if __name__ == "__main__":
    test_existing_scrapers()
