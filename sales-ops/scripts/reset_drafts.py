"""壊れたDMドラフトを破棄し、対象企業をnewに戻す（ワンショット運用スクリプト）。"""
import os
import sqlite3
import sys
from pathlib import Path

DB_PATH = Path(os.environ.get("SALES_OPS_DB_PATH", "data/sales_ops.db")).resolve()


def main() -> int:
    conn = sqlite3.connect(str(DB_PATH))
    try:
        cur = conn.cursor()
        r1 = cur.execute(
            "UPDATE approval_queue SET status='rejected', "
            "error_message='discarded: wrong sender_info (fix 2026-04-20)' "
            "WHERE status='pending' AND track='c'"
        ).rowcount
        r2 = cur.execute(
            "UPDATE companies SET status='new' WHERE status='drafted'"
        ).rowcount
        conn.commit()
        print(f"discarded={r1}, reset={r2}")

        print("\n--- post-reset counts ---")
        for row in cur.execute(
            "SELECT status, COUNT(*) FROM companies GROUP BY status"
        ):
            print(" companies", row)
        for row in cur.execute(
            "SELECT status, COUNT(*) FROM approval_queue GROUP BY status"
        ):
            print(" approval_queue", row)
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
