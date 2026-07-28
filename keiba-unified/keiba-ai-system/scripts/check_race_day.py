"""開催日チェックスクリプト

カレンダーJSON + keiba.go.jp のレース一覧ページで
本日が開催日かどうかを判定する。
--half 指定時は、開催種別に応じた実行時刻もチェックする。

終了コード:
  0 = 開催日かつ実行タイミングOK
  1 = 非開催日 or タイミング不一致（スキップ）

使い方:
    python scripts/check_race_day.py
    python scripts/check_race_day.py --half first
    python scripts/check_race_day.py --half second
    python scripts/check_race_day.py --date 2026-04-18 --half first --time 13:50
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date, datetime, time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"
CALENDAR_PATH = CONFIG_DIR / "race_calendar.json"

BASE_URL = "https://www.keiba.go.jp/KeibaWeb/TodayRaceInfo"
BABA_CODE = "3"  # 帯広
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

# 開催種別ごとの第1競走時刻
FIRST_RACE_TIMES = {
    "nighter": time(14, 20),
    "semi_nighter": time(13, 45),
    "twilight": time(13, 0),
}

# 前半結第1競走30分�、後半7-�P競走2時間後
HALF_OFFSETS = {
    "first": -30,   # 分
    "second": 120,   # 分
}

# 開催種別ごとの予測実行時刻
SCHEDULE = {
    "nighter":      {"first": time(13, 50), "second": time(16, 20)},
    "semi_nighter": {"first": time(13, 15), "second": time(15, 45)},
    "twilight":     {"first": time(12, 30), "second": time(15, 0)},
}


def load_calendar() -> dict | None:
    if not CALENDAR_PATH.exists():
        logger.warning("カレンダーファイルなし: %s", CALENDAR_PATH)
        return None
    with open(CALENDAR_PATH, encoding="utf-8") as f:
        return json.load(f)


def is_calendar_race_day(cal: dict | None, target: date) -> bool:
    if cal is None:
        return True
    return target.isoformat() in cal["race_dates"]


def get_race_type(target_date: date) -> str | None:
    """race_calendar.jsonのmeets配列から該当日のrace_typeを返す"""
    cal = load_calendar()
    target_iso = target_date.isoformat()
    for meet in cal.get("meets", []):
        if target_iso in meet.get("race_dates", []):
            return meet["race_type"]
    return None


def is_correct_timing(race_type: str, half: str, now_time: time) -> bool:
    """現在時刻が開催種別の実行時刻と合っているか（±10分の許容範囲）"""
    expected = SCHEDULE.get(race_type, {}).get(half)
    if expected is None:
        return True  # 判定できなければ通す

    # 分単位で比較
    now_min = now_time.hour * 60 + now_time.minute
    exp_min = expected.hour * 60 + expected.minute
    diff = abs(now_min - exp_min)
    if diff <= 10:
        return True

    logger.info("タイミンジ�Mな致: 開催種別=%s, 期待=%s, 現在=%s → スキップ",
                race_type, expected.strftime("%H:%M"), now_time.strftime("%H:%M"))
    return False


def is_online_race_day(target: date) -> bool:
    """keiba.go.jp のレース一覧ページで開催確認"""
    date_str = target.strftime("%Y/%m/%d")
    url = f"{BASE_URL}/RaceList"
    params = {"k_raceDate": date_str, "k_babaCode": BABA_CODE}

    try:
        resp = requests.get(url, params=params, headers={"User-Agent": USER_AGENT}, timeout=15)
        resp.raise_for_status()
        resp.encoding = resp.apparent_encoding
        soup = BeautifulSoup(resp.text, "lxml")

        for link in soup.find_all("a", href=True):
            if "RaceMarkTable" in link["href"] or "DebaTable" in link["href"]:
                return True
        return False

    except requests.RequestException as e:
        logger.warning("オンラインチェック失敗: %s — カレンダー判定を信頼", e)
        return True


def main():
    parser = argparse.ArgumentParser(description="ばんえい開催日チェック")
    parser.add_argument("--date", help="チェック日 (YYYY-MM-DD)")
    parser.add_argument("--half", choices=["first", "second"],
                        help="前半(first)or後半(second) — 指定時は実行時刻もチェック")
    parser.add_argument("--time", help="現在時刻の上書き (HH:MM) — テスト用")
    args = parser.parse_args()

    target = datetime.strptime(args.date, "%Y-%m-%d").date() if args.date else date.today()

    cal = load_calendar()

    # Step 1: カレンダーチェック
    if not is_calendar_race_day(cal, target):
        logger.info("%s: カレンダー上で非開催日 → スキップ", target)
        sys.exit(1)

    # Step 2: 実行タイミングチェック（--half指定時のみ）
    if args.half:
        race_type = get_race_type(target)
        if race_type:
            if args.time:
                now_time = datetime.strptime(args.time, "%H:%M").time()
            else:
                now_time = datetime.now().time()
            if not is_correct_timing(race_type, args.half, now_time):
                sys.exit(1)
            logger.info("%s: %s / %s半 → 実行OK", target, race_type, args.half)

    # Step 3: オンラインチェック
    if not is_online_race_day(target):
        logger.info("%s: keiba.go.jp で開催なし → スキップ", target)
        sys.exit(1)

    logger.info("%s: 開催日確認OK", target)
    sys.exit(0)


if __name__ == "__main__":
    main()
