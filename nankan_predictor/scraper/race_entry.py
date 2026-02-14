import logging
import re

from bs4 import BeautifulSoup

from nankan_predictor.scraper.base import BaseScraper
from nankan_predictor.config.settings import VENUE_NAMES

logger = logging.getLogger(__name__)

BASE_URL = "https://nar.netkeiba.com/race/shutuba.html"


def _safe_int(s):
    try:
        return int(str(s).strip())
    except (ValueError, TypeError):
        return None


def _safe_float(s):
    try:
        return float(str(s).strip())
    except (ValueError, TypeError):
        return None


def _extract_id(href: str, kind: str) -> str:
    parts = [p for p in href.strip("/").split("/") if p]
    if len(parts) >= 2 and parts[0] == kind:
        return parts[1]
    if len(parts) >= 3 and parts[1] == kind:
        return parts[2]
    # クエリパラメータ形式: ?horse_id=xxxx
    if f"{kind}_id=" in href:
        m = re.search(rf"{kind}_id=(\w+)", href)
        if m:
            return m.group(1)
    return ""


class RaceEntryScraper(BaseScraper):
    """nar.netkeiba.com の出馬表ページから出走馬情報を取得する。"""

    def scrape(self, race_id: str) -> dict:
        logger.info("Scraping shutuba: %s", race_id)
        html = self.get(BASE_URL, params={"race_id": race_id})
        soup = BeautifulSoup(html, "lxml")
        return {
            "race_info": self._parse_race_info(soup, race_id),
            "entries": self._parse_shutuba_table(soup, race_id),
        }

    def _parse_race_info(self, soup: BeautifulSoup, race_id: str) -> dict:
        info = {
            "race_id": race_id,
            "venue_code": race_id[4:6],
            "venue_name": VENUE_NAMES.get(race_id[4:6], race_id[4:6]),
            "race_date": f"{race_id[0:4]}-{race_id[6:8]}-{race_id[8:10]}",
            "race_number": _safe_int(race_id[10:12]),
        }

        race_name_el = soup.select_one(".RaceName, .race_name, h1.race_name")
        if race_name_el:
            info["race_name"] = race_name_el.get_text(strip=True)

        data_el = soup.select_one(".RaceData01, .race_data")
        if data_el:
            text = data_el.get_text()
            m = re.search(r"(ダ|芝)(\d+)m", text)
            if m:
                info["track_type"] = "ダート" if m.group(1) == "ダ" else "芝"
                info["distance"] = int(m.group(2))

        return info

    def _parse_shutuba_table(self, soup: BeautifulSoup, race_id: str) -> list[dict]:
        entries = []
        table = soup.select_one("table.Shutuba_Table, table.shutuba_table, .race_table_01")
        if not table:
            logger.warning("Shutuba table not found for race_id=%s", race_id)
            return entries
        # detect header columns to support variations
        header = table.select_one("tr")
        header_texts = [h.get_text(strip=True) for h in header.select("th, td")] if header else []

        def find_col(keywords: list[str]) -> int | None:
            for i, txt in enumerate(header_texts):
                for k in keywords:
                    if k in txt:
                        return i
            return None

        weight_idx = find_col(["馬体重", "馬体", "体重"])
        pop_idx = find_col(["人気", "人"])

        for tr in table.select("tr.HorseList, tr[class*='HorseList']"):
            tds = tr.select("td")
            if len(tds) < 2:
                continue

            entry: dict = {"race_id": race_id}
            entry["gate_number"] = _safe_int(tds[0].get_text(strip=True))
            entry["horse_number"] = _safe_int(tds[1].get_text(strip=True))

            horse_a = tr.select_one("td.Horse_Name a, .horsename a")
            if horse_a:
                entry["horse_name"] = horse_a.get_text(strip=True)
                entry["horse_id"] = _extract_id(horse_a.get("href", ""), "horse")

            jockey_a = tr.select_one("td.Jockey a, .jockeyname a")
            if jockey_a:
                entry["jockey_name"] = jockey_a.get_text(strip=True)
                entry["jockey_id"] = _extract_id(jockey_a.get("href", ""), "jockey")

            weight_el = tr.select_one("td.Weight")
            if weight_el:
                entry["weight_carried"] = _safe_float(weight_el.get_text(strip=True))

            # horse weight: prefer detected column, fall back to specific selectors
            if weight_idx is not None and weight_idx < len(tds):
                wt = tds[weight_idx].get_text(strip=True)
                wm = re.match(r"(\d+)\(([+-]?\d+)\)", wt)
                if wm:
                    entry["horse_weight"] = int(wm.group(1))
                    entry["weight_change"] = int(wm.group(2))
            else:
                horse_weight_el = tr.select_one("td.HorseWeight span, .horse_weight span, .weight span")
                if horse_weight_el:
                    wtext = horse_weight_el.get_text(strip=True)
                    wm = re.match(r"(\d+)\(([+-]?\d+)\)", wtext)
                    if wm:
                        entry["horse_weight"] = int(wm.group(1))
                        entry["weight_change"] = int(wm.group(2))

            # popularity
            if pop_idx is not None and pop_idx < len(tds):
                entry["popularity_rank"] = _safe_int(tds[pop_idx].get_text(strip=True))
            else:
                pop_el = tr.select_one(".Popular, .popularity, td.popularity")
                if pop_el:
                    entry["popularity_rank"] = _safe_int(pop_el.get_text(strip=True))

            entry["is_winner"] = None  # レース前なので未確定
            entries.append(entry)

        return entries
