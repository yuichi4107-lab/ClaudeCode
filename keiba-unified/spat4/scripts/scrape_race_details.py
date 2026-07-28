"""SPAT4対象レースの詳細データをkeiba.go.jpからスクレイピング

既存のspat4.csvの各レース(3レース×357開催=約1000レース)について、
着順・枠番・馬番・単勝オッズ・人気を取得してCSV保存する。

使い方:
    python scripts/scrape_race_details.py
"""

from __future__ import annotations

import csv
import logging
import re
import time
from datetime import date, datetime
from io import StringIO
from pathlib import Path

import pandas as pd
import requests
from bs4 import BeautifulSoup

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

BASE_URL = "https://www.keiba.go.jp/KeibaWeb/TodayRaceInfo"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)
REQUEST_INTERVAL = 2.0

# 競馬場コード
VENUE_CODES = {
    "大井": "20",
    "川崎": "21",
    "船橋": "22",
    "浦和": "23",
    "門別": "36",
}

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
OUTPUT_FILE = DATA_DIR / "race_details.csv"

session = requests.Session()
session.headers.update({"User-Agent": USER_AGENT})


def parse_race_date(date_str: str) -> str | None:
    """'1月27日(火)' → '2026/01/27' のように変換"""
    m = re.match(r"(\d{1,2})月(\d{1,2})日", str(date_str))
    if not m:
        return None
    month = int(m.group(1))
    day = int(m.group(2))
    # 年の推定: SPAT4データは2025-04〜2026-01
    if month >= 4:
        year = 2025
    else:
        year = 2026
    return f"{year}/{month:02d}/{day:02d}"


def parse_race_no(race_str: str) -> str | None:
    """'10R' → '10'"""
    m = re.match(r"(\d+)R", str(race_str))
    return m.group(1) if m else None


def scrape_race_result(race_date: str, race_no: str, baba_code: str) -> list[dict]:
    """1レースの成績をスクレイピング"""
    url = f"{BASE_URL}/RaceMarkTable"
    params = {"k_raceDate": race_date, "k_raceNo": race_no, "k_babaCode": baba_code}

    try:
        resp = session.get(url, params=params, timeout=30)
        resp.raise_for_status()
        resp.encoding = resp.apparent_encoding
        time.sleep(REQUEST_INTERVAL)
    except requests.RequestException as e:
        logger.error("リクエスト失敗: %s R%s %s - %s", race_date, race_no, baba_code, e)
        return []

    soup = BeautifulSoup(resp.text, "lxml")

    # 成績テーブルを探す（着順・枠番・馬番... のヘッダを持つテーブル）
    results = []
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if len(rows) < 3:
            continue

        # ヘッダ行を探す
        header_row = None
        data_start = 0
        for i, row in enumerate(rows):
            cells = [td.get_text(strip=True) for td in row.find_all(["td", "th"])]
            if "着順" in cells and "馬番" in cells:
                header_row = cells
                data_start = i + 1
                break

        if header_row is None:
            continue

        # カラムインデックスを取得
        col_map = {}
        for j, h in enumerate(header_row):
            if h == "着順":
                col_map["finish"] = j
            elif h == "枠番":
                col_map["post"] = j
            elif h == "馬番":
                col_map["horse_no"] = j
            elif h == "馬名":
                col_map["horse_name"] = j
            elif h == "人気":
                col_map["popularity"] = j

        if not col_map:
            continue

        # データ行を読む
        for row in rows[data_start:]:
            cells = [td.get_text(strip=True) for td in row.find_all(["td", "th"])]
            if len(cells) < max(col_map.values()) + 1:
                continue

            finish = cells[col_map.get("finish", 0)]
            if not finish or not finish.replace(".", "").isdigit():
                continue

            record = {
                "race_date": race_date,
                "race_no": race_no,
                "baba_code": baba_code,
                "finish": int(finish) if finish.isdigit() else None,
                "post_position": cells[col_map.get("post", 0)] if "post" in col_map else None,
                "horse_number": cells[col_map.get("horse_no", 0)] if "horse_no" in col_map else None,
                "horse_name": cells[col_map.get("horse_name", 0)] if "horse_name" in col_map else None,
                "popularity": cells[col_map.get("popularity", 0)] if "popularity" in col_map else None,
            }
            results.append(record)

        if results:
            break  # 成績テーブルが見つかったらループ終了

    return results


