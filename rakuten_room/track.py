#!/usr/bin/env python3
"""ROOMの成果推移を記録するツール。定期実行して効果測定に使う。

使い方:
    python rakuten_room/track.py room_d0463f2d6c

実行するたびに、アカウント統計(フォロワー・もらったいいね等)と投稿ごとの
いいね数を SQLite (data/rakuten_room.db) にスナップショット保存し、
前回実行時からの変化を表示する。

これを週1〜毎日回すことで「どの投稿・どんな商品タイプにいいねが付いたか」が
時系列で残り、suggest.py の選定基準を実績で調整できるようになる。
"""
import argparse
import sqlite3
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from rakuten_room.analyze_room import fetch_all_collects, fetch_user_data, is_template_post

DB_PATH = Path("data/rakuten_room.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS room_stats (
    snapshot_date TEXT PRIMARY KEY,
    followers     INTEGER,
    following     INTEGER,
    posts         INTEGER,
    likes_received INTEGER,
    likes_given   INTEGER,
    room_rank     INTEGER,
    sold          INTEGER,
    gms           INTEGER
);
CREATE TABLE IF NOT EXISTS post_likes (
    snapshot_date TEXT NOT NULL,
    collect_id    TEXT NOT NULL,
    likes         INTEGER,
    item_price    INTEGER,
    category_lv1  TEXT,
    is_template   INTEGER,
    item_name     TEXT,
    created_at    TEXT,
    PRIMARY KEY (snapshot_date, collect_id)
);
"""


def open_db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)
    return conn


def save(conn: sqlite3.Connection, snapshot_date: str, user: dict, collects: list) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO room_stats VALUES (?,?,?,?,?,?,?,?,?)",
        (
            snapshot_date,
            user.get("followers"),
            user.get("following_users"),
            user.get("collects"),
            user.get("liked"),
            user.get("likes"),
            user.get("rank"),
            user.get("sold"),
            user.get("gms"),
        ),
    )
    conn.executemany(
        "INSERT OR REPLACE INTO post_likes VALUES (?,?,?,?,?,?,?,?)",
        [
            (
                snapshot_date,
                r.get("id"),
                int(r.get("likes") or 0),
                int((r.get("item") or {}).get("price") or 0),
                (r.get("item") or {}).get("category_lv1_id"),
                int(is_template_post(r.get("content"))),
                ((r.get("item") or {}).get("name") or "")[:80],
                r.get("created_at"),
            )
            for r in collects
        ],
    )
    conn.commit()


def show_diff(conn: sqlite3.Connection, snapshot_date: str) -> None:
    row = conn.execute(
        "SELECT MAX(snapshot_date) FROM room_stats WHERE snapshot_date < ?",
        (snapshot_date,),
    ).fetchone()
    prev_date = row[0] if row else None
    if not prev_date:
        print("(初回スナップショットを保存しました。次回実行から前回比が表示されます)")
        return

    cur = conn.execute("SELECT * FROM room_stats WHERE snapshot_date = ?", (snapshot_date,)).fetchone()
    prev = conn.execute("SELECT * FROM room_stats WHERE snapshot_date = ?", (prev_date,)).fetchone()
    labels = ["", "フォロワー", "フォロー", "投稿数", "もらったいいね", "送ったいいね", "ランク", "売上件数", "流通額"]
    print(f"■ アカウント推移 ({prev_date} → {snapshot_date})")
    for i in range(1, len(labels)):
        diff = (cur[i] or 0) - (prev[i] or 0)
        sign = f" ({'+' if diff >= 0 else ''}{diff})" if diff else ""
        print(f"  {labels[i]}: {cur[i]}{sign}")

    print(f"\n■ 前回からいいねが増えた投稿")
    rows = conn.execute(
        """SELECT c.item_name, c.likes - COALESCE(p.likes, 0) AS gained, c.likes
           FROM post_likes c LEFT JOIN post_likes p
             ON p.collect_id = c.collect_id AND p.snapshot_date = ?
           WHERE c.snapshot_date = ? AND c.likes - COALESCE(p.likes, 0) > 0
           ORDER BY gained DESC LIMIT 10""",
        (prev_date, snapshot_date),
    ).fetchall()
    if not rows:
        print("  (増加なし)")
    for name, gained, total in rows:
        print(f"  +{gained} (計{total}) | {(name or '')[:50]}")


def main() -> int:
    parser = argparse.ArgumentParser(description="ROOM成果推移の記録")
    parser.add_argument("username", help="ROOMのユーザー名")
    parser.add_argument("--date", default=date.today().isoformat())
    args = parser.parse_args()

    user = fetch_user_data(args.username)
    collects = fetch_all_collects(user["id"])
    conn = open_db()
    save(conn, args.date, user, collects)
    show_diff(conn, args.date)
    return 0


if __name__ == "__main__":
    sys.exit(main())
