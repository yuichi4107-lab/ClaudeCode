"""NULLのrace_type/distanceを再スクレイプで修復するスクリプト

原因: スクレイパーが「ダ右1700m」形式を「ダート」と認識できなかった
修正: race_result_scraper.pyの正規表現を修正済み。このスクリプトで
      NULLレースのみ再取得してDB更新する。
"""

import re
import sqlite3
import sys
import time

sys.path.insert(0, ".")

from src.scraper.scraper_utils import retry_request, parse_html
from src.utils.config_loader import load_settings
from src.utils.logger import setup_logger

logger = setup_logger(__name__)
settings = load_settings()

DB_PATH = "data/keiba.db"
RACE_URL = settings["scraping"]["race_url_template"]
INTERVAL = settings["scraping"]["request_interval_sec"]


def parse_race_detail(soup):
    """レースページからrace_type, distance, direction, track_condition, weatherを抽出"""
    detail_text = ""
    for span_tag in soup.select("dl.racedata span"):
        detail_text += span_tag.get_text(strip=True) + " "
    if not detail_text.strip():
        for span_tag in soup.select(".data_intro span"):
            detail_text += span_tag.get_text(strip=True) + " "

    result = {
        "race_type": None,
        "distance": None,
        "direction": None,
        "track_condition": None,
        "weather": None,
    }

    # 距離・コース種別
    dist_match = re.search(r"(芝|ダート|ダ|障害|障)\D*?(\d{3,4})m", detail_text)
    if dist_match:
        surface = dist_match.group(1)
        if surface == "ダ":
            surface = "ダート"
        elif surface == "障":
            surface = "障害"
        result["race_type"] = surface
        result["distance"] = int(dist_match.group(2))

    # 回り
    dir_match = re.search(r"(右|左|直線)", detail_text)
    if dir_match:
        result["direction"] = dir_match.group(1)

    # 天候
    weather_match = re.search(r"天候\s*[:：]\s*(\S+)", detail_text)
    if weather_match:
        result["weather"] = weather_match.group(1)

    # 馬場状態
    cond_match = re.search(r"(?:芝|ダート?)\s*[:：]\s*(良|稍重|重|不良)", detail_text)
    if cond_match:
        result["track_condition"] = cond_match.group(1)

    return result


def main():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    cursor = conn.cursor()

    # NULLレースを取得
    cursor.execute(
        "SELECT race_id FROM races WHERE race_type IS NULL ORDER BY race_id"
    )
    null_ids = [row[0] for row in cursor.fetchall()]
    total = len(null_ids)
    print(f"修復対象: {total} レース")

    success = 0
    fail = 0
    updated_race_ids = []

    for i, race_id in enumerate(null_ids):
        url = RACE_URL.format(race_id=race_id)
        try:
            resp = retry_request(url)
            resp.encoding = resp.apparent_encoding or "utf-8"
            soup = parse_html(resp.text)
            info = parse_race_detail(soup)

            if info["race_type"]:
                # racesテーブル更新
                cursor.execute(
                    """UPDATE races
                       SET race_type = ?, distance = ?, direction = ?,
                           track_condition = ?, weather = ?
                       WHERE race_id = ?""",
                    (
                        info["race_type"],
                        info["distance"],
                        info["direction"],
                        info["track_condition"],
                        info["weather"],
                        race_id,
                    ),
                )
                updated_race_ids.append((race_id, info["race_type"], info["distance"]))
                success += 1
            else:
                fail += 1
                logger.warning("Parse still failed for %s", race_id)

        except Exception as e:
            fail += 1
            logger.error("Error fetching %s: %s", race_id, e)

        # 進捗表示
        if (i + 1) % 50 == 0 or (i + 1) == total:
            conn.commit()
            print(
                f"  [{i+1}/{total}] success={success}, fail={fail}"
            )

        time.sleep(INTERVAL)

    conn.commit()

    # horse_historyテーブルも連動更新
    print("\nhorse_historyテーブルを連動更新中...")
    cursor.execute(
        """UPDATE horse_history
           SET race_type = (
               SELECT r.race_type FROM races r WHERE r.race_id = horse_history.race_id
           ),
           distance = (
               SELECT r.distance FROM races r WHERE r.race_id = horse_history.race_id
           )
           WHERE race_id IN (SELECT race_id FROM races WHERE race_type IS NOT NULL)
             AND (race_type IS NULL OR distance IS NULL)"""
    )
    history_updated = cursor.rowcount
    conn.commit()
    print(f"horse_history更新: {history_updated} 行")

    # 結果サマリ
    cursor.execute(
        "SELECT race_type, COUNT(*) FROM races GROUP BY race_type ORDER BY race_type"
    )
    print("\n=== 修復後のrace_type分布 ===")
    for row in cursor.fetchall():
        print(f"  {row[0] or 'NULL'}: {row[1]:,}")

    cursor.execute(
        "SELECT race_type, COUNT(*) FROM horse_history GROUP BY race_type ORDER BY race_type"
    )
    print("\n=== horse_history race_type分布 ===")
    for row in cursor.fetchall():
        print(f"  {row[0] or 'NULL'}: {row[1]:,}")

    conn.close()
    print(f"\n完了: success={success}, fail={fail}")


if __name__ == "__main__":
    main()