def scrape_odds(race_date: str, race_no: str, baba_code: str) -> dict:
    """オッズページから単勝オッズを取得"""
    url = f"{BASE_URL}/OddsTanFuku"
    params = {"k_raceDate": race_date, "k_raceNo": race_no, "k_babaCode": baba_code}

    try:
        resp = session.get(url, params=params, timeout=30)
        resp.raise_for_status()
        resp.encoding = resp.apparent_encoding
        time.sleep(REQUEST_INTERVAL)
    except requests.RequestException:
        return {}

    soup = BeautifulSoup(resp.text, "lxml")
    odds_map = {}

    # テーブルから馬番とオッズを取得
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        for row in rows:
            cells = [td.get_text(strip=True) for td in row.find_all(["td", "th"])]
            # 「馬番」「単勝オッズ」のパターンを探す
            for i, cell in enumerate(cells):
                if cell.isdigit() and 1 <= int(cell) <= 16:
                    # 次のセルがオッズっぽい数値か
                    for j in range(i + 1, min(i + 4, len(cells))):
                        try:
                            odds_val = float(cells[j].replace(",", ""))
                            if 1.0 <= odds_val <= 999.9:
                                odds_map[cell] = odds_val
                                break
                        except (ValueError, IndexError):
                            continue

    return odds_map


def main():
    # SPAT4データ読み込み
    spat4_file = DATA_DIR / "spat4.csv"
    df = pd.read_csv(spat4_file, encoding="utf-8-sig")

    # 既存の詳細データを読み込み（途中再開用）
    existing_keys = set()
    if OUTPUT_FILE.exists():
        existing = pd.read_csv(OUTPUT_FILE, encoding="utf-8-sig")
        for _, row in existing.iterrows():
            existing_keys.add(f"{row['race_date']}_{row['race_no']}_{row['baba_code']}")
        logger.info("既存データ: %d レース分", len(existing_keys))

    all_results = []
    total_races = 0
    skipped = 0

    for idx, row in df.iterrows():
        venue = row.get("競馬場")
        date_str = row.get("日時")

        if pd.isna(venue) or pd.isna(date_str):
            continue

        baba_code = VENUE_CODES.get(str(venue).strip())
        if not baba_code:
            logger.warning("不明な競馬場: %s", venue)
            continue

        race_date = parse_race_date(str(date_str).strip())
        if not race_date:
            logger.warning("日付パース失敗: %s", date_str)
            continue

        # 3レース分処理
        for race_col in ["レース", "レース.1", "レース.2"]:
            race_str = row.get(race_col)
            if pd.isna(race_str):
                continue

            race_no = parse_race_no(str(race_str).strip())
            if not race_no:
                continue

            key = f"{race_date}_{race_no}_{baba_code}"
            if key in existing_keys:
                skipped += 1
                continue

            total_races += 1

            # 成績取得
            results = scrape_race_result(race_date, race_no, baba_code)
            if not results:
                logger.warning("成績取得失敗: %s R%s (%s)", race_date, race_no, venue)
                continue

            # オッズ取得
            odds_map = scrape_odds(race_date, race_no, baba_code)
            for r in results:
                horse_no = r.get("horse_number", "")
                r["win_odds"] = odds_map.get(str(horse_no))
                r["venue"] = venue

            all_results.extend(results)

            if total_races % 20 == 0:
                logger.info("進捗: %d レース取得済み (skip=%d)", total_races, skipped)

            # 50レースごとに中間保存
            if total_races % 50 == 0 and all_results:
                save_results(all_results)
                all_results = []

    # 最終保存
    if all_results:
        save_results(all_results)

    logger.info("=== 完了 ===")
    logger.info("取得レース数: %d, スキップ: %d", total_races, skipped)
    if OUTPUT_FILE.exists():
        final = pd.read_csv(OUTPUT_FILE, encoding="utf-8-sig")
        logger.info("最終データ: %d行", len(final))


def save_results(new_results: list[dict]):
    """結果をCSVに追記保存"""
    new_df = pd.DataFrame(new_results)
    if OUTPUT_FILE.exists():
        existing = pd.read_csv(OUTPUT_FILE, encoding="utf-8-sig")
        merged = pd.concat([existing, new_df], ignore_index=True)
    else:
        merged = new_df

    merged = merged.drop_duplicates(
        subset=["race_date", "race_no", "baba_code", "horse_number"], keep="last"
    )
    merged.to_csv(OUTPUT_FILE, index=False, encoding="utf-8-sig")
    logger.info("保存: %d行 → %s", len(merged), OUTPUT_FILE)


if __name__ == "__main__":
    main()
