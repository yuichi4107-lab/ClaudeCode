#!/usr/bin/env python3
"""Local questionnaire for choosing a KDP publication candidate and settings.

The form is localhost-only. Saving answers never signs in to KDP and never
publishes, uploads, prices, or changes an Amazon title.
"""

from __future__ import annotations

import argparse
import html as html_module
import json
import mimetypes
import re
import socket
from datetime import date, datetime, timedelta
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[2]
EBOOK_ROOT = ROOT / ".company" / "outputs" / "ebooks"
DEFAULT_OUTPUT_DIR = ROOT / ".company" / "outputs" / "kdp-publication-inputs"
JST = ZoneInfo("Asia/Tokyo")


BOOKS = [
    {
        "id": "somatid-introduction",
        "title": "ソマチッドとは何か",
        "subtitle": "未確立な生命観を、歴史・主張・科学的視点から読み解く",
        "author": "ソマチッド研究所",
        "chars": 98201,
        "quality": 90,
        "epub_mb": 51.25,
        "angle": "歴史・主張・科学的視点を横断する、もっとも広い初心者向け入門。",
        "reader": "初めてソマチッドを知る読者",
        "readiness": "公開前に著者名義と図解の最終目視が必要",
        "badge": "シリーズ第1冊におすすめ",
        "badge_kind": "recommended",
        "default": True,
    },
    {
        "id": "somatid-source-genealogy",
        "title": "ソマチッド言説を検証する",
        "subtitle": "ガストン・ネサン、714-X、日本で広がった物語を出典からたどる",
        "author": "水原 史紀",
        "chars": 96153,
        "quality": 96,
        "epub_mb": 51.96,
        "angle": "ネサン、714-X、日本語圏、SNS・AIまで、言説の出典系譜を5層で検証。",
        "reader": "公的資料と出典を重視する読者",
        "readiness": "最新基準で検証済み。KDPオンラインプレビューのみ残る",
        "badge": "現在の準備度が最高",
        "badge_kind": "ready",
        "default": False,
    },
    {
        "id": "somatid-life-decision-guide",
        "title": "ソマチッド情報と暮らしの判断術",
        "subtitle": "未確立な健康情報に流されないための安全な読み方",
        "author": "ソマチッド研究所",
        "chars": 88767,
        "quality": 93,
        "epub_mb": 69.88,
        "angle": "講座・商品・施術・SNSなど、生活上の判断を安全に行う実践書。",
        "reader": "購入や相談で迷っている一般読者",
        "readiness": "著者名義と大きめのEPUBを公開前に確認",
        "badge": "実用性重視",
        "badge_kind": "neutral",
        "default": False,
    },
    {
        "id": "somatid-belief-dialogue-map",
        "title": "ソマチッドをめぐる心の地図",
        "subtitle": "信じたい気持ちと確かめる力を両立するために",
        "author": "深見 玄理",
        "chars": 45009,
        "quality": 93,
        "epub_mb": 9.94,
        "angle": "信じたい心理、家族との対話、場の圧力を扱う感情・会話中心の本。",
        "reader": "家族や知人との対話に悩む読者",
        "readiness": "軽量で公開準備済み。テーマ特化編に向く",
        "badge": "対話・心理編",
        "badge_kind": "neutral",
        "default": False,
    },
    {
        "id": "somatid-particle-identification-science",
        "title": "ソマチットと微小世界の科学",
        "subtitle": "顕微鏡像から正体へ――動く光点を観察・測定・同定する30の問い",
        "author": "白瀬 光",
        "chars": 105000,
        "quality": 93,
        "epub_mb": 29.48,
        "angle": "顕微鏡の「動く光点」を観察・測定・同定する科学的方法論。",
        "reader": "顕微鏡や粒子同定へ関心がある読者",
        "readiness": "技術的には完成。「ソマチット」表記方針を確認",
        "badge": "科学・顕微鏡編",
        "badge_kind": "neutral",
        "default": False,
    },
    {
        "id": "somatid-information-literacy-practice",
        "title": "ソマチッド情報の読み解き方",
        "subtitle": "未確立な健康情報と安全に向き合う実践ガイド",
        "author": "ソマチッド研究所",
        "chars": 83630,
        "quality": 95,
        "epub_mb": 64.94,
        "angle": "健康情報を扱う実務者・現場リーダー向けの発信・教材化ガイド。",
        "reader": "説明や教材作成を行う実務者",
        "readiness": "品質は高い。一般向け数冊の後が自然",
        "badge": "実務者編",
        "badge_kind": "neutral",
        "default": False,
    },
]


