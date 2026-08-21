"""Win5対象レースの特定（全面改訂版: date= エンドポイント・和数字パーサ対応）"""

import logging
import re
from datetime import date

from bs4 import BeautifulSoup

from config.settings import NETKEIBA_RACE_URL
from database.models import Win5Event
from scraper.base import BaseScraper

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# 純粋関数: 金額・票数パーサ
# ─────────────────────────────────────────────────────────────

def parse_japanese_yen(s: str) -> int | None:
    """和数字を含む金額文字列を整数(円)に変換する。

    例:
        "188万5200円"    → 1_885_200
        "7億9447万8300円" → 794_478_300
        "2億円"          → 200_000_000
        ""               → None
    アルゴリズム:
        1. 「円」とカンマを除去
        2. 「億」で分割: 左部 × 10^8 を加算
        3. 「万」で分割: 左部 × 10^4 を加算
        4. 残りを加算
    """
    if not s:
        return None
    s = s.replace(",", "").replace("円", "").strip()
    if not s:
        return None

    result = 0

    # 億の処理
    if "億" in s:
        oku_part, s = s.split("億", 1)
        try:
            result += int(oku_part) * 100_000_000
        except ValueError:
            return None

    # 万の処理
    if "万" in s:
        man_part, s = s.split("万", 1)
        try:
            result += int(man_part) * 10_000
        except ValueError:
            return None

    # 残り（円未満の端数）
    if s:
        try:
            result += int(s)
        except ValueError:
            return None

    return result


def parse_int_count(s: str) -> int | None:
    """「295票」「7,944,783票」などを整数に変換する。

    「票」を除去しカンマを取り除いてintを返す。
    該当なし・変換失敗は None。
    """
    if not s:
        return None
    s = s.replace(",", "").replace("票", "").strip()
    if not s:
        return None
    try:
        return int(s)
    except ValueError:
        return None


# ─────────────────────────────────────────────────────────────
# HTMLパーサ
# ─────────────────────────────────────────────────────────────

def parse_win5_page(html: str, event_date: date) -> Win5Event | None:
    """WIN5ページHTMLをパースして Win5Event を返す。

    5レース未満の場合は None を返す。
    的中週: payout 設定・carryover=None
    CO週  : carryover 設定・payout=None
    """
    soup = BeautifulSoup(html, "lxml")

    # ── race_id 抽出 ──────────────────────────
    race_ids: list[str] = []
    seen: set[str] = set()
    for m in re.finditer(r"result\.html\?race_id=(\d{12})", html):
        rid = m.group(1)
        if rid not in seen:
            seen.add(rid)
            race_ids.append(rid)

    if len(race_ids) < 5:
        logger.warning(
            "WIN5 page %s: found only %d race_ids (need 5), skip",
            event_date,
            len(race_ids),
        )
        return None

    race_ids = race_ids[:5]

    # ── 金額・票数 抽出 ────────────────────────
    payout: int | None = None
    carryover: int | None = None
    num_winners: int | None = None
    total_sales: int | None = None

    # 全テーブルセルのテキストを走査
    # 発売金額
    for th in soup.find_all("th"):
        th_text = th.get_text(strip=True)
        td = th.find_next_sibling("td")
        if td is None:
            continue
        td_text = td.get_text(strip=True)

        if th_text == "発売金額":
            total_sales = parse_japanese_yen(td_text)
        elif th_text == "払戻金":
            payout = parse_japanese_yen(td_text)
        elif th_text == "的中票数":
            num_winners = parse_int_count(td_text)
        elif "キャリーオーバー" in th_text:
            carryover = parse_japanese_yen(td_text)

    # 発売金額が th/td 兄弟でない場合のフォールバック（同一 <tr> に複数 th がある場合）
    if total_sales is None:
        for tr in soup.find_all("tr"):
            cells = tr.find_all(["th", "td"])
            texts = [c.get_text(strip=True) for c in cells]
            for i, t in enumerate(texts):
                if t == "発売金額" and i + 1 < len(texts):
                    total_sales = parse_japanese_yen(texts[i + 1])

    # 発売票数フォールバック（発売票数は使わないが念のため）
    # 払戻金がなくキャリーオーバーが存在するケースに備える
    if payout is None and carryover is None:
        # CO週の別パターン: <th>キャリーオーバー金額</th> など
        full_text = soup.get_text()
        co_match = re.search(r"キャリーオーバー[^\d]*([0-9,億万]+円)", full_text)
        if co_match:
            carryover = parse_japanese_yen(co_match.group(1))

    event_id = event_date.strftime("%Y%m%d")
    event = Win5Event(
        event_id=event_id,
        event_date=event_date,
        race1_id=race_ids[0],
        race2_id=race_ids[1],
        race3_id=race_ids[2],
        race4_id=race_ids[3],
        race5_id=race_ids[4],
        payout=float(payout) if payout is not None else None,
        carryover=float(carryover) if carryover is not None else None,
        num_winners=num_winners,
        total_sales=float(total_sales) if total_sales is not None else None,
    )

    logger.info(
        "Parsed WIN5 %s: races=%s, payout=%s, carryover=%s, winners=%s",
        event_date,
        race_ids,
        payout,
        carryover,
        num_winners,
    )
    return event


# ─────────────────────────────────────────────────────────────
# スクレイパークラス
# ─────────────────────────────────────────────────────────────

class Win5TargetScraper(BaseScraper):
    """Win5対象レースの情報を取得する"""

    def scrape(self, target_date: date) -> Win5Event | None:
        """指定日の WIN5 情報を取得する。

        URL は ?date=YYYYMMDD 形式（kaisai_date ではない）。
        ネットワーク失敗時は None を返してログを出す（全体を止めない）。
        """
        date_str = target_date.strftime("%Y%m%d")
        url = f"{NETKEIBA_RACE_URL}/top/win5.html?date={date_str}"

        try:
            # fetch() はキャッシュ対応のため、キャッシュヒット時は再取得しない
            html = self.fetch(url, encoding="euc-jp")
        except Exception as e:
            logger.error("Failed to fetch WIN5 page for %s: %s", target_date, e)
            return None

        return parse_win5_page(html, target_date)

    def list_win5_dates(self, year: int) -> list[date]:
        """指定年の WIN5 開催日一覧を返す。

        https://race.netkeiba.com/top/win5_results.html?year=YYYY を取得し、
        win5.html?date=YYYYMMDD パターンを抽出・重複除去して date のリストで返す。
        """
        url = f"{NETKEIBA_RACE_URL}/top/win5_results.html?year={year}"
        try:
            html = self.fetch(url, encoding="euc-jp")
        except Exception as e:
            logger.error("Failed to fetch win5 date list for %d: %s", year, e)
            return []

        raw_dates = list(dict.fromkeys(re.findall(r"win5\.html\?date=(\d{8})", html)))
        dates: list[date] = []
        for d_str in raw_dates:
            try:
                dates.append(date(int(d_str[:4]), int(d_str[4:6]), int(d_str[6:8])))
            except ValueError:
                logger.warning("Invalid date string: %s", d_str)

        logger.info("WIN5 dates for %d: %d dates found", year, len(dates))
        return dates

    def get_win5_race_ids(self, target_date: date) -> list[str]:
        """Win5対象レースIDだけを返す（後方互換メソッド）"""
        event = self.scrape(target_date)
        if event is None:
            return []
        return [
            rid
            for rid in [
                event.race1_id,
                event.race2_id,
                event.race3_id,
                event.race4_id,
                event.race5_id,
            ]
            if rid
        ]
