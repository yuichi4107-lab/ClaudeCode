#!/usr/bin/env python3
"""既存 DB レース（760件）の解析と NAR スクレイプ計画立案"""

import sys
sys.path.insert(0, '/app')

import sqlite3
from nankan_predictor.storage.database import get_connection
from nankan_predictor.config.settings import DB_PATH
from collections import Counter
from datetime import datetime

def analyze_existing_races():
    """既存 DB の760レースを分析"""
    
    conn = get_connection(DB_PATH)
    
    print("【既存DB レース分析】\n")
    
    # 1. 日付範囲
    cursor = conn.execute("""
        SELECT MIN(race_date), MAX(race_date), COUNT(*) 
        FROM races
    """)
    min_date, max_date, count = cursor.fetchone()
    print(f"✅ レース数: {count}")
    print(f"   日付範囲: {min_date} ～ {max_date}\n")
    
    # 2. 会場別集計
    print("✅ 会場別レース数:")
    cursor = conn.execute("""
        SELECT venue_code, venue_name, COUNT(*) as cnt
        FROM races
        GROUP BY venue_code
        ORDER BY cnt DESC
    """)
    for venue_code, venue_name, cnt in cursor.fetchall():
        print(f"   {venue_code} ({venue_name}): {cnt} レース")
    
    # 3. データの完全性
    print(f"\n✅ データ完全性確認:")
    
    # 出走馬数分布
    cursor = conn.execute("""
        SELECT race_id, field_size FROM races WHERE field_size IS NOT NULL
    """)
    field_sizes = [row[1] for row in cursor.fetchall()]
    print(f"   出走馬あり: {len(field_sizes)} レース")
    if field_sizes:
        print(f"   出走馬数（平均/中央値）: {sum(field_sizes)/len(field_sizes):.1f} / {sorted(field_sizes)[len(field_sizes)//2]}")
    
    # 結果データ
    cursor = conn.execute("""
        SELECT COUNT(DISTINCT race_id) FROM race_entries WHERE finish_position IS NOT NULL
    """)
    races_with_result = cursor.fetchone()[0]
    print(f"   結果あり: {races_with_result}/{count} レース ({races_with_result*100//count}%)")
    
    # 払戻データ
    cursor = conn.execute("""
        SELECT COUNT(DISTINCT race_id) FROM race_payouts
    """)
    races_with_payout = cursor.fetchone()[0]
    print(f"   払戻あり: {races_with_payout}/{count} レース ({races_with_payout*100//count}%)")
    
    # 4. NAR レースの判別
    print(f"\n✅ NAR レースの判別:")
    cursor = conn.execute("""
        SELECT venue_code, COUNT(*) FROM races GROUP BY venue_code
    """)
    for venue_code, cnt in cursor.fetchall():
        # NAR 会場コード（南関東 + 地方競馬）
        is_nar = venue_code in ['44', '45', '46', '47', '82', '83']  # NAR 会場
        print(f"   {venue_code}: NAR={is_nar}")
    
    # 5. 今後のスクレイプ計画
    print(f"\n【スクレイプ改善戦略】")
    print(f"1. 既存 760 レース → NAR から詳細情報再取得")
    print(f"   - 出走馬/騎手 ID の完全取得")
    print(f"   - 馬題/調教師情報の補完")
    print(f"   - 払戻データの補完（現在 {races_with_payout}/{count}）")
    print(f"")
    print(f"2. NAR トップページ動的リンク取得計画")
    print(f"   - Selenium で過去30日分のレース一覧を取得")
    print(f"   - 月別データの積み重ね（現在 763 → 目標 3000+）")
    print(f"")
    print(f"3. 優先順位")
    print(f"   高: 払戻データ補完 ({count - races_with_payout} レース)")
    print(f"   中: 馬/騎手 ID 取得 (feature engineering 用)")
    print(f"   低: 新規レース追加（月 30～50 レース）")
    
    conn.close()

if __name__ == "__main__":
    analyze_existing_races()