QUESTIONS = [
    {
        "id": "metadata_action",
        "title": "タイトル・著者名",
        "required": True,
        "options": [
            {
                "value": "use_current",
                "label": "現在の書誌情報を使う",
                "description": "選んだ本のタイトル・サブタイトル・著者名をそのまま登録します。",
            },
            {
                "value": "change_author",
                "label": "著者名を変更する",
                "description": "個人ペンネームなどへ変更してから登録します。",
            },
            {
                "value": "undecided",
                "label": "まだ決めない",
                "description": "回答は保存しますが、公開準備完了にはしません。",
            },
        ],
    },
    {
        "id": "series_mode",
        "title": "シリーズ登録",
        "required": True,
        "options": [
            {
                "value": "standalone",
                "label": "まず単独刊として出す",
                "description": "最初の1冊を先に公開し、シリーズ化は後から判断します。",
                "recommended": True,
                "default": True,
            },
            {
                "value": "create_series",
                "label": "シリーズとして登録する",
                "description": "シリーズ名と巻数を決めてから公開します。",
            },
            {
                "value": "undecided",
                "label": "まだ決めない",
                "description": "候補だけ保存します。",
            },
        ],
    },
    {
        "id": "distribution_territory",
        "title": "配信権と販売地域",
        "required": True,
        "options": [
            {
                "value": "worldwide",
                "label": "全世界での出版権を保有",
                "description": "事実であれば、世界のKindleストアへ配信します。",
                "recommended": True,
                "default": True,
            },
            {
                "value": "selected_territories",
                "label": "指定地域のみ",
                "description": "権利を持つ地域だけを個別指定します。",
            },
            {
                "value": "undecided",
                "label": "権利範囲を確認する",
                "description": "確認が終わるまで公開しません。",
            },
        ],
    },
    {
        "id": "kdp_select",
        "title": "KDPセレクト",
        "required": True,
        "options": [
            {
                "value": "enroll",
                "label": "参加する",
                "description": "90日間、電子版をKindleストア独占にし、KUと日本向け70%ロイヤリティを利用します。",
            },
            {
                "value": "not_enroll",
                "label": "参加しない",
                "description": "他ストアや自サイトでも電子版を配信できます。日本向けは35%を選びます。",
            },
            {
                "value": "undecided",
                "label": "まだ決めない",
                "description": "独占条件を確認してから決めます。",
                "default": True,
            },
        ],
    },
    {
        "id": "royalty_plan",
        "title": "ロイヤリティ",
        "required": True,
        "options": [
            {
                "value": "70",
                "label": "70%（KDPセレクト参加時）",
                "description": "Amazon.co.jpでは250〜1,650円。KDPセレクト参加と配信コスト差し引きがあります。",
            },
            {
                "value": "35",
                "label": "35%",
                "description": "電子版のAmazon独占を避けたい場合に選びます。",
            },
        ],
    },
    {
        "id": "drm",
        "title": "DRM",
        "required": True,
        "options": [
            {
                "value": "apply",
                "label": "DRMを適用する",
                "description": "読者はKindleアプリ・端末で閲覧します。",
            },
            {
                "value": "drm_free",
                "label": "DRMなし",
                "description": "購入者はEPUB・PDFをダウンロードして他の対応端末でも読めます。",
            },
            {
                "value": "undecided",
                "label": "まだ決めない",
                "description": "公開前に再確認します。",
                "default": True,
            },
        ],
    },
    {
        "id": "release_mode",
        "title": "発売タイミング",
        "required": True,
        "options": [
            {
                "value": "after_preview_asap",
                "label": "プレビュー合格後、早めに公開",
                "description": "KDPオンラインプレビューと最終承認後に公開します。",
                "recommended": True,
                "default": True,
            },
            {
                "value": "preorder",
                "label": "予約販売",
                "description": "発売日の72時間以上前に最終原稿を提出します。",
            },
            {
                "value": "draft_only",
                "label": "下書き保存のみ",
                "description": "KDP上でも公開ボタンを押さず、下書きで止めます。",
            },
        ],
    },
    {
        "id": "preview_plan",
        "title": "公開前プレビュー",
        "required": True,
        "options": [
            {
                "value": "codex_then_owner",
                "label": "Codex確認後、私が最終確認",
                "description": "スマホ・タブレット相当の表示を確認してから最終承認します。",
                "recommended": True,
                "default": True,
            },
            {
                "value": "owner_only",
                "label": "自分で確認する",
                "description": "KDPオンラインプレビューを自分で確認します。",
            },
            {
                "value": "pending",
                "label": "まだ確認しない",
                "description": "公開準備完了にはしません。",
            },
        ],
    },
]


BOOK_BY_ID = {book["id"]: book for book in BOOKS}


def clean_list_item(line: str) -> str:
    return re.sub(r"^\s*(?:[-*]|\d+[.)])\s*", "", line).strip()


def unique_limited(items: list[str], limit: int) -> list[str]:
    result: list[str] = []
    for item in items:
        normalized = item.strip().strip("。、")
        if normalized and normalized not in result:
            result.append(normalized)
        if len(result) >= limit:
            break
    return result


def kdp_metadata_snapshot(book_id: str) -> dict[str, object]:
    base = EBOOK_ROOT / book_id / "KDP出版用"
    category_file = base / "ジャンル・キーワード.md"
    description_file = base / "書籍紹介文_HTML.html"
    categories: list[str] = []
    keywords: list[str] = []

    if category_file.exists():
        mode = ""
        for raw in category_file.read_text(encoding="utf-8-sig").splitlines():
            line = raw.strip()
            if line.startswith("## "):
                heading = line[3:].strip()
                if "キーワード" in heading:
                    mode = "keywords"
                elif "カテゴリ" in heading or "ジャンル" in heading:
                    mode = "categories"
                else:
                    mode = ""
                continue
            if not line or line.startswith("#"):
                continue
            if mode == "categories" and re.match(r"^(?:[-*]|\d+[.)])\s*", line):
                categories.append(clean_list_item(line))
            elif mode == "keywords":
                if re.match(r"^(?:[-*]|\d+[.)])\s*", line):
                    keywords.append(clean_list_item(line))
                elif "," in line:
                    keywords.extend(part.strip() for part in line.split(","))

    description_preview = ""
    if description_file.exists():
        raw_html = description_file.read_text(encoding="utf-8-sig")
        plain = re.sub(r"<[^>]+>", " ", raw_html)
        plain = re.sub(r"\s+", " ", html_module.unescape(plain)).strip()
        description_preview = plain[:360] + ("…" if len(plain) > 360 else "")

    return {
        "language": "日本語",
        "content_description": {
            "status": "作成済み" if description_file.exists() else "未作成",
            "preview": description_preview,
            "path": str(description_file) if description_file.exists() else None,
        },
        "categories": unique_limited(categories, 3),
        "keywords": unique_limited(keywords, 7),
        "category_keyword_path": str(category_file) if category_file.exists() else None,
    }


