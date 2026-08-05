#!/usr/bin/env python3
"""楽天ROOMの公開ページから投稿一覧を取得して傾向分析するツール。

使い方:
    python rakuten_room/analyze_room.py room_d0463f2d6c
    python rakuten_room/analyze_room.py room_d0463f2d6c --csv out.csv

ログイン不要。公開されている情報のみを使用する:
  1. https://room.rakuten.co.jp/{username}/items の埋め込みJSONからユーザーIDと統計を取得
  2. /api/{user_id}/collects?api_version=1 をページングして全投稿を取得
  3. いいね・価格帯・カテゴリ・投稿文タイプの傾向をレポート出力
"""
import argparse
import csv
import json
import re
import sys
import time
import urllib.request
from collections import Counter, defaultdict
from statistics import mean, median

BASE = "https://room.rakuten.co.jp"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    ),
}
PAGE_LIMIT = 20
REQUEST_INTERVAL_SEC = 1.0

# 定型文っぽい冒頭パターン(オリジナリティ判定に使用)
TEMPLATE_PREFIXES = (
    "楽天のデイリーランキング",
    "いま楽天ランキング",
)


def _get(url: str):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8")


def fetch_user_data(username: str) -> dict:
    html = _get(f"{BASE}/{username}/items")
    m = re.search(r"window\.__INITIAL_STATE__\s*=\s*(\{.*?\})\s*(?:;|</script>)", html, re.S)
    if not m:
        raise RuntimeError("__INITIAL_STATE__ が見つかりません。ページ構造が変わった可能性があります")
    return json.loads(m.group(1))["userData"]


def fetch_all_collects(user_id: str) -> list:
    collects = []
    offset = 0
    while True:
        url = f"{BASE}/api/{user_id}/collects?api_version=1&limit={PAGE_LIMIT}&offset={offset}"
        data = json.loads(_get(url))
        batch = data.get("data", [])
        if not batch:
            break
        collects.extend(batch)
        if len(batch) < PAGE_LIMIT:
            break
        offset += PAGE_LIMIT
        time.sleep(REQUEST_INTERVAL_SEC)
    return collects


def price_band(price: int) -> str:
    if price < 1000:
        return "~999円"
    if price < 3000:
        return "1000-2999円"
    if price < 5000:
        return "3000-4999円"
    if price < 10000:
        return "5000-9999円"
    return "10000円~"


def is_template_post(content: str) -> bool:
    return (content or "").startswith(TEMPLATE_PREFIXES)


def report(user: dict, collects: list) -> None:
    print(f"■ アカウント: {user.get('fullname')} (@{user.get('username')})")
    print(f"  開設 {user.get('register', '')[:10]} / 投稿 {user.get('collects')}件 / "
          f"フォロワー {user.get('followers')} / フォロー {user.get('following_users')}")
    print(f"  ROOMランク {user.get('rank')} / 売上件数 {user.get('sold')} / 流通額 {user.get('gms')}")
    print(f"  もらったいいね {user.get('liked')} / 送ったいいね {user.get('likes')} / "
          f"コレクション {user.get('collections')}")

    likes = [int(r.get("likes") or 0) for r in collects]
    print(f"\n■ 投稿パフォーマンス ({len(collects)}件)")
    print(f"  いいね: 合計 {sum(likes)} / 平均 {mean(likes):.2f} / 中央値 {median(likes)} / "
          f"0いいね {sum(1 for x in likes if x == 0)}件")

    with_photo = sum(1 for r in collects if r.get("pictures"))
    print(f"  オリジナル写真付き投稿: {with_photo}件")

    tpl = [r for r in collects if is_template_post(r.get("content"))]
    org = [r for r in collects if not is_template_post(r.get("content"))]
    if tpl and org:
        print(f"  定型文投稿 {len(tpl)}件 (平均いいね {mean(int(r.get('likes') or 0) for r in tpl):.2f}) vs "
              f"その他 {len(org)}件 (平均いいね {mean(int(r.get('likes') or 0) for r in org):.2f})")

    print("\n■ いいね上位10投稿")
    for r in sorted(collects, key=lambda r: -int(r.get("likes") or 0))[:10]:
        item = r.get("item") or {}
        name = (item.get("name") or r.get("name") or "")[:40]
        print(f"  いいね{r.get('likes')} | {item.get('price')}円 | {name}")

    print("\n■ 価格帯分布")
    bands = Counter(price_band(int((r.get("item") or {}).get("price") or 0)) for r in collects)
    for band, count in bands.most_common():
        print(f"  {band}: {count}件")

    print("\n■ カテゴリ別 平均いいね")
    by_cat = defaultdict(list)
    for r in collects:
        item = r.get("item") or {}
        by_cat[item.get("category_lv1_id")].append(int(r.get("likes") or 0))
    for cat, cat_likes in sorted(by_cat.items(), key=lambda kv: -len(kv[1])):
        print(f"  {cat}: {len(cat_likes)}件 / 平均いいね {mean(cat_likes):.2f}")

    print("\n■ 日別投稿数(直近14日)")
    days = Counter((r.get("created_at") or "")[:10] for r in collects)
    for day, count in sorted(days.items())[-14:]:
        print(f"  {day}: {count}件")


def write_csv(collects: list, path: str) -> None:
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow([
            "created_at", "likes", "price", "affiliate_rate", "category_lv1_id",
            "is_template", "has_photo", "item_name", "content", "url",
        ])
        for r in collects:
            item = r.get("item") or {}
            writer.writerow([
                r.get("created_at"),
                r.get("likes"),
                item.get("price"),
                item.get("affiliate_rate"),
                item.get("category_lv1_id"),
                int(is_template_post(r.get("content"))),
                int(bool(r.get("pictures"))),
                item.get("name"),
                r.get("content"),
                item.get("url"),
            ])


def main() -> int:
    parser = argparse.ArgumentParser(description="楽天ROOM 投稿傾向分析")
    parser.add_argument("username", help="ROOMのユーザー名 (room.rakuten.co.jp/○○○ の部分)")
    parser.add_argument("--csv", help="投稿一覧をCSV出力するパス")
    parser.add_argument("--json", help="生データをJSON出力するパス")
    args = parser.parse_args()

    user = fetch_user_data(args.username)
    collects = fetch_all_collects(user["id"])
    report(user, collects)

    if args.csv:
        write_csv(collects, args.csv)
        print(f"\nCSV出力: {args.csv}")
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump({"user": user, "collects": collects}, f, ensure_ascii=False, indent=1)
        print(f"JSON出力: {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
