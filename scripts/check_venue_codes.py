#!/usr/bin/env python3
"""既存のレースデータから実際の会場コードを確認"""

import sqlite3
from pathlib import Path
from collections import Counter

db_path = Path("data/nankan.db")
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# races テーブルの venue_code を確認
cursor.execute("SELECT DISTINCT venue_code, COUNT(*) FROM races GROUP BY venue_code ORDER BY COUNT(*) DESC")
venue_stats = cursor.fetchall()

print("DB に保存されているレースの会場コード:")
for venue_code, count in venue_stats:
    print(f"  {venue_code}: {count} レース")

# race_id から venue_code を抽出（フォーマット: YYYYAANNRRNN）
cursor.execute("SELECT race_id FROM races LIMIT 10")
sample_races = cursor.fetchall()

print("\nサンプルレースID:")
for (race_id,) in sample_races[:5]:
    # フォーマット: 202645013108 = YYYY(2026) AA(45) NN(01) RR(31) NN(08)
    # 実は: YYYY AA NN RR NN みたいな構造かもしれない
    year = race_id[0:4]
    venue_from_id = race_id[4:6]
    print(f"  {race_id}: 年度={year}, 会場部分={venue_from_id}")

# race_id に含まれる会場コードを集計
cursor.execute("SELECT race_id FROM races")
all_race_ids = [row[0] for row in cursor.fetchall()]

venues_from_id = Counter([rid[4:6] for rid in all_race_ids])
print("\nレースIDから抽出した会場コード:")
for venue, count in venues_from_id.most_common():
    print(f"  {venue}: {count} レース")

print("\n【分析】")
print(f"DB のvenenue_code 列の値: {[v for v, _ in venue_stats]}")
print(f"レースID に含まれる会場コード: {list(venues_from_id.keys())}")
print("\n→ これらを settings.py の VENUE_CODES と比較して修正が必要かもしれません")

conn.close()
