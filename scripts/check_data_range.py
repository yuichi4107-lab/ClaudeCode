#!/usr/bin/env python3
"""DB に保存されているデータの日付範囲を確認"""

import sqlite3
from pathlib import Path
from datetime import datetime

# DB パス
db_path = Path("data/nankan.db")
if not db_path.exists():
    print(f"Error: Database not found at {db_path}")
    exit(1)

conn = sqlite3.connect(db_path)
cursor = conn.cursor()

try:
    # race テーブルの日付範囲を確認
    cursor.execute("SELECT MIN(race_date) as min_date, MAX(race_date) as max_date, COUNT(*) as count FROM races")
    result = cursor.fetchone()
    if result:
        min_date, max_date, count = result
        print("=" * 80)
        print("DB の データ取得期間")
        print("=" * 80)
        print(f"\n【race テーブル】")
        print(f"  最古のレース日付: {min_date}")
        print(f"  最新のレース日付: {max_date}")
        print(f"  レース総数:      {count:,} 件")
        
        # 期間を計算
        if min_date and max_date:
            min_dt = datetime.strptime(min_date[:10], "%Y-%m-%d")
            max_dt = datetime.strptime(max_date[:10], "%Y-%m-%d")
            days = (max_dt - min_dt).days
            years = days / 365.25
            print(f"  取得期間:       {days:,} 日間 ({years:.2f} 年間)")
    
    # entries テーブルの統計
    cursor.execute("SELECT COUNT(*) as count FROM race_entries")
    entries_count = cursor.fetchone()[0]
    print(f"\n【race_entries テーブル】")
    print(f"  入馬総数: {entries_count:,} 件")
    
    # payouts テーブルの統計
    cursor.execute("SELECT COUNT(*) as count FROM race_payouts")
    payouts_count = cursor.fetchone()[0]
    print(f"\n【race_payouts テーブル】")
    print(f"  馬単払戻データ: {payouts_count:,} 件")
    
    # horse_history テーブルの統計
    cursor.execute("SELECT COUNT(DISTINCT horse_id) as count FROM horse_history_cache")
    horses_count = cursor.fetchone()[0]
    print(f"\n【horse_history テーブル】")
    print(f"  登録済み馬: {horses_count:,} 頭")
    
    # テーブル一覧の確認
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [row[0] for row in cursor.fetchall()]
    print(f"\n【テーブル一覧】")
    for table in sorted(tables):
        cursor.execute(f"SELECT COUNT(*) FROM {table}")
        count = cursor.fetchone()[0]
        print(f"  {table:.<40} {count:>10,} 行")
    
    print("\n" + "=" * 80)
    
finally:
    conn.close()
