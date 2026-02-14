#!/usr/bin/env python3
"""NAR 最新レースの取得と DB 保存"""

import sys
sys.path.insert(0, '/app')

import logging
from nankan_predictor.scraper.nar_race_list import NARRaceListScraper, NARRaceDetailsScraper
from nankan_predictor.storage.nar_repository import NARRepository
from nankan_predictor.config.settings import DB_PATH

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def scrape_and_save_nar_races():
    """NAR 最新レースを取得して DB に保存"""
    
    list_scraper = NARRaceListScraper(use_cache=False)
    details_scraper = NARRaceDetailsScraper(use_cache=False)
    repository = NARRepository(db_path=DB_PATH)
    
    # NAR トップページから最新レースを取得
    print("【NAR レース取得開始】")
    race_ids = list_scraper.get_latest_races()
    
    if not race_ids:
        print("❌ NAR からレースを取得できませんでした")
        return
    
    print(f"✅ {len(race_ids)} 件のレースID を取得\n")
    
    saved_count = 0
    skipped_count = 0
    error_count = 0
    
    for i, race_id in enumerate(race_ids, 1):
        print(f"【処理中】 {i}/{len(race_ids)}: {race_id}")
        
        # レースが既に存在するかチェック
        if repository.check_race_exists(race_id):
            print(f"   ⏭️  スキップ（既存）\n")
            skipped_count += 1
            continue
        
        try:
            # 出走表情報を取得
            race_details = details_scraper.scrape_race_details(race_id)
            if not race_details.get('entries'):
                print(f"   ⚠️  出走馬情報が取得できませんでした")
                error_count += 1
                continue
            
            # 出走表を DB に保存
            repository.save_race_and_entries(race_details)
            
            # 結果情報を取得
            race_results = details_scraper.scrape_race_result(race_id)
            
            # 結果を DB に保存
            if race_results.get('results'):
                repository.save_race_results(race_results)
            
            # 出力
            print(f"   ✅ 保存完了")
            print(f"      日付: {race_details.get('race_date')}")
            print(f"      会場: {race_details.get('venue_name')}")
            print(f"      出走: {len(race_details.get('entries', []))} 頭")
            print(f"      結果: {len(race_results.get('results', []))} 件\n")
            
            saved_count += 1
            
        except Exception as e:
            print(f"   ❌ エラー: {e}\n")
            error_count += 1
            continue
    
    # 統計
    print(f"\n【取得完了】")
    print(f"  保存: {saved_count} レース")
    print(f"  スキップ: {skipped_count} レース（既存）")
    print(f"  エラー: {error_count} レース")
    print(f"  DB総数: {repository.get_race_count()} レース")

if __name__ == "__main__":
    scrape_and_save_nar_races()
