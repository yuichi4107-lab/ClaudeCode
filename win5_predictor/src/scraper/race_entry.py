"""出馬表(未来レース)の取得"""

import logging
import re

from bs4 import BeautifulSoup

from config.settings import NETKEIBA_RACE_URL
from database.models import RaceResult
from scraper.base import BaseScraper

logger = logging.getLogger(__name__)


class RaceEntryScraper(BaseScraper):
    """出馬表ページをスクレイピングする(レース前のエントリー情報)"""

    def scrape(self, race_id: str) -> list[RaceResult]:
        """出馬表を取得する。RaceResultオブジェクトに格納(着順等は空)"""
        url = f"{NETKEIBA_RACE_URL}/race/shutuba.html?race_id={race_id}"
        try:
            soup = self.fetch_and_parse(url, encoding="euc-jp")
        except Exception as e:
            logger.error("Failed to scrape entry for %s: %s", race_id, e)
            return []

        return self._parse_entry_table(soup, race_id)

    def _parse_entry_table(
        self, soup: BeautifulSoup, race_id: str
    ) -> list[RaceResult]:
        """出馬表テーブルをパースする"""
        entries = []
        table = soup.select_one("table.Shutuba_Table, table.race_table_01")
        if table is None:
            logger.warning("No entry table found for %s", race_id)
            return entries

        rows = table.select("tr")[1:]
        for row in rows:
            try:
                entry = self._parse_entry_row(row, race_id)
                if entry:
                    entries.append(entry)
            except Exception as e:
                logger.debug("Failed to parse entry row: %s", e)

        return entries

    def _parse_entry_row(
        self, row: BeautifulSoup, race_id: str
    ) -> RaceResult | None:
        cells = row.select("td")
        if len(cells) < 8:
            return None

        # 枠番
        post_position = _safe_int(cells[0].get_text(strip=True))

        # 馬番
        horse_number = _safe_int(cells[1].get_text(strip=True))
        if horse_number == 0:
            return None

        # 馬名・horse_id
        horse_link = cells[3].select_one("a[href*='/horse/']")
        horse_name = cells[3].get_text(strip=True)
        horse_id = ""
        if horse_link:
            href = horse_link.get("href", "")
            m = re.search(r"/horse/(\w+)", href)
            if m:
                horse_id = m.group(1)

        # 性齢
        sex_age_text = cells[4].get_text(strip=True)
        sex = sex_age_text[0] if sex_age_text else ""
        age = _safe_int(sex_age_text[1:]) if len(sex_age_text) > 1 else 0

        # 斤量
        weight_carried = _safe_float(cells[5].get_text(strip=True)) or 0.0

        # 騎手
        jockey_link = cells[6].select_one("a[href*='/jockey/']")
        jockey_name = cells[6].get_text(strip=True)
        jockey_id = ""
        if jockey_link:
            href = jockey_link.get("href", "")
            m = re.search(r"/jockey/(\w+)", href)
            if m:
                jockey_id = m.group(1)

        # 調教師
        trainer_id = ""
        trainer_name = ""
        if len(cells) > 7:
            trainer_link = cells[7].select_one("a[href*='/trainer/']")
            trainer_name = cells[7].get_text(strip=True)
            if trainer_link:
                href = trainer_link.get("href", "")
                m = re.search(r"/trainer/(\w+)", href)
                if m:
                    trainer_id = m.group(1)

        # 馬体重(前走)
        horse_weight = None
        weight_change = None
        if len(cells) > 8:
            wt_text = cells[8].get_text(strip=True)
            wt_match = re.match(r"(\d+)\(([+-]?\d+)\)", wt_text)
            if wt_match:
                horse_weight = int(wt_match.group(1))
                weight_change = int(wt_match.group(2))

        return RaceResult(
            race_id=race_id,
            horse_id=horse_id,
            horse_name=horse_name,
            post_position=post_position,
            horse_number=horse_number,
            sex=sex,
            age=age,
            weight_carried=weight_carried,
            jockey_id=jockey_id,
            jockey_name=jockey_name,
            trainer_id=trainer_id,
            trainer_name=trainer_name,
            horse_weight=horse_weight,
            weight_change=weight_change,
        )


def _safe_int(text: str) -> int:
    try:
        return int(text)
    except (ValueError, TypeError):
        return 0


def _safe_float(text: str) -> float | None:
    try:
        return float(text)
    except (ValueError, TypeError):
        return None
