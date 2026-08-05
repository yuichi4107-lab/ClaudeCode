#!/usr/bin/env python3
"""楽天市場の売れ筋ランキングから、ROOM投稿候補リストを生成するツール。

使い方:
    export RAKUTEN_APP_ID=...
    export RAKUTEN_ACCESS_KEY=...
    export RAKUTEN_ALLOWED_DOMAIN=example.com
    python rakuten_room/suggest.py                # 候補トップ10を表示+Markdown保存
    python rakuten_room/suggest.py --top-n 15
    python rakuten_room/suggest.py --genres 215783,100804

仕組み:
  1. 対象ジャンルのランキング(各3ページ=90件)を取得
  2. SQLite (data/rakuten_room.db) に日次スナップショットとして保存
  3. 前回スナップショットと比較して「急上昇」を検出
  4. ランキング順位・急上昇・レビュー・価格帯・期待報酬でスコアリング
  5. 投稿文のたたき台付きで候補リストを出力 (data/suggestions/YYYYMMDD.md)

対象ジャンルはROOMの実績(analyze_room.py の分析)で反応が良かった系統に合わせている。
"""
import argparse
import os
import sqlite3
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from rakuten_room.rakuten_api import fetch_ranking

# ROOMの投稿実績と相性が良いジャンル (Ichiba genreId)
DEFAULT_GENRES = {
    "215783": "日用品雑貨・文房具・手芸",
    "100804": "インテリア・寝具・収納",
    "558944": "キッチン用品・食器・調理器具",
}
PAGES_PER_GENRE = 3  # 30件/ページ
DB_PATH = Path("data/rakuten_room.db")
OUT_DIR = Path("data/suggestions")

SCHEMA = """
CREATE TABLE IF NOT EXISTS ranking_snapshots (
    snapshot_date TEXT NOT NULL,
    genre_id      TEXT NOT NULL,
    rank          INTEGER NOT NULL,
    item_code     TEXT NOT NULL,
    item_name     TEXT,
    item_price    INTEGER,
    review_count  INTEGER,
    review_average REAL,
    affiliate_rate REAL,
    item_url      TEXT,
    affiliate_url TEXT,
    shop_name     TEXT,
    PRIMARY KEY (snapshot_date, genre_id, rank)
);
"""


def open_db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute(SCHEMA)
    return conn


def collect_rankings(genres: dict) -> list:
    items = []
    for genre_id, genre_name in genres.items():
        for page in range(1, PAGES_PER_GENRE + 1):
            for item in fetch_ranking(genre_id=genre_id, page=page):
                item["_genre_id"] = genre_id
                item["_genre_name"] = genre_name
                items.append(item)
        print(f"  {genre_name}: {PAGES_PER_GENRE * 30}件取得", file=sys.stderr)
    return items


