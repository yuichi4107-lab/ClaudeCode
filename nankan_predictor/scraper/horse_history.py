import logging
import re

from bs4 import BeautifulSoup

from nankan_predictor.scraper.base import BaseScraper

logger = logging.getLogger(__name__)

BASE_URL = "https://db.netkeiba.com/horse/result/{horse_id}/"


def _safe_int(s):
    try:
        return int(str(s).strip().replace(",", ""))
    except (ValueError, TypeError):
        return None


def _safe_float(s):
    try:
        return float(str(s).strip().replace(",", ""))
    except (ValueError, TypeError):
        return None


def _parse_time(s: str):
    s = str(s).strip()
    m = re.match(r"(?:(\d+):)?(\d+)\.(\d+)", s)
    if not m:
        return None
    minutes = int(m.group(1) or 0)
    seconds = int(m.group(2))
    tenths = int(m.group(3))
    return minutes * 60 + seconds + tenths / 10


def _parse_date(s: str):
    """'2024/12/25' -> '2024-12-25'"""
    s = str(s).strip()
    m = re.match(r"(\d{4})[/\-.](\d{1,2})[/\-.](\d{1,2})", s)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    return None


class HorseHistoryScraper(BaseScraper):
    """db.netkeiba.com/horse/result/{horse_id}/ から馬の過去成績を取得する。"""

    def scrape(self, horse_id: str) -> list[dict]:
        url = BASE_URL.format(horse_id=horse_id)
        logger.info("Scraping horse history: %s", horse_id)
        html = self.get(url)
        soup = BeautifulSoup(html, "lxml")
        return self._parse_history_table(soup, horse_id)

    def _parse_history_table(self, soup: BeautifulSoup, horse_id: str) -> list[dict]:
        rows = []
        table = soup.select_one("table.db_h_race_results, table.race_table_01")
        if not table:
            logger.warning("History table not found for horse_id=%s", horse_id)
            return rows

        headers = [th.get_text(strip=True) for th in table.select("tr th")]

        for tr in table.select("tr")[1:]:
            tds = tr.select("td")
            if len(tds) < 10:
                continue

            row: dict = {}

            # 列インデックスは実際のHTMLに依存するため、ヘッダーで判断できる場合は使う
            # 標準的な db.netkeiba.com の馬成績テーブルの列順:
            # 0:日付 1:競馬場 2:天候 3:レース名 4:映像 5:頭数 6:枠 7:馬番
            # 8:オッズ 9:人気 10:着順 11:騎手 12:斤量 13:距離 14:馬場
            # 15:馬場指数 16:タイム 17:着差 18:タイム指数 19:通過 20:ペース
            # 21:上り 22:馬体重 23:厩舎評価 24:賞金
            try:
                row["race_date"] = _parse_date(tds[0].get_text(strip=True))
                if not row["race_date"]:
                    continue
                row["venue_name"] = tds[1].get_text(strip=True)
                row["race_name"] = tds[3].get_text(strip=True)
                row["field_size"] = _safe_int(tds[5].get_text(strip=True))
                row["gate_number"] = _safe_int(tds[6].get_text(strip=True))
                row["horse_number"] = _safe_int(tds[7].get_text(strip=True))
                row["popularity_rank"] = _safe_int(tds[9].get_text(strip=True))
                row["finish_position"] = _safe_int(tds[10].get_text(strip=True))
                row["jockey_name"] = tds[11].get_text(strip=True)
                row["weight_carried"] = _safe_float(tds[12].get_text(strip=True))

                # 距離と馬場種別: "ダ1400" や "芝1600" など
                dist_text = tds[13].get_text(strip=True) if len(tds) > 13 else ""
                dm = re.match(r"[ダ芝障]?(\d+)", dist_text)
                row["distance"] = int(dm.group(1)) if dm else None

                row["finish_time"] = _parse_time(tds[16].get_text(strip=True)) if len(tds) > 16 else None
                row["margin"] = tds[17].get_text(strip=True) if len(tds) > 17 else None
                row["passing_positions"] = tds[19].get_text(strip=True) if len(tds) > 19 else None
                row["pace"] = tds[20].get_text(strip=True) if len(tds) > 20 else None

                # 馬体重: "456(+2)"
                if len(tds) > 22:
                    wtext = tds[22].get_text(strip=True)
                    wm = re.match(r"(\d+)\(([+-]?\d+)\)", wtext)
                    row["horse_weight"] = int(wm.group(1)) if wm else _safe_int(wtext)
                else:
                    row["horse_weight"] = None

                rows.append(row)
            except IndexError:
                continue

        return rows
