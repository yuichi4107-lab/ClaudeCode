"""レース結果ページスクレイピングモジュール

netkeiba.comのレース結果ページからレース情報・着順・払戻を抽出する。
"""

import re
from typing import Dict, List, Optional

from src.scraper.scraper_utils import retry_request, parse_html
from src.scraper.odds_scraper import extract_payoffs
from src.utils.config_loader import load_settings
from src.utils.constants import VENUE_CODES
from src.utils.logger import setup_logger

logger = setup_logger(__name__)

_settings = load_settings()
_race_url_template = _settings["scraping"]["race_url_template"]


def _parse_time_str(time_str: str) -> Optional[float]:
    """タイム文字列を秒数に変換する (e.g., '1:35.2' -> 95.2)"""
    if not time_str or time_str.strip() == "":
        return None
    time_str = time_str.strip()
    match = re.match(r"(\d+):(\d+)\.(\d+)", time_str)
    if match:
        minutes = int(match.group(1))
        seconds = int(match.group(2))
        frac = int(match.group(3))
        return minutes * 60.0 + seconds + frac * 0.1
    match = re.match(r"(\d+)\.(\d+)", time_str)
    if match:
        return float(time_str)
    return None


def _parse_horse_weight(weight_str: str):
    """馬体重文字列をパースする (e.g., '480(+4)' -> (480, 4))"""
    if not weight_str or weight_str.strip() == "":
        return None, None
    weight_str = weight_str.strip()
    match = re.match(r"(\d+)\(([+-]?\d+)\)", weight_str)
    if match:
        return int(match.group(1)), int(match.group(2))
    match = re.match(r"(\d+)", weight_str)
    if match:
        return int(match.group(1)), None
    return None, None


def _extract_id_from_href(href: str, pattern: str) -> Optional[str]:
    """hrefからIDを抽出する"""
    match = re.search(pattern, href)
    return match.group(1) if match else None


def _parse_race_info(soup, race_id: str) -> Dict:
    """レース情報ヘッダーをパースする"""
    info = {
        "race_id": race_id,
        "race_date": None,
        "venue_code": race_id[4:6],
        "venue_name": VENUE_CODES.get(race_id[4:6], ""),
        "kai": None,
        "nichi": None,
        "race_number": None,
        "race_name": None,
        "grade": None,
        "race_type": None,
        "distance": None,
        "direction": None,
        "track_condition": None,
        "weather": None,
        "horse_count": None,
        "prize_1st": None,
    }

    # race_idからkai, nichi, race_numberを抽出
    try:
        info["kai"] = int(race_id[6:8])
        info["nichi"] = int(race_id[8:10])
        info["race_number"] = int(race_id[10:12])
    except (ValueError, IndexError):
        pass

    # レース名
    race_name_tag = soup.select_one("dl.racedata h1") or soup.select_one(
        ".data_intro h1"
    )
    if race_name_tag:
        info["race_name"] = race_name_tag.get_text(strip=True)

    # グレード判定
    icon = soup.select_one("dl.racedata h1 img") or soup.select_one(
        ".data_intro h1 img"
    )
    if icon:
        alt = icon.get("alt", "").upper()
        for g in ["G1", "G2", "G3"]:
            if g in alt:
                info["grade"] = g
                break

    # レース詳細テキスト (dl.racedata内のspan)
    # 例: "芝左1400m / 天候 : 曇 / 芝 : 稍重  / 発走 : 15:30"
    detail_text = ""
    for span_tag in soup.select("dl.racedata span"):
        detail_text += span_tag.get_text(strip=True) + " "
    if not detail_text.strip():
        for span_tag in soup.select(".data_intro span"):
            detail_text += span_tag.get_text(strip=True) + " "

    # 距離・コース種別: "芝左1400m" or "ダート右1200m" or "ダ右1700m" or "芝1600m"
    dist_match = re.search(r"(芝|ダート|ダ|障害|障)\D*?(\d{3,4})m", detail_text)
    if dist_match:
        surface = dist_match.group(1)
        # 省略表記を正規化
        if surface == "ダ":
            surface = "ダート"
        elif surface == "障":
            surface = "障害"
        info["race_type"] = surface
        info["distance"] = int(dist_match.group(2))

    # 回り
    dir_match = re.search(r"(右|左|直線)", detail_text)
    if dir_match:
        info["direction"] = dir_match.group(1)

    # 天候: "天候 : 曇"
    weather_match = re.search(r"天候\s*[:：]\s*(\S+)", detail_text)
    if weather_match:
        info["weather"] = weather_match.group(1)

    # 馬場状態: "芝 : 稍重" or "ダート : 良"
    cond_match = re.search(r"(?:芝|ダート?)\s*[:：]\s*(良|稍重|重|不良)", detail_text)
    if cond_match:
        info["track_condition"] = cond_match.group(1)

    # 日付: "2024年06月23日" or "2024/06/23"
    date_tag = soup.select_one("p.smalltxt") or soup.select_one(
        ".data_intro p"
    )
    if date_tag:
        date_text = date_tag.get_text(strip=True)
        # "2024年06月23日" 形式
        date_match = re.search(
            r"(\d{4})年(\d{1,2})月(\d{1,2})日", date_text
        )
        if not date_match:
            # "2024/06/23" 形式
            date_match = re.search(
                r"(\d{4})/(\d{1,2})/(\d{1,2})", date_text
            )
        if date_match:
            y, m, d = date_match.groups()
            info["race_date"] = f"{y}-{int(m):02d}-{int(d):02d}"

        # グレード未取得の場合、テキストから推定
        if not info["grade"]:
            grade_text = date_tag.get_text(strip=True)
            if "オープン" in grade_text or "OP" in grade_text:
                info["grade"] = "オープン"

    # 頭数: 結果テーブルのデータ行数
    result_rows = soup.select("table.race_table_01 tr")
    data_rows = [
        r for r in result_rows
        if r.select("td") and not r.select("th")
    ]
    info["horse_count"] = len(data_rows) if data_rows else None

    return info