def books_for_ui() -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for source in BOOKS:
        book: dict[str, object] = dict(source)
        book["kdp_metadata"] = kdp_metadata_snapshot(str(source["id"]))
        result.append(book)
    return result


def pick_port(host: str, preferred: int) -> int:
    for port in range(preferred, preferred + 50):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind((host, port))
            except OSError:
                continue
            return port
    raise RuntimeError(f"No free port found from {preferred} to {preferred + 49}")


def artifact_paths(book_id: str) -> dict[str, str | None]:
    base = EBOOK_ROOT / book_id
    epub_files = sorted((base / "KDP出版用").glob("*.epub"))
    cover = base / "KDP出版用" / "cover.jpg"
    return {
        "project_dir": str(base),
        "epub": str(epub_files[0]) if epub_files else None,
        "cover": str(cover) if cover.exists() else None,
    }


def answer_value(answers: dict, key: str) -> str:
    item = answers.get(key)
    if not isinstance(item, dict):
        return ""
    return str(item.get("value") or "")


def validate_answers(payload: dict) -> list[str]:
    issues: list[str] = []
    selected_book = str(payload.get("selected_book_id") or "")
    if selected_book not in BOOK_BY_ID:
        issues.append("最初に公開する本を選択してください。")

    answers = payload.get("answers") if isinstance(payload.get("answers"), dict) else {}
    for question in QUESTIONS:
        value = answer_value(answers, str(question["id"]))
        allowed = {str(option["value"]) for option in question["options"]}
        if question.get("required") and value not in allowed:
            issues.append(f"{question['title']}を選択してください。")

    metadata_action = answer_value(answers, "metadata_action")
    if metadata_action == "change_author" and not str(payload.get("new_author_name") or "").strip():
        issues.append("変更後の著者名を入力してください。")
    if metadata_action == "undecided":
        issues.append("著者名を含む書誌情報が未確定です。")

    selected = BOOK_BY_ID.get(selected_book)
    effective_author = str(selected.get("author") or "") if selected else ""
    if metadata_action == "change_author":
        effective_author = str(payload.get("new_author_name") or "").strip()
    if "研究所" in effective_author and payload.get("editorial_brand_confirmed") is not True:
        issues.append("「研究所」名義が実在の医療・研究機関ではなく、編集上の著者名義であることを確認してください。")

    if answer_value(answers, "series_mode") == "create_series":
        if not str(payload.get("series_name") or "").strip():
            issues.append("シリーズ名を入力してください。")

    territory = answer_value(answers, "distribution_territory")
    if territory == "selected_territories" and not str(payload.get("territory_note") or "").strip():
        issues.append("販売する地域を入力してください。")
    if territory == "undecided":
        issues.append("配信権の範囲が未確定です。")
    if payload.get("rights_confirmed") is not True:
        issues.append("出版権の確認が必要です。")

    kdp_select = answer_value(answers, "kdp_select")
    royalty = answer_value(answers, "royalty_plan")
    if kdp_select == "undecided":
        issues.append("KDPセレクトへの参加が未確定です。")
    if kdp_select == "enroll" and payload.get("ebook_exclusivity_confirmed") is not True:
        issues.append("KDPセレクト参加には、電子版の90日間独占確認が必要です。")
    if royalty == "70" and kdp_select != "enroll":
        issues.append("Amazon.co.jpで70%を選ぶにはKDPセレクト参加が必要です。")

    try:
        price = int(payload.get("list_price") or 0)
    except (TypeError, ValueError):
        price = 0
    if royalty == "70" and not 250 <= price <= 1650:
        issues.append("70%ロイヤリティの価格は250〜1,650円にしてください。")
    if royalty == "35" and not 99 <= price <= 20000:
        issues.append("35%ロイヤリティの価格は99〜20,000円にしてください。")

    drm = answer_value(answers, "drm")
    if drm == "undecided":
        issues.append("DRMの設定が未確定です。")

    release_mode = answer_value(answers, "release_mode")
    if release_mode == "preorder":
        raw_date = str(payload.get("release_date") or "")
        try:
            release_date = date.fromisoformat(raw_date)
        except ValueError:
            issues.append("予約販売の発売日を入力してください。")
        else:
            today = datetime.now(JST).date()
            if release_date < today + timedelta(days=4):
                issues.append("予約販売日は今日から4日以上先にしてください。")
            if release_date > today + timedelta(days=365):
                issues.append("予約販売日は1年以内にしてください。")

    if answer_value(answers, "preview_plan") == "pending":
        issues.append("公開前プレビューの担当が未確定です。")
    if payload.get("metadata_confirmed") is not True:
        issues.append("タイトル・著者名などの書誌確認が必要です。")
    if payload.get("health_safety_confirmed") is not True:
        issues.append("健康効果を保証する表現がないことの確認が必要です。")
    if payload.get("ai_disclosure_confirmed") is not True:
        issues.append("AI生成コンテンツの申告内容を確認してください。")
    return issues


