#!/usr/bin/env python3
"""既存 DB レースの払戻データ補完"""

import sys
sys.path.insert(0, '/app')

import logging
import sqlite3
from nankan_predictor.scraper.nar_race_list import NARRaceDetailsScraper
from nankan_predictor.storage.database import get_connection
from nankan_predictor.storage.nar_repository import NARRepository
from nankan_predictor.config.settings import DB_PATH

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def get_races_without_payouts():
    """払戻データがないレースIDを取得"""
    conn = get_connection(DB_PATH)
    cursor = conn.execute("""
        SELECT race_id, race_date FROM races
        WHERE race_id NOT IN (SELECT DISTINCT race_id FROM race_payouts)
        AND race_date >= '2023-01-01'
        ORDER BY race_date DESC
        LIMIT 50
    """)
    races = cursor.fetchall()
    conn.close()
    return races

def fill_missing_payouts():
    """払戻データがないレースについて NAR から取得して補完"""
    
    details_scraper = NARRaceDetailsScraper(use_cache=False)
    repository = NARRepository(db_path=DB_PATH)
    
    races = get_races_without_payouts()
    
    if not races:
        print("✅ すべてのレースに払戻データが存在します")
        return
    
    print(f"【払戻データ補完開始】")
    print(f"対象: {len(races)} レース\n")
    
    success_count = 0
    already_exist = 0
    error_count = 0
    
    for i, (race_id, race_date) in enumerate(races, 1):
        print(f"【{i}/{len(races)}】 {race_id} ({race_date})")
        
        try:
            # NAR から結果ページ（払戻情報）を取得
            # ただし、race_id が NAR 形式でない場合はスキップ
            if not race_id.isdigit() or len(race_id) != 12:
                print(f"   ⏭️  スキップ（ID形式が NAR 形式ではない）\n")
                continue
            
            # 既存の払戻データがあるかチェック
            conn = get_connection(DB_PATH)
            cursor = conn.execute(
                "SELECT COUNT(*) FROM race_payouts WHERE race_id = ?",
                (race_id,)
            )
            if cursor.fetchone()[0] > 0:
                print(f"   ⏭️  スキップ（既に払戻データが存在）\n")
                already_exist += 1
                conn.close()
                continue
            conn.close()
            
            # 結果ページから払戻情報を取得
            try:
                race_results = details_scraper.scrape_race_result(race_id)
                
                if not race_results.get('payouts'):
                    print(f"   ⚠️  払戻データが見つかりませんでした\n")
                    error_count += 1
                    continue
                
                # DB に保存
                repository.save_race_results(race_results)
                
                print(f"   ✅ 完了")
                print(f"      払戻レコード数: {len(race_results['payouts'])}\n")
                success_count += 1
                
            except Exception as inner_e:
                print(f"   ❌ スクレイプエラー: {inner_e}\n")
                error_count += 1
                continue
        
        except Exception as e:
            print(f"   ❌ エラー: {e}\n")
            error_count += 1
            continue
    
    # 統計
    print(f"\n【補完完了】")
    print(f"  成功: {success_count} レース")
    print(f"  既存: {already_exist} レース")
    print(f"  エラー: {error_count} レース")
    
    # 統計確認
    conn = get_connection(DB_PATH)
    cursor = conn.execute("""
        SELECT COUNT(DISTINCT race_id) FROM race_payouts
    """)
    total_with_payout = cursor.fetchone()[0]
    cursor = conn.execute("SELECT COUNT(*) FROM races")
    total_races = cursor.fetchone()[0]
    conn.close()
    
    print(f"  DB総数: {total_with_payout}/{total_races} レース ({total_with_payout*100//total_races}%)")

if __name__ == "__main__":
    fill_missing_payouts()