def _parse_results_table(soup, race_id: str) -> List[Dict]:
    """結果テーブルをパースする

    列マッピング (netkeiba db):
    [0]着順 [1]枠番 [2]馬番 [3]馬名 [4]性齢 [5]斤量
    [6]騎手 [7]タイム [8]着差 [9]ﾀｲﾑ指数 [10]通過 [11]上り
    [12]単勝 [13]人気 [14]馬体重 [15]調教ﾀｲﾑ [16]厩舎ｺﾒﾝﾄ
    [17]備考 [18]調教師 [19]馬主 [20]賞金(万円)
    """
    results = []
    table = soup.select_one("table.race_table_01")
    if not table:
        logger.warning("Result table not found for race %s", race_id)
        return results

    rows = table.select("tr")
    for row in rows:
        cells = row.select("td")
        if len(cells) < 15:
            continue

        result = {"race_id": race_id}

        # [0] 着順
        order_text = cells[0].get_text(strip=True)
        try:
            result["finish_order"] = int(order_text)
        except ValueError:
            result["finish_order"] = None

        # [1] 枠番
        try:
            result["frame_number"] = int(cells[1].get_text(strip=True))
        except ValueError:
            result["frame_number"] = None

        # [2] 馬番
        try:
            result["horse_number"] = int(cells[2].get_text(strip=True))
        except ValueError:
            result["horse_number"] = None

        # [3] 馬名・馬ID
        horse_link = cells[3].select_one("a")
        result["horse_name"] = cells[3].get_text(strip=True)
        result["horse_id"] = None
        if horse_link:
            result["horse_id"] = _extract_id_from_href(
                horse_link.get("href", ""), r"/horse/(\w+)/"
            )

        # [4] 性齢
        result["sex_age"] = cells[4].get_text(strip=True)

        # [5] 斤量
        try:
            result["weight_carry"] = float(cells[5].get_text(strip=True))
        except ValueError:
            result["weight_carry"] = None

        # [6] 騎手
        jockey_link = cells[6].select_one("a")
        result["jockey_name"] = cells[6].get_text(strip=True)
        result["jockey_id"] = None
        if jockey_link:
            result["jockey_id"] = _extract_id_from_href(
                jockey_link.get("href", ""), r"/jockey/(?:result/(?:recent/)?)?(\w+)/"
            )

        # [7] タイム
        result["finish_time"] = _parse_time_str(cells[7].get_text(strip=True))

        # [8] 着差
        result["margin"] = cells[8].get_text(strip=True) or None

        # [10] 通過順
        result["corner_positions"] = cells[10].get_text(strip=True) or None

        # [11] 上がり3F
        try:
            result["final_3f"] = float(cells[11].get_text(strip=True))
        except (ValueError, IndexError):
            result["final_3f"] = None

        # [12] 単勝オッズ
        try:
            result["odds"] = float(cells[12].get_text(strip=True))
        except (ValueError, IndexError):
            result["odds"] = None

        # [13] 人気
        try:
            result["popularity"] = int(cells[13].get_text(strip=True))
        except (ValueError, IndexError):
            result["popularity"] = None

        # [14] 馬体重
        weight_text = cells[14].get_text(strip=True)
        w, wc = _parse_horse_weight(weight_text)
        result["horse_weight"] = w
        result["weight_change"] = wc

        # [18] 調教師
        result["trainer_name"] = None
        result["trainer_id"] = None
        if len(cells) > 18:
            trainer_link = cells[18].select_one("a")
            if trainer_link:
                # "[東]手塚貴久" -> "手塚貴久" (所属を除去)
                raw_name = trainer_link.get_text(strip=True)
                result["trainer_name"] = re.sub(r"^\[.+?\]", "", raw_name)
                result["trainer_id"] = _extract_id_from_href(
                    trainer_link.get("href", ""),
                    r"/trainer/(?:result/(?:recent/)?)?(\w+)/",
                )

        results.append(result)

    logger.info("Parsed %d results for race %s", len(results), race_id)
    return results


def scrape_race(race_id: str) -> Optional[Dict]:
    """レース結果ページをスクレイピングして全データを返す

    Args:
        race_id: 12桁のレースID (YYYYPPNNDDRR)

    Returns:
        dict with keys: race_info, results, payoffs
        or None if request fails
    """
    url = _race_url_template.format(race_id=race_id)
    logger.info("Scraping race: %s", url)

    try:
        resp = retry_request(url)
    except Exception as e:
        logger.error("Failed to fetch race %s: %s", race_id, e)
        return None

    # netkeibaはEUC-JPエンコーディングの場合がある
    resp.encoding = resp.apparent_encoding or "utf-8"
    soup = parse_html(resp.text)

    race_info = _parse_race_info(soup, race_id)
    results = _parse_results_table(soup, race_id)
    payoffs = extract_payoffs(soup, race_id)

    # horse_countが取れなかった場合、結果行数で補完
    if not race_info.get("horse_count") and results:
        race_info["horse_count"] = len(results)

    return {
        "race_info": race_info,
        "results": results,
        "payoffs": payoffs,
    }
