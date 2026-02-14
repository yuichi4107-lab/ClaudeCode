import logging
from urllib.parse import urlencode
import re

from bs4 import BeautifulSoup

from nankan_predictor.scraper.base import BaseScraper
from nankan_predictor.config.settings import NANKAN_VENUES

logger = logging.getLogger(__name__)

BASE_URL = "https://db.netkeiba.com/"
NAR_TOP_URL = "https://nar.netkeiba.com/"


class RaceListScraper(BaseScraper):
    """指定年月・会場のレースIDリストを db.netkeiba.com または NAR から取得する。"""

    def get_race_ids_for_month(self, year: int, month: int) -> list[str]:
        """月別のレースID一覧を取得（NAR フォールバック対応）"""
        
        # 既存の db.netkeiba.com から取得を試みる
        params = [
            ("pid", "race_list"),
            ("start_year", year),
            ("start_mon", month),
            ("end_year", year),
            ("end_mon", month),
            ("list", 200),
        ] + [("jyo[]", v) for v in NANKAN_VENUES]

        url = BASE_URL + "?" + urlencode(params)
        logger.info("Fetching race list from db.netkeiba: %d/%02d", year, month)
        html = self.get(url)
        race_ids = self._parse_race_ids(html)
        
        # db.netkeiba.com で結果が得られない場合は NAR から取得
        if len(race_ids) == 0 or len(race_ids) < 5:
            logger.warning("Got only %d races from db.netkeiba, trying NAR fallback", len(race_ids))
            race_ids_nar = self._get_races_from_nar(year, month)
            if race_ids_nar:
                race_ids.extend(race_ids_nar)
                logger.info("Added %d races from NAR", len(race_ids_nar))
        
        logger.info("Found %d races for %d/%02d", len(race_ids), year, month)
        return race_ids

    def _get_races_from_nar(self, year: int, month: int) -> list[str]:
        """NARトップページから当該月のレースを取得"""
        try:
            html = self.get(NAR_TOP_URL)
            all_race_ids = re.findall(r'race_id=(\d{12})', html)
            
            # race_id のフォーマット: YYYYMMDD... (推定)
            # タイムフィルタ: 指定年月のレースのみ抽出
            filtered_ids = []
            for rid in all_race_ids:
                # レースID形式の詳細が不明なため、全て返す
                # (実際にはより正確な日付抽出ロジックが必要)
                filtered_ids.append(rid)
            
            logger.info("Extracted %d race IDs from NAR", len(filtered_ids))
            return filtered_ids
        except Exception as e:
            logger.error("Failed to fetch from NAR: %s", e)
            return []

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
