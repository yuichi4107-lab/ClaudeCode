"""馬情報スクレイピングモジュール

netkeibaの馬ページから過去成績を抽出する。
"""

import re
from typing import Dict, List, Optional

from src.scraper.scraper_utils import retry_request, parse_html
from src.utils.config_loader import load_settings
from src.utils.logger import setup_logger

logger = setup_logger(__name__)

_settings = load_settings()
_horse_url_template = _settings["scraping"]["horse_url_template"]


def _parse_time_str(time_str: str) -> Optional[float]:
    """タイム文字列を秒数に変換する"""
    if not time_str or time_str.strip() == "":
        return None
    time_str = time_str.strip()
    match = re.match(r"(\d+):(\d+)\.(\d+)", time_str)
    if match:
        minutes = int(match.group(1))
        seconds = int(match.group(2))
        frac = int(match.group(3))
        return minutes * 60.0 + seconds + frac * 0.1
    match = re.match(r"(\d+\.\d+)", time_str)
    if match:
        return float(match.group(1))
    return None


def scrape_horse_history(horse_id: str) -> List[Dict]:
    """馬の過去成績を取得する

    Args:
        horse_id: 馬ID (e.g., '2019104308')

    Returns:
        List of dict representing each past race
    """
    url = _horse_url_template.format(horse_id=horse_id)
    logger.info("Scraping horse history: %s", url)

    try:
        resp = retry_request(url)
    except Exception as e:
        logger.error("Failed to fetch horse %s: %s", horse_id, e)
        return []

    resp.encoding = resp.apparent_encoding or "utf-8"
    soup = parse_html(resp.text)

    results = []
    table = soup.select_one("table.db_h_race_results")
    if not table:
        # 別のセレクタも試す
        table = soup.select_one("table.nk_tb_common")
    if not table:
        logger.warning("History table not found for horse %s", horse_id)
        return results

    rows = table.select("tr")
    for row in rows:
        cells = row.select("td")
        if len(cells) < 12:
            continue

        record = {"horse_id": horse_id}

        # 日付
        date_text = cells[0].get_text(strip=True)
        date_match = re.match(r"(\d{4})/(\d{2})/(\d{2})", date_text)
        if date_match:
            y, m, d = date_match.groups()
            record["race_date"] = f"{y}-{m}-{d}"
        else:
            record["race_date"] = None

        # 開催場
        record["venue_name"] = cells[1].get_text(strip=True)

        # race_id (リンクから取得)
        race_link = cells[4].select_one("a") if len(cells) > 4 else None
        record["race_id"] = None
        if race_link:
            href = race_link.get("href", "")
            match = re.search(r"/race/(\d{12})/", href)
            if match:
                record["race_id"] = match.group(1)

        # コース種別・距離
        course_text = cells[3].get_text(strip=True) if len(cells) > 3 else ""
        surface_match = re.match(r"(芝|ダート|障害)(\d+)", course_text)
        if surface_match:
            record["race_type"] = surface_match.group(1)
            record["distance"] = int(surface_match.group(2))
        else:
            record["race_type"] = None
            record["distance"] = None

        # 馬場状態
        if len(cells) > 9:
            record["track_condition"] = cells[9].get_text(strip=True) or None
        else:
            record["track_condition"] = None

        # 着順
        order_text = cells[11].get_text(strip=True) if len(cells) > 11 else ""
        try:
            record["finish_order"] = int(order_text)
        except ValueError:
            record["finish_order"] = None

        # 頭数
        count_text = cells[6].get_text(strip=True) if len(cells) > 6 else ""
        try:
            record["horse_count"] = int(count_text)
        except ValueError:
            record["horse_count"] = None

        # タイム
        time_text = cells[17].get_text(strip=True) if len(cells) > 17 else ""
        record["finish_time"] = _parse_time_str(time_text)

        # 上がり3F
        if len(cells) > 22:
            try:
                record["final_3f"] = float(cells[22].get_text(strip=True))
            except (ValueError, IndexError):
                record["final_3f"] = None
        else:
            record["final_3f"] = None

        # 馬体重
        if len(cells) > 23:
            weight_text = cells[23].get_text(strip=True)
            match = re.match(r"(\d+)", weight_text)
            record["horse_weight"] = int(match.group(1)) if match else None
        else:
            record["horse_weight"] = None

        # オッズ
        if len(cells) > 12:
            try:
                record["odds"] = float(cells[12].get_text(strip=True))
            except ValueError:
                record["odds"] = None
        else:
            record["odds"] = None

        # 人気
        if len(cells) > 13:
            try:
                record["popularity"] = int(cells[13].get_text(strip=True))
            except ValueError:
                record["popularity"] = None
        else:
            record["popularity"] = None

        # 騎手
        if len(cells) > 12:
            jockey_tag = cells[12].select_one("a")
            record["jockey_name"] = (
                jockey_tag.get_text(strip=True) if jockey_tag else None
            )
        else:
            record["jockey_name"] = None

        results.append(record)

    logger.info("Parsed %d history records for horse %s", len(results), horse_id)
    return results
