#!/usr/bin/env python3
"""NAR 詳細スクレイパーの動作確認"""

import sys
sys.path.insert(0, '/app')

from nankan_predictor.scraper.nar_race_list import NARRaceListScraper, NARRaceDetailsScraper
import json

def test_nar_scraper():
    """NAR スクレイパーの動作確認"""
    
    # リスト取得
    print("【ステップ1: レース ID 取得】")
    list_scraper = NARRaceListScraper(use_cache=False)
    race_ids = list_scraper.get_latest_races()
    
    if not race_ids:
        print("❌ レースが取得できませんでした")
        return
    
    print(f"✅ {len(race_ids)} 件のレースID を取得")
    race_id = race_ids[0]
    print(f"   テスト対象: {race_id}\n")
    
    # 詳細スクレイピング
    print("【ステップ2: 出走表情報取得】")
    details_scraper = NARRaceDetailsScraper(use_cache=False)
    
    try:
        details = details_scraper.scrape_race_details(race_id)
        
        print(f"✅ レースID: {details['race_id']}")
        print(f"   日付: {details['race_date']}")
        print(f"   レース名: {details['race_name']}")
        print(f"   出走馬数: {len(details['entries'])}")
        
        if details['entries']:
            entry = details['entries'][0]
            print(f"   最初の出走馬:")
            for key, value in entry.items():
                print(f"      {key}: {value}")
        
    except Exception as e:
        print(f"❌ 詳細取得エラー: {e}")
        import traceback
        traceback.print_exc()
    
    # 結果スクレイピング
    print(f"\n【ステップ3: 結果情報取得】")
    
    try:
        result = details_scraper.scrape_race_result(race_id)
        
        print(f"✅ レースID: {result['race_id']}")
        print(f"   着順情報数: {len(result['results'])}")
        
        if result['results']:
            first_result = result['results'][0]
            print(f"   1着馬:")
            for key, value in first_result.items():
                print(f"      {key}: {value}")
        
        print(f"   払戻件数: {len(result['payouts'])}")
        if result['payouts']:
            payouts_sample = list(result['payouts'].items())[:3]
            print(f"   払戻サンプル:")
            for key, value in payouts_sample:
                print(f"      {key}: {value}")
        
    except Exception as e:
        print(f"❌ 結果取得エラー: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_nar_scraper()
