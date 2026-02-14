#!/usr/bin/env python3
"""DB テーブル一覧を確認"""

import sqlite3
from pathlib import Path

db_path = Path("data/nankan.db")
if not db_path.exists():
    print(f"Error: Database not found at {db_path}")
    exit(1)

conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# テーブル一覧
cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = [row[0] for row in cursor.fetchall()]

print("DB に存在するテーブル:")
for table in sorted(tables):
    cursor.execute(f"SELECT COUNT(*) FROM {table}")
    count = cursor.fetchone()[0]
    print(f"  {table:.<40} {count:>10,} 行")

# schema を確認する
print("\n" + "=" * 80)
for table in sorted(tables):
    print(f"\nテーブル: {table}")
    cursor.execute(f"PRAGMA table_info({table})")
    cols = cursor.fetchall()
    for col in cols[:5]:  # 最初の5列だけ表示
        print(f"  {col[1]} ({col[2]})")
    if len(cols) > 5:
        print(f"  ... 他 {len(cols) - 5} 列")

conn.close()
