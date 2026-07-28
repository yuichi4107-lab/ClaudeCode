"""レースID一覧スクレイピングモジュール

race.netkeiba.comのカレンダーページから開催日を取得し、
db.netkeiba.comのレース一覧ページからレースIDを収集する。
"""

import re
from typing import List

from src.scraper.scraper_utils import retry_request, parse_html
from src.utils.config_loader import load_settings
from src.utils.logger import setup_logger

logger = setup_logger(__name__)

_settings = load_settings()
_base_url = _settings["scraping"]["base_url"]  # https://db.netkeiba.com


def _scrape_kaisai_dates_for_month(year: int, month: int) -> List[str]:
    """指定年月の開催日一覧を取得する

    race.netkeiba.comのカレンダーページから開催日リンクを抽出する。

    Returns:
        List of date strings in YYYYMMDD format
    """
    url = f"https://race.netkeiba.com/top/calendar.html?year={year}&month={month}"
    logger.info("Fetching kaisai calendar: %s", url)

    try:
        resp = retry_request(url)
    except Exception:
        logger.error("Failed to fetch kaisai page: %s", url)
        return []

    soup = parse_html(resp.text)
    dates = []

    # カレンダーページから kaisai_date パラメータ付きリンクを抽出
    for a_tag in soup.find_all("a", href=True):
        href = a_tag["href"]
        match = re.search(r"kaisai_date=(\d{8})", href)
        if match:
            date_str = match.group(1)
            # 指定年月のデータのみ取得
            if date_str.startswith(f"{year}{month:02d}"):
                dates.append(date_str)

    dates = sorted(set(dates))
    logger.info("Found %d kaisai dates in %d/%02d", len(dates), year, month)
    return dates


def _scrape_race_ids_for_date(date_str: str) -> List[str]:
    """指定日のレースID一覧を取得する

    db.netkeiba.comのレース一覧ページからレースIDを抽出する。

    Args:
        date_str: YYYYMMDD format

    Returns:
        List of race IDs (YYYYPPNNDDRR format)
    """
    url = f"{_base_url}/race/list/{date_str}/"
    logger.info("Fetching race list: %s", url)

    try:
        resp = retry_request(url)
    except Exception:
        logger.error("Failed to fetch race list: %s", url)
        return []

    soup = parse_html(resp.text)
    race_ids = []

    for a_tag in soup.find_all("a", href=True):
        href = a_tag["href"]
        match = re.search(r"/race/(\d{12})/", href)
        if match:
            race_ids.append(match.group(1))

    race_ids = sorted(set(race_ids))
    logger.info("Found %d races on %s", len(race_ids), date_str)
    return race_ids


def scrape_race_ids_for_year(year: int) -> List[str]:
    """指定年の全レースIDを取得する

    Args:
        year: 対象年 (e.g., 2024)

    Returns:
        List of race IDs sorted
    """
    logger.info("Scraping race IDs for year %d", year)
    all_race_ids = []

    for month in range(1, 13):
        dates = _scrape_kaisai_dates_for_month(year, month)
        for date_str in dates:
            race_ids = _scrape_race_ids_for_date(date_str)
            all_race_ids.extend(race_ids)

    all_race_ids = sorted(set(all_race_ids))
    logger.info("Total %d race IDs for year %d", len(all_race_ids), year)
    return all_race_ids


def scrape_race_ids_for_years(years: List[int]) -> List[str]:
    """複数年のレースIDを取得する"""
    all_ids = []
    for year in years:
        ids = scrape_race_ids_for_year(year)
        all_ids.extend(ids)
    return sorted(set(all_ids))
