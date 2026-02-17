import logging
import re
from urllib.parse import urlencode

from bs4 import BeautifulSoup

from jra_predictor.scraper.base import BaseScraper
from jra_predictor.config.settings import JRA_VENUES

logger = logging.getLogger(__name__)

BASE_URL = "https://db.netkeiba.com/"


class RaceListScraper(BaseScraper):
    """指定年月・会場のレースIDリストを db.netkeiba.com から取得する（JRA中央競馬）。"""

    def get_race_ids_for_month(self, year: int, month: int) -> list[str]:
        """月別のレースID一覧を取得（ページネーション対応）。"""
        all_ids = set()
        page = 1
        max_pages = 10  # 安全上限

        while page <= max_pages:
            params = [
                ("pid", "race_list"),
                ("start_year", year),
                ("start_mon", month),
                ("end_year", year),
                ("end_mon", month),
                ("page", page),
                ("list", 100),
            ] + [("jyo[]", v) for v in JRA_VENUES]

            url = BASE_URL + "?" + urlencode(params)
            logger.info("Fetching JRA race list: %d/%02d (page %d)", year, month, page)
            html = self.get(url)
            page_ids = self._parse_race_ids(html)

            if not page_ids:
                break

            new_ids = set(page_ids) - all_ids
            all_ids.update(page_ids)

            # 次ページの有無を確認
            if not self._has_next_page(html) or not new_ids:
                break

            page += 1

        logger.info("Found %d JRA races for %d/%02d (%d pages)", len(all_ids), year, month, page)
        return list(all_ids)

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
            # 例: /race/202505030801/
            parts = [p for p in href.strip("/").split("/") if p]
            if parts and parts[-1].isdigit() and len(parts[-1]) == 12:
                rid = parts[-1]
                if rid[4:6] in JRA_VENUES:
                    race_ids.add(rid)
        return list(race_ids)

    @staticmethod
    def _has_next_page(html: str) -> bool:
        """ページネーションに「次」リンクがあるか判定する。"""
        soup = BeautifulSoup(html, "lxml")
        # db.netkeiba.com は pager クラスで次ページリンクを提供
        pager = soup.select_one(".pager")
        if pager:
            for a in pager.select("a"):
                text = a.get_text(strip=True)
                if "次" in text or ">" in text:
                    return True
        return False
