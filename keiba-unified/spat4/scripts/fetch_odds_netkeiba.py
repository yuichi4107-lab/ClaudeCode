"""nar.netkeiba.comからSPAT4対象レースの単勝オッズを取得

既存のrace_details.csvにオッズ情報を付加する。

使い方:
    python scripts/fetch_odds_netkeiba.py
"""

from __future__ import annotations

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

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DETAILS_FILE = DATA_DIR / "race_details.csv"

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
REQUEST_INTERVAL = 1.5

# netkeiba 競馬場コード（地方）
# 大井=36, 川崎=37, 船橋=38, 浦和=39, 門別=30
VENUE_MAP = {
    "20": "36",  # 大井: keiba.go.jp=20 → netkeiba=36
    "21": "37",  # 川崎
    "22": "38",  # 船橋
    "23": "39",  # 浦和
    "36": "30",  # 門別
}

session = requests.Session()
session.headers.update({"User-Agent": USER_AGENT})


def build_race_id(race_date: str, race_no: str, baba_code: str) -> str | None:
    """netkeiba形式のrace_idを構築: YYYY + venue_code + MMDD + race_no(2桁)"""
    # race_date = "2025/12/30"
    m = re.match(r"(\d{4})/(\d{2})/(\d{2})", race_date)
    if not m:
        return None
    year, month, day = m.group(1), m.group(2), m.group(3)
    nk_venue = VENUE_MAP.get(baba_code)
    if not nk_venue:
        return None
    race_no_2d = race_no.zfill(2)
    return f"{year}{nk_venue}{month}{day}{race_no_2d}"


def fetch_odds(race_id: str) -> dict[str, float]:
    """レース結果ページから馬番→単勝オッズのマッピングを取得"""
    url = "https://nar.netkeiba.com/race/result.html"
    params = {"race_id": race_id}

    try:
        resp = session.get(url, params=params, timeout=30)
        resp.encoding = "euc-jp"
        time.sleep(REQUEST_INTERVAL)

        tables = pd.read_html(StringIO(resp.text))
        if not tables or len(tables) == 0:
            return {}

        # 結果テーブル（着順・馬番・単勝オッズを含むもの）
        for t in tables:
            cols = [str(c) for c in t.columns]
            # 「馬 番」「単勝 オッズ」カラムを探す
            horse_no_col = None
            odds_col = None
            for c in cols:
                if "馬" in c and "番" in c:
                    horse_no_col = c
                if "オッズ" in c:
                    odds_col = c

            if horse_no_col and odds_col:
                result = {}
                for _, row in t.iterrows():
                    try:
                        hno = str(int(row[horse_no_col]))
                        odds = float(row[odds_col])
                        result[hno] = odds
                    except (ValueError, TypeError):
                        continue
                return result

    except Exception as e:
        logger.debug("fetch failed for %s: %s", race_id, e)

    return {}


def main():
    if not DETAILS_FILE.exists():
        logger.error("race_details.csv が見つかりません")
        return

    df = pd.read_csv(DETAILS_FILE, encoding="utf-8-sig")
    logger.info("既存データ: %d行, オッズあり: %d", len(df), df["win_odds"].notna().sum())

    # レースごとにグループ化
    races = df.groupby(["race_date", "race_no", "baba_code"]).first().reset_index()
    total = len(races)
    fetched = 0
    skipped = 0

    for idx, race in races.iterrows():
        rd = race["race_date"]
        rno = str(int(race["race_no"]))
        bc = str(int(race["baba_code"]))

        # 既にオッズがある行があればスキップ
        mask = (df["race_date"] == rd) & (df["race_no"] == int(rno)) & (df["baba_code"] == int(bc))
        if df.loc[mask, "win_odds"].notna().any():
            skipped += 1
            continue

        race_id = build_race_id(rd, rno, bc)
        if not race_id:
            continue

        odds_map = fetch_odds(race_id)
        if odds_map:
            for hno_str, odds_val in odds_map.items():
                row_mask = mask & (df["horse_number"].astype(str) == hno_str)
                df.loc[row_mask, "win_odds"] = odds_val
            fetched += 1
        else:
            fetched += 1  # カウントはするが取得失敗

        if (fetched + skipped) % 50 == 0:
            logger.info("進捗: %d/%d (fetched=%d, skip=%d, odds_filled=%d)",
                        fetched + skipped, total, fetched, skipped, df["win_odds"].notna().sum())

    # 保存
    df.to_csv(DETAILS_FILE, index=False, encoding="utf-8-sig")
    logger.info("=== 完了 ===")
    logger.info("取得: %d, スキップ: %d", fetched, skipped)
    logger.info("オッズあり: %d / %d", df["win_odds"].notna().sum(), len(df))


if __name__ == "__main__":
    main()
