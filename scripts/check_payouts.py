#!/usr/bin/env python3
"""DB内の払戻金データの状態を確認"""

import sqlite3
from nankan_predictor.config.settings import DB_PATH

def check_payouts():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    
    # テーブル確認
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [row[0] for row in cur.fetchall()]
    print(f"Tables in DB: {tables}")
    
    # race_payouts テーブルの行数
    try:
        cur.execute("SELECT COUNT(*) FROM race_payouts")
        count = cur.fetchone()[0]
        print(f"\nrace_payouts table rows: {count}")
    except Exception as e:
        print(f"Error querying race_payouts: {e}")
        return
    
    if count == 0:
        print("WARNING: race_payouts table is empty!")
        print("\nChecking races table...")
        cur.execute("SELECT COUNT(*) FROM races")
        races_count = cur.fetchone()[0]
        print(f"races table rows: {races_count}")
        
        if races_count > 0:
            cur.execute("SELECT race_id, race_date FROM races LIMIT 5")
            print("Sample races:")
            for row in cur.fetchall():
                print(f"  {row['race_id']} ({row['race_date']})")
    else:
        print("\nSample payouts:")
        cur.execute("SELECT race_id, bet_type, combination, payout FROM race_payouts LIMIT 5")
        for row in cur.fetchall():
            print(f"  {row['race_id']} {row['bet_type']} {row['combination']} → {row['payout']}")
        
        # 最新のpayoutを確認
        print("\nLatest payouts:")
        cur.execute("""
            SELECT r.race_date, rp.bet_type, COUNT(*) as cnt
            FROM race_payouts rp
            JOIN races r ON rp.race_id = r.race_id
            GROUP BY r.race_date, rp.bet_type
            ORDER BY r.race_date DESC
            LIMIT 10
        """)
        for row in cur.fetchall():
            print(f"  {row['race_date']} {row['bet_type']}: {row['cnt']} combos")
    
    conn.close()

if __name__ == "__main__":
    check_payouts()