HTML_TEMPLATE = r"""<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>KDP出版準備アンケート</title>
  <style>
    :root {
      color-scheme: light;
      --ink: #17202a; --muted: #5f6b78; --line: #dbe2ea; --paper: #f5f7fa;
      --panel: #fff; --navy: #102a43; --teal: #0f766e; --teal-soft: #e8f5f2;
      --amber: #a65d08; --amber-soft: #fff6e5; --blue: #2457a6; --blue-soft: #eef4ff;
      --danger: #a12b2b; --danger-soft: #fff0f0;
    }
    * { box-sizing: border-box; }
    body { margin: 0; background: var(--paper); color: var(--ink); font-family: -apple-system, BlinkMacSystemFont, "Hiragino Sans", "Yu Gothic", sans-serif; line-height: 1.65; }
    main { width: min(1180px, calc(100vw - 28px)); margin: 0 auto; padding: 24px 0 52px; }
    header { background: linear-gradient(135deg, #102a43, #174f55); color: white; border-radius: 18px; padding: 26px 28px; box-shadow: 0 12px 32px rgba(16,42,67,.14); }
    h1 { margin: 0; font-size: clamp(26px, 4vw, 42px); line-height: 1.25; }
    header p { margin: 10px 0 0; color: #d9edf0; max-width: 850px; }
    .safe-note { margin-top: 16px; display: inline-flex; gap: 8px; align-items: center; background: rgba(255,255,255,.12); border: 1px solid rgba(255,255,255,.25); padding: 9px 12px; border-radius: 999px; font-size: 13px; }
    .section { margin-top: 22px; background: var(--panel); border: 1px solid var(--line); border-radius: 16px; padding: 22px; }
    .section-head { display: flex; gap: 12px; justify-content: space-between; align-items: end; flex-wrap: wrap; margin-bottom: 15px; }
    h2 { margin: 0; font-size: 23px; }
    h3 { margin: 0; font-size: 17px; }
    .muted, .help { color: var(--muted); font-size: 13px; }
    .book-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; }
    .book-card { display: grid; grid-template-columns: 112px 1fr; gap: 14px; padding: 14px; border: 2px solid var(--line); border-radius: 14px; background: white; cursor: pointer; min-height: 205px; transition: .16s ease; }
    .book-card:hover { border-color: #93b6bb; transform: translateY(-1px); }
    .book-card:has(input:checked) { border-color: var(--teal); background: var(--teal-soft); box-shadow: 0 0 0 2px rgba(15,118,110,.1); }
    .cover { width: 108px; height: 162px; object-fit: cover; border-radius: 6px; box-shadow: 0 5px 16px rgba(16,42,67,.2); background: #e8edf2; }
    .book-main { min-width: 0; }
    .book-select { display: flex; gap: 9px; align-items: flex-start; }
    input[type="radio"], input[type="checkbox"] { accent-color: var(--teal); width: 18px; height: 18px; flex: none; }
    .book-title { font-size: 18px; font-weight: 800; line-height: 1.4; }
    .subtitle { color: var(--muted); font-size: 12px; margin-top: 2px; }
    .badge { display: inline-flex; margin-top: 8px; border-radius: 999px; padding: 3px 9px; font-size: 11px; font-weight: 800; }
    .badge.recommended { color: #7a4200; background: #fff0ce; border: 1px solid #e9c36a; }
    .badge.ready { color: #075b53; background: #dbf4ef; border: 1px solid #8ad1c7; }
    .badge.neutral { color: #30558b; background: #ecf3ff; border: 1px solid #bcd0ef; }
    .metrics { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 9px; }
    .metric { font-size: 11px; color: #405264; background: #f1f4f7; border-radius: 6px; padding: 2px 7px; }
    .angle { margin-top: 9px; font-size: 13px; }
    .readiness { margin-top: 7px; font-size: 12px; color: var(--amber); }
    .metadata-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
    .metadata-card { border: 1px solid var(--line); border-radius: 12px; padding: 14px; background: #fbfcfe; }
    .metadata-card.wide { grid-column: 1 / -1; }
    .metadata-value { margin-top: 6px; font-size: 14px; }
    .tag-list { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }
    .tag { background: #edf2f7; color: #334e68; border-radius: 999px; padding: 4px 9px; font-size: 12px; }
    .numbered-list { margin: 8px 0 0; padding-left: 22px; font-size: 13px; }
    .choice-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; }
    fieldset { border: 1px solid var(--line); border-radius: 12px; padding: 15px; margin: 0; min-width: 0; }
    legend { font-weight: 800; padding: 0 7px; }
    .choices { display: grid; gap: 8px; margin-top: 7px; }
    .choice { display: grid; grid-template-columns: 22px 1fr; gap: 9px; padding: 10px; border: 1px solid var(--line); border-radius: 10px; cursor: pointer; }
    .choice:hover { background: #f8fbfc; }
    .choice:has(input:checked) { border-color: var(--teal); background: var(--teal-soft); }
    .choice-title { font-weight: 750; }
    .mini-badge { margin-left: 6px; color: var(--blue); background: var(--blue-soft); border: 1px solid #c9daf8; border-radius: 999px; padding: 1px 7px; font-size: 10px; }
    .extra-grid { display: grid; grid-template-columns: repeat(2, minmax(0,1fr)); gap: 14px; margin-top: 16px; }
    .control { border: 1px solid var(--line); border-radius: 12px; padding: 15px; }
    label.block { display: block; font-weight: 750; margin-bottom: 6px; }
    input[type="text"], input[type="number"], input[type="date"], textarea { width: 100%; border: 1px solid #bfc9d4; border-radius: 9px; padding: 10px 11px; font: inherit; background: white; }
    textarea { min-height: 95px; resize: vertical; }
    .price-row { display: grid; grid-template-columns: repeat(5, 1fr); gap: 8px; }
    .price-button { position: relative; }
    .price-button input { position: absolute; opacity: 0; }
    .price-button span { display: block; text-align: center; border: 1px solid var(--line); border-radius: 9px; padding: 10px 5px; cursor: pointer; font-weight: 750; }
    .price-button input:checked + span { border-color: var(--teal); background: var(--teal-soft); color: #075b53; }
    .policy { display: grid; gap: 8px; margin-top: 12px; padding: 13px; border-radius: 10px; background: #f7f9fb; border: 1px solid var(--line); font-size: 13px; }
    .policy strong { color: var(--navy); }
    .checks { display: grid; gap: 10px; }
    .check { display: grid; grid-template-columns: 22px 1fr; gap: 10px; align-items: start; padding: 10px; border: 1px solid var(--line); border-radius: 10px; }
    .warning { display: none; margin-top: 12px; padding: 12px; border: 1px solid #f2c38b; background: var(--amber-soft); color: #7a4200; border-radius: 10px; font-size: 13px; white-space: pre-line; }
    .actions { position: sticky; bottom: 10px; z-index: 3; display: flex; justify-content: space-between; align-items: center; gap: 12px; margin-top: 22px; padding: 14px 16px; border: 1px solid #aac2c7; background: rgba(255,255,255,.96); backdrop-filter: blur(8px); border-radius: 14px; box-shadow: 0 10px 28px rgba(16,42,67,.16); }
    button { border: 0; border-radius: 10px; background: var(--teal); color: white; padding: 12px 20px; font-weight: 800; font-size: 15px; cursor: pointer; }
    button:hover { filter: brightness(.95); }
    .saved { display: none; margin-top: 14px; padding: 14px; border-radius: 10px; background: #edf9f1; border: 1px solid #a9ddb9; color: #155d2b; white-space: pre-line; }
    .incomplete { background: var(--danger-soft); border-color: #efb1b1; color: var(--danger); }
    @media (max-width: 850px) { .book-grid, .choice-grid, .extra-grid, .metadata-grid { grid-template-columns: 1fr; } .metadata-card.wide { grid-column: auto; } .price-row { grid-template-columns: repeat(3,1fr); } }
    @media (max-width: 520px) { main { width: min(100% - 18px, 1180px); } header, .section { padding: 17px; } .book-card { grid-template-columns: 78px 1fr; } .cover { width: 76px; height: 114px; } .actions { align-items: stretch; flex-direction: column; } button { width: 100%; } }
  </style>
</head>
<body>
<main>
  <header>
    <h1>KDP出版準備アンケート</h1>
    <p>完成済み6冊を比べ、最初に公開する1冊とKDP設定を決めます。回答はこのPC内に保存され、Amazonには送信されません。</p>
    <div class="safe-note">🔒 保存しても公開・アップロード・課金は行われません</div>
  </header>

  <form id="kdp-form">
    <section class="section">
      <div class="section-head">
        <div><h2>1. 最初に公開する本</h2><div class="muted">「入口の分かりやすさ」と「現在の完成度」を分けて表示しています。</div></div>
        <div class="muted">全6冊：EPUB・表紙あり</div>
      </div>
      <div id="book-grid" class="book-grid"></div>
    </section>

    <section class="section">
      <div class="section-head"><div><h2>2. KDP入力情報の一覧</h2><div class="muted">選んだ本に用意済みの、言語・商品説明・カテゴリー・キーワードを確認できます。</div></div></div>
      <div id="metadata-panel" class="metadata-grid"></div>
    </section>

    <section class="section">
      <div class="section-head"><div><h2>3. KDPの登録設定</h2><div class="muted">おすすめは青緑色で初期選択されています。独占条件だけは必ずご自身で確認してください。</div></div></div>
      <div id="question-grid" class="choice-grid"></div>

      <div class="extra-grid">
        <div class="control">
          <label class="block" for="new_author_name">変更後の著者名</label>
          <input id="new_author_name" type="text" placeholder="著者名を変更する場合のみ入力">
          <div id="author-note" class="help">選んだ本の現在の著者名をここに表示します。</div>
        </div>
        <div class="control">
          <label class="block" for="series_name">シリーズ名</label>
          <input id="series_name" type="text" placeholder="シリーズ登録する場合のみ入力">
          <div class="help">例：ソマチッドを読み解くシリーズ</div>
        </div>
        <div class="control">
          <label class="block" for="territory_note">指定する販売地域</label>
          <input id="territory_note" type="text" placeholder="指定地域のみの場合に入力">
        </div>
        <div class="control">
          <label class="block" for="release_date">予約販売の発売日</label>
          <input id="release_date" type="date">
          <div class="help">予約販売を選ぶ場合のみ。今日から4日以上先、1年以内。</div>
        </div>
      </div>
    </section>

    <section class="section">
      <div class="section-head"><div><h2>4. 価格</h2><div id="epub-size-note" class="muted"></div></div></div>
      <div class="price-row">
        <label class="price-button"><input type="radio" name="price_choice" value="498"><span>498円</span></label>
        <label class="price-button"><input type="radio" name="price_choice" value="780" checked><span>780円<br><small>おすすめ</small></span></label>
        <label class="price-button"><input type="radio" name="price_choice" value="980"><span>980円</span></label>
        <label class="price-button"><input type="radio" name="price_choice" value="1200"><span>1,200円</span></label>
        <label class="price-button"><input type="radio" name="price_choice" value="custom"><span>自由入力</span></label>
      </div>
      <div style="margin-top:10px; max-width:240px"><input id="custom_price" type="number" min="99" max="20000" step="1" placeholder="自由入力の価格"></div>
      <div class="policy">
        <div><strong>70%：</strong>Amazon.co.jpでは250〜1,650円。KDPセレクト参加が必要で、ファイル容量に応じた配信コストが差し引かれます。</div>
        <div><strong>35%：</strong>99〜20,000円。電子版をAmazon独占にしない場合はこちらを選びます。</div>
      </div>
      <div id="compat-warning" class="warning"></div>
    </section>

    <section class="section">
      <div class="section-head"><div><h2>5. 権利・AI申告・安全確認</h2><div class="muted">公開前に必ず確認する項目です。</div></div></div>
      <div class="checks">
        <label class="check"><input id="rights_confirmed" type="checkbox"><span><strong>出版権を確認した</strong><br><span class="help">選んだ販売地域で、この本を出版できる権利を保有しています。</span></span></label>
        <label class="check"><input id="ebook_exclusivity_confirmed" type="checkbox"><span><strong>電子版の90日間独占条件を確認した</strong><br><span class="help">KDPセレクトへ参加する場合のみ必須。電子版はKDPと公共図書館以外で配信しません。</span></span></label>
        <label class="check"><input id="editorial_brand_confirmed" type="checkbox"><span><strong>「研究所」名義は編集上の著者ブランドであることを確認した</strong><br><span class="help">該当する著者名を使う場合のみ必須。実在の医療機関・研究機関・資格者を示す名義ではありません。</span></span></label>
        <label class="check"><input id="metadata_confirmed" type="checkbox"><span><strong>タイトル・サブタイトル・著者名を確認した</strong><br><span class="help">表紙、EPUB、KDP登録欄で同じ表記にします。</span></span></label>
        <label class="check"><input id="health_safety_confirmed" type="checkbox"><span><strong>健康効果を保証する表現がないことを確認する</strong><br><span class="help">治療・診断・予防効果や標準医療の中止を勧めません。</span></span></label>
        <label class="check"><input id="ai_disclosure_confirmed" type="checkbox"><span><strong>AI生成申告：本文＝はい、表紙・本文画像＝はい、翻訳＝該当なし</strong><br><span class="help">編集量にかかわらず、AIが生成した本文と画像として申告します。</span></span></label>
      </div>
    </section>

    <section class="section">
      <label class="block" for="notes"><h3>補足・希望</h3></label>
      <textarea id="notes" placeholder="例：最初の本だけ780円にする。著者名は全6冊で統一案を見てから決めたい。"></textarea>
      <div id="saved" class="saved"></div>
    </section>

    <div class="actions">
      <div><strong id="status">回答を選んで保存してください。</strong><div class="help">保存後も publication_authorization は false のままです。</div></div>
      <button type="submit">回答を保存する（KDPには送信しません）</button>
    </div>
  </form>
</main>

<script>
const books = __BOOKS_JSON__;
const questions = __QUESTIONS_JSON__;

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[char]));
}

function renderBooks() {
  document.getElementById("book-grid").innerHTML = books.map((book) => `
    <label class="book-card">
      <img class="cover" src="/cover/${esc(book.id)}" alt="${esc(book.title)}の表紙">
      <span class="book-main">
        <span class="book-select">
          <input type="radio" name="selected_book_id" value="${esc(book.id)}" ${book.default ? "checked" : ""}>
          <span><span class="book-title">${esc(book.title)}</span><span class="subtitle">${esc(book.subtitle)}</span></span>
        </span>
        <span class="badge ${esc(book.badge_kind)}">${esc(book.badge)}</span>
        <span class="metrics">
          <span class="metric">著者：${esc(book.author)}</span><span class="metric">${book.chars.toLocaleString()}字</span><span class="metric">品質 ${book.quality}/100</span><span class="metric">EPUB ${book.epub_mb}MB</span>
        </span>
        <span class="angle">${esc(book.angle)}</span>
        <span class="readiness">${esc(book.readiness)}</span>
      </span>
    </label>`).join("");
}

function renderQuestions() {
  document.getElementById("question-grid").innerHTML = questions.map((q) => `
    <fieldset><legend>${esc(q.title)}</legend><div class="choices">${q.options.map((opt) => `
      <label class="choice"><input type="radio" name="${esc(q.id)}" value="${esc(opt.value)}" ${opt.default ? "checked" : ""}>
        <span><span class="choice-title">${esc(opt.label)}${opt.recommended ? '<span class="mini-badge">おすすめ</span>' : ""}</span><span class="help">${esc(opt.description)}</span></span>
      </label>`).join("")}</div></fieldset>`).join("");
}

function renderMetadata(book) {
  const meta = book.kdp_metadata || {};
  const description = meta.content_description || {};
  const categories = Array.isArray(meta.categories) ? meta.categories : [];
  const keywords = Array.isArray(meta.keywords) ? meta.keywords : [];
  document.getElementById("metadata-panel").innerHTML = `
    <div class="metadata-card"><h3>言語</h3><div class="metadata-value">${esc(meta.language || "未設定")}</div></div>
    <div class="metadata-card"><h3>書誌情報</h3><div class="metadata-value"><strong>${esc(book.title)}</strong><br>${esc(book.subtitle)}<br>著者：${esc(book.author)}</div></div>
    <div class="metadata-card wide"><h3>商品説明</h3><div class="metadata-value"><span class="badge ready">${esc(description.status || "未確認")}</span><br>${esc(description.preview || "商品説明が見つかりません。")}</div></div>
    <div class="metadata-card"><h3>カテゴリー候補（最大3）</h3><ol class="numbered-list">${categories.map((item) => `<li>${esc(item)}</li>`).join("") || "<li>未設定</li>"}</ol><div class="help">公開時にKDP画面の現行カテゴリーから最も近いものを選びます。</div></div>
    <div class="metadata-card"><h3>検索キーワード（最大7）</h3><div class="tag-list">${keywords.map((item) => `<span class="tag">${esc(item)}</span>`).join("") || '<span class="tag">未設定</span>'}</div></div>`;
}

function selectedValue(name) {
  const node = document.querySelector(`input[name="${name}"]:checked`);
  return node ? node.value : "";
}

function selectedBook() { return books.find((book) => book.id === selectedValue("selected_book_id")); }

function answerObject() {
  const answers = {};
  for (const question of questions) {
    const value = selectedValue(question.id);
    const option = question.options.find((item) => item.value === value);
    answers[question.id] = { value, label: option ? option.label : value };
  }
  return answers;
}

function currentPrice() {
  const choice = selectedValue("price_choice");
  if (choice === "custom") return Number(document.getElementById("custom_price").value || 0);
  return Number(choice || 0);
}

function updateContext() {
  const book = selectedBook();
  if (!book) return;
  renderMetadata(book);
  document.getElementById("author-note").textContent = `現在の著者：${book.author}${book.author.includes("研究所") ? "（実在の研究機関と誤解されない名義確認が必要）" : ""}`;
  document.getElementById("epub-size-note").textContent = `選択中：『${book.title}』／EPUB 約${book.epub_mb}MB。70%では配信コストが差し引かれるため、KDP画面の推定額を確認します。`;
  updateCompatibility();
}

function updateCompatibility() {
  const select = selectedValue("kdp_select");
  const royalty = selectedValue("royalty_plan");
  const price = currentPrice();
  const warnings = [];
  if (royalty === "70" && select !== "enroll") warnings.push("70%とKDPセレクト不参加・未定は両立しません。参加するか、35%を選んでください。");
  if (royalty === "70" && (price < 250 || price > 1650)) warnings.push("70%の価格は250〜1,650円です。");
  if (royalty === "35" && (price < 99 || price > 20000)) warnings.push("35%の価格は99〜20,000円です。");
  const box = document.getElementById("compat-warning");
  box.textContent = warnings.join("\n");
  box.style.display = warnings.length ? "block" : "none";
}

document.addEventListener("change", (event) => {
  if (event.target.matches('input[name="selected_book_id"]')) updateContext();
  if (event.target.matches('input[name="kdp_select"], input[name="royalty_plan"], input[name="price_choice"]')) updateCompatibility();
});
document.getElementById("custom_price").addEventListener("input", updateCompatibility);

document.getElementById("kdp-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const book = selectedBook();
  const payload = {
    schema_version: 1,
    selected_book_id: book ? book.id : "",
    selected_book: book || null,
    answers: answerObject(),
    new_author_name: document.getElementById("new_author_name").value.trim(),
    series_name: document.getElementById("series_name").value.trim(),
    territory_note: document.getElementById("territory_note").value.trim(),
    list_price: currentPrice(),
    currency: "JPY",
    primary_marketplace: "Amazon.co.jp",
    release_date: document.getElementById("release_date").value,
    rights_confirmed: document.getElementById("rights_confirmed").checked,
    ebook_exclusivity_confirmed: document.getElementById("ebook_exclusivity_confirmed").checked,
    editorial_brand_confirmed: document.getElementById("editorial_brand_confirmed").checked,
    metadata_confirmed: document.getElementById("metadata_confirmed").checked,
    health_safety_confirmed: document.getElementById("health_safety_confirmed").checked,
    ai_disclosure_confirmed: document.getElementById("ai_disclosure_confirmed").checked,
    ai_disclosure: { text: "ai_generated", images: "ai_generated", translation: "not_applicable" },
    notes: document.getElementById("notes").value.trim(),
    publication_authorization: false
  };
  document.getElementById("status").textContent = "保存中です…";
  const response = await fetch("/submit", { method: "POST", headers: {"Content-Type":"application/json"}, body: JSON.stringify(payload) });
  const result = await response.json();
  const saved = document.getElementById("saved");
  saved.style.display = "block";
  saved.classList.toggle("incomplete", result.readiness_status !== "complete");
  if (!response.ok) {
    document.getElementById("status").textContent = "保存できませんでした。";
    saved.textContent = result.error || "保存エラー";
    return;
  }
  document.getElementById("status").textContent = result.readiness_status === "complete" ? "回答を保存しました。公開準備の確認へ進めます。" : "回答を保存しました。未確定項目があります。";
  saved.textContent = `保存先：${result.path}\n${result.readiness_status === "complete" ? "KDP公開準備アンケートは完了です。公開自体はまだ行いません。" : "未確定：\n・" + result.validation_issues.join("\n・")}`;
  saved.scrollIntoView({behavior:"smooth", block:"center"});
});

renderBooks();
renderQuestions();
updateContext();
</script>
</body>
</html>
"""


