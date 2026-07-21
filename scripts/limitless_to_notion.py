#!/usr/bin/env python3
"""Limitless のライフログを Notion データベースへ同期するスクリプト。

Limitless API (https://api.limitless.ai/v1/lifelogs) から指定期間のライフログを
取得し、Notion データベースに 1 ライフログ = 1 ページとして保存する。
ページには Lifelog ID を記録し、既に保存済みのログはスキップするため
何度実行しても重複しない(定期実行を想定)。

必要な環境変数:
    LIMITLESS_API_KEY     Limitless アプリの Settings > Developer で発行した API キー
    NOTION_API_KEY        Notion インテグレーションのシークレット (ntn_... / secret_...)
    NOTION_DATABASE_ID    保存先データベースの ID (URL の 32 桁 16 進部分)

任意の環境変数:
    NOTION_DATE_PROP      日付プロパティ名 (既定: 日付)
    NOTION_ID_PROP        Lifelog ID プロパティ名 (既定: Lifelog ID)

使い方:
    python scripts/limitless_to_notion.py                # 直近3日分を同期
    python scripts/limitless_to_notion.py --days 7       # 直近7日分
    python scripts/limitless_to_notion.py --date 2026-07-20
    python scripts/limitless_to_notion.py --dry-run      # Notion に書き込まず確認のみ

セットアップ手順は docs/limitless_to_notion.md を参照。
"""

import argparse
import os
import sys
import time
from datetime import date, datetime, timedelta

import requests

LIMITLESS_API = "https://api.limitless.ai/v1/lifelogs"
NOTION_API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"

# Notion API の制限
NOTION_TEXT_LIMIT = 2000      # rich_text 1要素あたりの文字数上限
NOTION_BLOCK_LIMIT = 95       # ページ作成時に付ける本文ブロック数の上限(APIは100)

DEFAULT_TIMEZONE = "Asia/Tokyo"


def _request_with_retry(method, url, *, headers, params=None, json_body=None, max_retries=4):
    """429/5xx をバックオフ付きでリトライする HTTP リクエスト。"""
    delay = 2
    for attempt in range(max_retries + 1):
        resp = requests.request(
            method, url, headers=headers, params=params, json=json_body, timeout=30
        )
        if resp.status_code < 400:
            return resp
        if resp.status_code in (429, 500, 502, 503, 504) and attempt < max_retries:
            retry_after = resp.headers.get("Retry-After")
            wait = int(retry_after) if retry_after and retry_after.isdigit() else delay
            time.sleep(wait)
            delay *= 2
            continue
        raise RuntimeError(
            f"{method} {url} failed: HTTP {resp.status_code} {resp.text[:500]}"
        )
    raise RuntimeError("unreachable")


# ---------------------------------------------------------------------------
# Limitless
# ---------------------------------------------------------------------------

def fetch_lifelogs(api_key, start, end, tz):
    """期間内のライフログを全ページ取得して返す(古い順)。"""
    headers = {"X-API-Key": api_key}
    lifelogs = []
    cursor = None
    while True:
        params = {
            "start": start,
            "end": end,
            "timezone": tz,
            "limit": 10,
            "direction": "asc",
            "includeMarkdown": "true",
            "includeHeadings": "true",
        }
        if cursor:
            params["cursor"] = cursor
        resp = _request_with_retry("GET", LIMITLESS_API, headers=headers, params=params)
        payload = resp.json()
        batch = payload.get("data", {}).get("lifelogs", [])
        lifelogs.extend(batch)
        cursor = payload.get("meta", {}).get("lifelogs", {}).get("nextCursor")
        if not cursor or not batch:
            return lifelogs


# ---------------------------------------------------------------------------
# Notion
# ---------------------------------------------------------------------------

