import logging
from urllib.parse import urlencode

from bs4 import BeautifulSoup

from nankan_predictor.scraper.base import BaseScraper
from nankan_predictor.config.settings import NANKAN_VENUES

logger = logging.getLogger(__name__)

BASE_URL = "https://db.netkeiba.com/"


class RaceListScraper(BaseScraper):
    """指定年月・会場のレースIDリストを db.netkeiba.com から取得する。"""

    def get_race_ids_for_month(self, year: int, month: int) -> list[str]:
        params = [
            ("pid", "race_list"),
            ("start_year", year),
            ("start_mon", month),
            ("end_year", year),
            ("end_mon", month),
            ("list", 200),
        ] + [("jyo[]", v) for v in NANKAN_VENUES]

        url = BASE_URL + "?" + urlencode(params)
        logger.info("Fetching race list: %d/%02d", year, month)
        html = self.get(url)
        race_ids = self._parse_race_ids(html)
        logger.info("Found %d races for %d/%02d", len(race_ids), year, month)
        return race_ids

    def get_race_ids_for_date(
        self, date_str: str, venue_code: str = None
    ) -> list[str]:
        """date_str: 'YYYYMMDD' or 'YYYY-MM-DD'"""
        date_str = date_str.replace("-", "")
        year = int(date_str[:4])
        month = int(date_str[4:6])
        day = date_str[4:8]

        all_ids = self.get_race_ids_for_month(year, month)
        # レースIDの日付部分（インデックス6:10）でフィルタ
        filtered = [r for r in all_ids if r[6:10] == day]
        if venue_code:
            filtered = [r for r in filtered if r[4:6] == venue_code]
        return filtered

    def _parse_race_ids(self, html: str) -> list[str]:
        soup = BeautifulSoup(html, "lxml")
        race_ids = set()
        for a in soup.select("a[href*='/race/']"):
            href = a.get("href", "")
            # 例: /race/202645020601/
            parts = [p for p in href.strip("/").split("/") if p]
            if parts and parts[-1].isdigit() and len(parts[-1]) == 12:
                rid = parts[-1]
                if rid[4:6] in NANKAN_VENUES:
                    race_ids.add(rid)
        return list(race_ids)
