"""レースID一覧の取得"""

import logging
import re
from datetime import date, timedelta

from scraper.base import BaseScraper
from config.settings import NETKEIBA_BASE_URL

logger = logging.getLogger(__name__)


class RaceListScraper(BaseScraper):
    """開催日のレースID一覧を取得する"""

    def get_race_ids_by_date(self, target_date: date) -> list[str]:
        """指定日の全レースIDを取得する"""
        url = f"{NETKEIBA_BASE_URL}/?pid=race_list&date={target_date.strftime('%Y%m%d')}"
        soup = self.fetch_and_parse(url)
        race_ids = []

        # レースリンクからrace_idを抽出
        for link in soup.select("a[href*='/race/']"):
            href = link.get("href", "")
            match = re.search(r"/race/(\d{12})/", href)
            if match:
                race_id = match.group(1)
                if race_id not in race_ids:
                    race_ids.append(race_id)

        logger.info("Found %d races on %s", len(race_ids), target_date)
        return sorted(race_ids)

    def get_kaisai_dates(self, year: int, month: int) -> list[date]:
        """指定年月の開催日一覧を取得する"""
        url = f"{NETKEIBA_BASE_URL}/?pid=race_top&date={year:04d}{month:02d}01"
        soup = self.fetch_and_parse(url)
        dates = []

        # カレンダーから開催日を抽出
        for link in soup.select("a[href*='date=']"):
            href = link.get("href", "")
            match = re.search(r"date=(\d{8})", href)
            if match:
                d = match.group(1)
                try:
                    dt = date(int(d[:4]), int(d[4:6]), int(d[6:8]))
                    if dt not in dates:
                        dates.append(dt)
                except ValueError:
                    continue

        # 開催日のみ(土日+祝日)をフィルタ
        return sorted(dates)

    def get_race_ids_in_range(
        self, start: date, end: date
    ) -> dict[date, list[str]]:
        """日付範囲のレースIDを取得する"""
        result: dict[date, list[str]] = {}
        current = start
        while current <= end:
            # 開催日(土日)のみ対象
            if current.weekday() in (5, 6):  # 土曜=5, 日曜=6
                race_ids = self.get_race_ids_by_date(current)
                if race_ids:
                    result[current] = race_ids
            current += timedelta(days=1)
        return result