def notion_headers(api_key):
    return {
        "Authorization": f"Bearer {api_key}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }


def get_database(api_key, database_id):
    resp = _request_with_retry(
        "GET", f"{NOTION_API}/databases/{database_id}", headers=notion_headers(api_key)
    )
    return resp.json()


def find_title_property(database):
    """データベースのタイトル型プロパティ名を返す(名前は問わない)。"""
    for name, prop in database.get("properties", {}).items():
        if prop.get("type") == "title":
            return name
    raise RuntimeError("データベースにタイトル型プロパティが見つかりません")


def ensure_id_property(api_key, database, id_prop):
    """Lifelog ID 用のテキストプロパティが無ければ追加する。"""
    if id_prop in database.get("properties", {}):
        return
    _request_with_retry(
        "PATCH",
        f"{NOTION_API}/databases/{database['id']}",
        headers=notion_headers(api_key),
        json_body={"properties": {id_prop: {"rich_text": {}}}},
    )
    print(f"  Notion データベースにプロパティ「{id_prop}」を追加しました")


def ensure_date_property(api_key, database, date_prop):
    """日付プロパティが無ければ追加する。"""
    if date_prop in database.get("properties", {}):
        return
    _request_with_retry(
        "PATCH",
        f"{NOTION_API}/databases/{database['id']}",
        headers=notion_headers(api_key),
        json_body={"properties": {date_prop: {"date": {}}}},
    )
    print(f"  Notion データベースにプロパティ「{date_prop}」を追加しました")


def page_exists(api_key, database_id, id_prop, lifelog_id):
    resp = _request_with_retry(
        "POST",
        f"{NOTION_API}/databases/{database_id}/query",
        headers=notion_headers(api_key),
        json_body={
            "filter": {"property": id_prop, "rich_text": {"equals": lifelog_id}},
            "page_size": 1,
        },
    )
    return bool(resp.json().get("results"))


def _chunk_text(text, limit=NOTION_TEXT_LIMIT):
    return [text[i : i + limit] for i in range(0, len(text), limit)] or [""]


def _text_block(block_type, text):
    return {
        "object": "block",
        "type": block_type,
        block_type: {
            "rich_text": [
                {"type": "text", "text": {"content": chunk}}
                for chunk in _chunk_text(text)
            ]
        },
    }


def markdown_to_blocks(markdown):
    """Limitless の Markdown を Notion ブロックに変換する(簡易パーサ)。

    見出し(#/##/###)・箇条書き(- )・段落のみ対応。ブロック数が上限を
    超える場合は打ち切り、末尾にその旨の段落を付ける。
    """
    blocks = []
    for raw_line in (markdown or "").splitlines():
        line = raw_line.rstrip()
        if not line.strip():
            continue
        stripped = line.strip()
        if stripped.startswith("### "):
            blocks.append(_text_block("heading_3", stripped[4:]))
        elif stripped.startswith("## "):
            blocks.append(_text_block("heading_2", stripped[3:]))
        elif stripped.startswith("# "):
            blocks.append(_text_block("heading_1", stripped[2:]))
        elif stripped.startswith("- "):
            blocks.append(_text_block("bulleted_list_item", stripped[2:]))
        else:
            blocks.append(_text_block("paragraph", stripped))
        if len(blocks) >= NOTION_BLOCK_LIMIT:
            blocks.append(
                _text_block("paragraph", "(長いため以降は省略。全文は Limitless アプリ参照)")
            )
            break
    return blocks


def create_page(api_key, database_id, title_prop, date_prop, id_prop, lifelog):
    title = lifelog.get("title") or "(無題のライフログ)"
    properties = {
        title_prop: {"title": [{"type": "text", "text": {"content": title[:200]}}]},
        id_prop: {
            "rich_text": [{"type": "text", "text": {"content": lifelog["id"]}}]
        },
    }
    start_time = lifelog.get("startTime")
    if start_time:
        date_value = {"start": start_time}
        if lifelog.get("endTime"):
            date_value["end"] = lifelog["endTime"]
        properties[date_prop] = {"date": date_value}

    _request_with_retry(
        "POST",
        f"{NOTION_API}/pages",
        headers=notion_headers(api_key),
        json_body={
            "parent": {"database_id": database_id},
            "properties": properties,
            "children": markdown_to_blocks(lifelog.get("markdown")),
        },
    )


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def parse_args():
    parser = argparse.ArgumentParser(
        description="Limitless のライフログを Notion データベースへ同期する"
    )
    parser.add_argument("--days", type=int, default=3, help="直近N日分を同期(既定: 3)")
    parser.add_argument("--date", help="特定日のみ同期 (YYYY-MM-DD)")
    parser.add_argument("--timezone", default=DEFAULT_TIMEZONE, help=f"タイムゾーン(既定: {DEFAULT_TIMEZONE})")
    parser.add_argument("--dry-run", action="store_true", help="Notion に書き込まず対象を表示のみ")
    return parser.parse_args()


def main():
    args = parse_args()

    limitless_key = os.environ.get("LIMITLESS_API_KEY")
    notion_key = os.environ.get("NOTION_API_KEY")
    database_id = os.environ.get("NOTION_DATABASE_ID")
    missing = [
        name
        for name, value in [
            ("LIMITLESS_API_KEY", limitless_key),
            ("NOTION_API_KEY", notion_key),
            ("NOTION_DATABASE_ID", database_id),
        ]
        if not value
    ]
    if missing:
        print(f"環境変数が未設定です: {', '.join(missing)}", file=sys.stderr)
        print("設定方法は docs/limitless_to_notion.md を参照してください", file=sys.stderr)
        return 1

    date_prop = os.environ.get("NOTION_DATE_PROP", "日付")
    id_prop = os.environ.get("NOTION_ID_PROP", "Lifelog ID")

    if args.date:
        start_day = datetime.strptime(args.date, "%Y-%m-%d").date()
        end_day = start_day
    else:
        end_day = date.today()
        start_day = end_day - timedelta(days=max(args.days - 1, 0))
    start = f"{start_day} 00:00:00"
    end = f"{end_day} 23:59:59"

    print(f"Limitless からライフログを取得: {start_day} 〜 {end_day} ({args.timezone})")
    lifelogs = fetch_lifelogs(limitless_key, start, end, args.timezone)
    print(f"  {len(lifelogs)} 件取得")
    if not lifelogs:
        return 0

    database = get_database(notion_key, database_id)
    title_prop = find_title_property(database)
    if not args.dry_run:
        ensure_id_property(notion_key, database, id_prop)
        ensure_date_property(notion_key, database, date_prop)

    created = skipped = 0
    for lifelog in lifelogs:
        label = f"{lifelog.get('startTime', '?')[:16]} {lifelog.get('title') or '(無題)'}"
        if page_exists(notion_key, database_id, id_prop, lifelog["id"]):
            skipped += 1
            print(f"  スキップ(保存済み): {label}")
            continue
        if args.dry_run:
            created += 1
            print(f"  [dry-run] 保存対象: {label}")
            continue
        create_page(notion_key, database_id, title_prop, date_prop, id_prop, lifelog)
        created += 1
        print(f"  保存: {label}")
        time.sleep(0.4)  # Notion のレート制限(約3req/秒)対策

    action = "保存対象" if args.dry_run else "保存"
    print(f"完了: {action} {created} 件 / スキップ {skipped} 件")
    return 0


if __name__ == "__main__":
    sys.exit(main())
