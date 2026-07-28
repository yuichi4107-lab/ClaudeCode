"""払戻データ抽出モジュール

レース結果ページの払戻テーブルから各馬券種別の払戻データを抽出する。

netkeiba.comの払戻テーブル構造:
  - 単勝/馬連/馬単/三連複/三連単: 1行1エントリ
  - 複勝/ワイド: 1行に複数エントリが <br> 区切りで格納
    td.get_text('|') で "6|2|10" / "240|480|460" のように取得される
"""

import re
from typing import Dict, List

from bs4 import BeautifulSoup

from src.utils.logger import setup_logger

logger = setup_logger(__name__)

_BET_TYPE_ALIASES = {
    "単勝": "単勝",
    "複勝": "複勝",
    "枠連": "枠連",
    "馬連": "馬連",
    "ワイド": "ワイド",
    "馬単": "馬単",
    "三連複": "三連複",
    "三連単": "三連単",
}


def _normalize_bet_type(raw: str) -> str:
    """馬券種別名を正規化する"""
    raw = raw.strip()
    if raw in _BET_TYPE_ALIASES:
        return _BET_TYPE_ALIASES[raw]
    for key, val in _BET_TYPE_ALIASES.items():
        if key in raw:
            return val
    return raw


def _parse_payout(text: str) -> int:
    """払戻金額をパースする (e.g., '1,230円' -> 1230, '3,580' -> 3580)"""
    text = text.replace(",", "").replace("円", "").replace("¥", "").strip()
    match = re.search(r"(\d+)", text)
    return int(match.group(1)) if match else 0


def _parse_popularity(text: str) -> int:
    """人気をパースする (e.g., '1番人気' -> 1, '2' -> 2)"""
    text = text.strip()
    match = re.search(r"(\d+)", text)
    return int(match.group(1)) if match else 0


def extract_payoffs(soup: BeautifulSoup, race_id: str) -> List[Dict]:
    """払戻テーブルを解析して払戻データリストを返す

    複勝・ワイドは1行に複数エントリがあるため、 | で分割して
    個別のエントリとして返す。

    Returns:
        List of dict: race_id, bet_type, combination, payout, popularity
    """
    payoffs = []

    payout_tables = soup.select("table.pay_table_01")
    if not payout_tables:
        payout_tables = soup.select("table.pay_block")

    for table in payout_tables:
        rows = table.select("tr")
        current_bet_type = None

        for row in rows:
            th = row.select_one("th")
            tds = row.select("td")

            if th:
                current_bet_type = _normalize_bet_type(th.get_text(strip=True))

            if not tds or not current_bet_type:
                continue

            if len(tds) < 2:
                continue

            # get_text with '|' separator to split <br>-separated entries
            combo_text = tds[0].get_text("|", strip=True)
            payout_text = tds[1].get_text("|", strip=True)
            pop_text = tds[2].get_text("|", strip=True) if len(tds) >= 3 else ""

            combos = [c.strip() for c in combo_text.split("|") if c.strip()]
            payouts_raw = [p.strip() for p in payout_text.split("|") if p.strip()]
            pops_raw = [p.strip() for p in pop_text.split("|") if p.strip()]

            # 複勝・ワイド: 複数エントリを個別に処理
            for i, combo in enumerate(combos):
                payout = _parse_payout(payouts_raw[i]) if i < len(payouts_raw) else 0
                pop = _parse_popularity(pops_raw[i]) if i < len(pops_raw) else 0

                if combo and payout > 0:
                    payoffs.append({
                        "race_id": race_id,
                        "bet_type": current_bet_type,
                        "combination": combo,
                        "payout": payout,
                        "popularity": pop,
                    })

    logger.info(
        "Extracted %d payoff entries for race %s", len(payoffs), race_id
    )
    return payoffs