def save_snapshot(conn: sqlite3.Connection, snapshot_date: str, items: list) -> None:
    conn.executemany(
        """INSERT OR REPLACE INTO ranking_snapshots VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        [
            (
                snapshot_date,
                it["_genre_id"],
                int(it.get("rank") or 0),
                it.get("itemCode") or it.get("itemUrl") or "",
                it.get("itemName"),
                int(it.get("itemPrice") or 0),
                int(it.get("reviewCount") or 0),
                float(it.get("reviewAverage") or 0),
                float(it.get("affiliateRate") or 0),
                it.get("itemUrl"),
                it.get("affiliateUrl"),
                (it.get("shopName") or ""),
            )
            for it in items
        ],
    )
    conn.commit()


def previous_ranks(conn: sqlite3.Connection, before_date: str) -> dict:
    """before_date より前の直近スナップショットの {(genre_id, item_code): rank}"""
    row = conn.execute(
        "SELECT MAX(snapshot_date) FROM ranking_snapshots WHERE snapshot_date < ?",
        (before_date,),
    ).fetchone()
    prev_date = row[0] if row else None
    if not prev_date:
        return {}
    return {
        (genre_id, code): rank
        for genre_id, code, rank in conn.execute(
            "SELECT genre_id, item_code, rank FROM ranking_snapshots WHERE snapshot_date = ?",
            (prev_date,),
        )
    }


def price_fit(price: int) -> float:
    """ROOM実績で反応が良い価格帯(1000〜9999円)を優遇"""
    if 1000 <= price < 10000:
        return 1.0
    if price < 1000:
        return 0.6
    if price < 20000:
        return 0.7
    return 0.4


def score_item(item: dict, prev: dict) -> tuple:
    rank = int(item.get("rank") or 90)
    price = int(item.get("itemPrice") or 0)
    review_count = int(item.get("reviewCount") or 0)
    review_avg = float(item.get("reviewAverage") or 0)
    rate = float(item.get("affiliateRate") or 0)

    rank_score = max(0.0, (91 - rank) / 90)
    review_score = min(review_count, 1000) / 1000 * (review_avg / 5 if review_avg else 0.5)
    if 0 < review_avg < 4.0:  # 低評価商品は紹介リスクが高い
        review_score *= 0.3
    reward_score = min(price * rate / 100, 500) / 500  # 1件成約の期待報酬(500円で頭打ち)

    key = (item["_genre_id"], item.get("itemCode") or item.get("itemUrl") or "")
    prev_rank = prev.get(key)
    if prev_rank is None:
        surge, surge_label = (0.6, "NEW(前回圏外)") if prev else (0.0, "")
    elif prev_rank - rank >= 10:
        surge, surge_label = 1.0, f"急上昇 {prev_rank}位→{rank}位"
    elif prev_rank > rank:
        surge, surge_label = 0.3, f"上昇 {prev_rank}位→{rank}位"
    else:
        surge, surge_label = 0.0, ""

    total = (
        0.30 * rank_score
        + 0.25 * review_score
        + 0.15 * price_fit(price)
        + 0.15 * reward_score
        + 0.15 * surge
    )
    return total, surge_label


def render_markdown(candidates: list, snapshot_date: str) -> str:
    lines = [
        f"# ROOM投稿候補 {snapshot_date}",
        "",
        "スコア = ランキング順位 + 急上昇 + レビュー + 価格帯 + 期待報酬 の加重平均。",
        "**投稿文はたたき台です。「自分の言葉ポイント」を必ず自分の体験・視点で書き換えてから投稿してください**",
        "(定型文のままの投稿はいいねが付きにくいことが分析で確認済み)。",
        "",
    ]
    for n, (score, surge_label, item) in enumerate(candidates, 1):
        price = int(item.get("itemPrice") or 0)
        rate = float(item.get("affiliateRate") or 0)
        review_count = int(item.get("reviewCount") or 0)
        review_avg = item.get("reviewAverage") or "-"
        url = item.get("affiliateUrl") or item.get("itemUrl") or ""
        name = (item.get("itemName") or "").strip()
        lines += [
            f"## {n}. {name[:60]}",
            "",
            f"- ジャンル: {item['_genre_name']} {item.get('rank')}位"
            + (f" / **{surge_label}**" if surge_label else ""),
            f"- 価格: {price:,}円 / 料率: {rate}% (成約1件 約{int(price * rate / 100)}円)",
            f"- レビュー: {review_count:,}件 / ★{review_avg}",
            f"- URL: {url}",
            "",
            "投稿文たたき台:",
            "```",
            f"{name[:30]}…",
            "【自分の言葉ポイント】なぜ気になったか・どんな場面で使いたいかを2〜3行で",
            f"レビュー{review_count:,}件で★{review_avg}と高評価。",
            "```",
            "",
        ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="ROOM投稿候補リスト生成")
    parser.add_argument("--top-n", type=int, default=10)
    parser.add_argument("--genres", help="ジャンルIDをカンマ区切りで指定(省略時はデフォルト3ジャンル)")
    parser.add_argument("--date", default=date.today().isoformat(), help="スナップショット日付(YYYY-MM-DD)")
    args = parser.parse_args()

    if args.genres:
        genres = {g: g for g in args.genres.split(",")}
    else:
        genres = DEFAULT_GENRES

    print("ランキング取得中...", file=sys.stderr)
    items = collect_rankings(genres)

    conn = open_db()
    prev = previous_ranks(conn, args.date)
    save_snapshot(conn, args.date, items)

    seen = set()
    scored = []
    for item in items:
        code = item.get("itemCode") or item.get("itemUrl") or ""
        if code in seen:
            continue
        seen.add(code)
        total, surge_label = score_item(item, prev)
        scored.append((total, surge_label, item))
    scored.sort(key=lambda x: -x[0])
    candidates = scored[: args.top_n]

    md = render_markdown(candidates, args.date)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / f"{args.date.replace('-', '')}.md"
    out_path.write_text(md, encoding="utf-8")

    print(md)
    print(f"\n保存先: {out_path}", file=sys.stderr)
    if not prev:
        print("(初回実行のため急上昇判定なし。明日以降の実行から順位変動が反映されます)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