def render_page() -> bytes:
    html = HTML_TEMPLATE.replace("__BOOKS_JSON__", json.dumps(books_for_ui(), ensure_ascii=False))
    html = html.replace("__QUESTIONS_JSON__", json.dumps(QUESTIONS, ensure_ascii=False))
    return html.encode("utf-8")


class KDPHandler(BaseHTTPRequestHandler):
    server_version = "KDPPublicationSetupUI/1.0"

    def log_message(self, fmt: str, *args: object) -> None:
        return

    @property
    def app(self) -> "KDPServer":
        return self.server  # type: ignore[return-value]

    def send_json(self, status: HTTPStatus, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/":
            body = render_page()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if parsed.path == "/health":
            self.send_json(HTTPStatus.OK, {"ok": True, "books": len(BOOKS)})
            return
        if parsed.path == "/latest":
            latest = self.app.output_dir / "latest.json"
            if latest.exists():
                self.send_json(HTTPStatus.OK, {"path": str(latest), "data": json.loads(latest.read_text(encoding="utf-8"))})
            else:
                self.send_json(HTTPStatus.NOT_FOUND, {"error": "No saved answer yet."})
            return
        if parsed.path.startswith("/cover/"):
            book_id = unquote(parsed.path.removeprefix("/cover/"))
            if book_id not in BOOK_BY_ID:
                self.send_json(HTTPStatus.NOT_FOUND, {"error": "Unknown book."})
                return
            cover = EBOOK_ROOT / book_id / "KDP出版用" / "cover.jpg"
            if not cover.exists():
                self.send_json(HTTPStatus.NOT_FOUND, {"error": "Cover not found."})
                return
            body = cover.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", mimetypes.guess_type(cover.name)[0] or "image/jpeg")
            self.send_header("Cache-Control", "private, max-age=300")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_json(HTTPStatus.NOT_FOUND, {"error": "Not found."})

    def do_POST(self) -> None:
        if urlparse(self.path).path != "/submit":
            self.send_json(HTTPStatus.NOT_FOUND, {"error": "Not found."})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": "回答データを読み取れませんでした。"})
            return
        if not isinstance(payload, dict):
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": "回答形式が正しくありません。"})
            return

        answers = payload.get("answers")
        if not isinstance(answers, dict) or any(not isinstance(item, dict) for item in answers.values()):
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": "選択回答の形式が正しくありません。画面を再読み込みしてください。"})
            return

        selected_id = str(payload.get("selected_book_id") or "")
        if selected_id not in BOOK_BY_ID:
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": "最初に公開する本を選択してください。"})
            return

        now = datetime.now(JST)
        payload["selected_book"] = dict(BOOK_BY_ID[selected_id])
        payload["kdp_metadata_snapshot"] = kdp_metadata_snapshot(selected_id)
        issues = validate_answers(payload)
        payload["submitted_at"] = now.isoformat()
        payload["source"] = "local_kdp_publication_setup_ui"
        payload["selected_artifacts"] = artifact_paths(selected_id)
        payload["validation_issues"] = issues
        payload["readiness_status"] = "complete" if not issues else "needs_confirmation"
        payload["publication_authorization"] = False

        self.app.output_dir.mkdir(parents=True, exist_ok=True)
        out_path = self.app.output_dir / f"{now.strftime('%Y%m%d-%H%M%S')}-kdp-publication-setup.json"
        text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
        out_path.write_text(text, encoding="utf-8")
        (self.app.output_dir / "latest.json").write_text(text, encoding="utf-8")

        self.send_json(
            HTTPStatus.OK,
            {
                "ok": True,
                "path": str(out_path),
                "readiness_status": payload["readiness_status"],
                "validation_issues": issues,
                "publication_authorization": False,
            },
        )


class KDPServer(ThreadingHTTPServer):
    def __init__(self, address: tuple[str, int], output_dir: Path):
        super().__init__(address, KDPHandler)
        self.output_dir = output_dir


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the localhost KDP publication setup questionnaire.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8775)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    port = pick_port(args.host, args.port)
    server = KDPServer((args.host, port), output_dir=args.output_dir)
    print(f"kdp_publication_setup_ui_url=http://{args.host}:{port}/", flush=True)
    print(f"kdp_publication_setup_output_dir={args.output_dir}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
