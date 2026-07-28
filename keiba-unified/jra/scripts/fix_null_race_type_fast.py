"""NULLのrace_type/distanceを並列スクレイプで高速修復するスクリプト

ThreadPoolExecutorで5並列リクエスト、0.5秒間隔で処理する。
"""

import re
import sqlite3
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from bs4 import BeautifulSoup

sys.path.insert(0, ".")

from src.utils.config_loader import load_settings

settings = load_settings()
DB_PATH = "data/keiba.db"
RACE_URL = settings["scraping"]["race_url_template"]
HEADERS = {"User-Agent": settings["scraping"]["user_agent"]}
TIMEOUT = settings["scraping"]["timeout_sec"]

# 並列数とインターバル（アクセス制限回避のため控えめ設定）
WORKERS = 2
BATCH_SIZE = 20
BATCH_INTERVAL = 15  # バッチ間の待機秒数


def parse_race_detail(html_text):
    """HTMLからrace_type, distance, direction, track_condition, weatherを抽出"""
    soup = BeautifulSoup(html_text, "html.parser")

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

    dist_match = re.search(r"(芝|ダート|ダ|障害|障)\D*?(\d{3,4})m", detail_text)
    if dist_match:
        surface = dist_match.group(1)
        if surface == "ダ":
            surface = "ダート"
        elif surface == "障":
            surface = "障害"
        result["race_type"] = surface
        result["distance"] = int(dist_match.group(2))

    dir_match = re.search(r"(右|左|直線)", detail_text)
    if dir_match:
        result["direction"] = dir_match.group(1)

    weather_match = re.search(r"天候\s*[:：]\s*(\S+)", detail_text)
    if weather_match:
        result["weather"] = weather_match.group(1)

    cond_match = re.search(r"(?:芝|ダート?)\s*[:：]\s*(良|稍重|重|不良)", detail_text)
    if cond_match:
        result["track_condition"] = cond_match.group(1)

    return result


def fetch_one(race_id):
    """1レースを取得してパース結果を返す"""
    url = RACE_URL.format(race_id=race_id)
    try:
        resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        resp.encoding = resp.apparent_encoding or "utf-8"
        info = parse_race_detail(resp.text)
        return race_id, info, None
    except Exception as e:
        return race_id, None, str(e)


def main():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    cursor = conn.cursor()

    cursor.execute(
        "SELECT race_id FROM races WHERE race_type IS NULL ORDER BY race_id"
    )
    null_ids = [row[0] for row in cursor.fetchall()]
    total = len(null_ids)
    print(f"修復対象: {total} レース")
    print(f"並列数: {WORKERS}, バッチサイズ: {BATCH_SIZE}")

    success = 0
    fail = 0
    start_time = time.time()

    # バッチ処理
    for batch_start in range(0, total, BATCH_SIZE):
        batch = null_ids[batch_start : batch_start + BATCH_SIZE]

        with ThreadPoolExecutor(max_workers=WORKERS) as executor:
            futures = {executor.submit(fetch_one, rid): rid for rid in batch}

            for future in as_completed(futures):
                race_id, info, error = future.result()

                if error:
                    fail += 1
                    continue

                if info and info["race_type"]:
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
                    success += 1
                else:
                    fail += 1

        conn.commit()

        done = batch_start + len(batch)
        elapsed = time.time() - start_time
        rate = done / elapsed if elapsed > 0 else 0
        eta = (total - done) / rate / 60 if rate > 0 else 0
        print(
            f"  [{done}/{total}] success={success} fail={fail} "
            f"({rate:.1f}件/秒, 残り約{eta:.0f}分)"
        )

        # バッチ間の待機
        if batch_start + BATCH_SIZE < total:
            time.sleep(BATCH_INTERVAL)

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
    print("\n=== 修復後のrace_type分布 ===")
    cursor.execute(
        "SELECT race_type, COUNT(*) FROM races GROUP BY race_type ORDER BY race_type"
    )
    for row in cursor.fetchall():
        print(f"  {row[0] or 'NULL':10s}: {row[1]:,}")

    cursor.execute(
        "SELECT race_type, COUNT(*) FROM horse_history GROUP BY race_type ORDER BY race_type"
    )
    print("\n=== horse_history race_type分布 ===")
    for row in cursor.fetchall():
        print(f"  {row[0] or 'NULL':10s}: {row[1]:,}")

    conn.close()
    elapsed_total = time.time() - start_time
    print(f"\n完了: success={success}, fail={fail}, 所要時間={elapsed_total/60:.1f}分")


if __name__ == "__main__":
    main()
