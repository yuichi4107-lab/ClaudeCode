# -*- coding: utf-8 -*-
"""db.netkeiba から欠損フィールドのみを補完するエンリッチスクリプト

対象（UPDATEのみ・INSERTしない＝重複ゼロ・既存値は上書きしない）:
  - races.track_condition / weather / start_time が空のレース
  - results.passing / last_3f が空の確定済みレース

背景（2026-07-08発見）:
  - track_condition は初期構築(〜2026-03-15)以降、日次パイプラインが一度も
    書いておらず4か月分が空 → 馬場状態特徴量が実質無効化していた
  - ライブ経路(scrape_result_live_netkeiba)は着順しか書かないため、
    ライブで確定した開催日(主に土曜9日分)の passing / last_3f が丸ごと欠損
    → 脚質系特徴量(early_pace等)が劣化していた

使い方:
  python3 enrich_results.py --since 2026-03-16          # 期間指定バックフィル
  python3 enrich_results.py --days 8                    # 直近8日（週次cron用）
  python3 enrich_results.py --since 2026-03-16 --dry-run
"""
import argparse
import os
import re
import sqlite3
import sys
import time
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(__file__))
import requests
from bs4 import BeautifulSoup
from scraper_legacy import HEADERS, _decode_result_html

DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                  "data", "keiba_live.db")
INTERVAL = 1.2


def fetch_page(race_id):
    url = f"https://db.netkeiba.com/race/{race_id}/"
    res = requests.get(url, headers=HEADERS, timeout=15)
    if res.status_code != 200:
        return None
    return BeautifulSoup(_decode_result_html(res.content), "lxml")


def parse_race_info(soup):
    """レース情報欄から 馬場状態・天候・発走時刻 を抜く"""
    info = soup.find("div", class_="data_intro")
    if not info:
        return {}
    span = info.find("span")
    text = span.text.strip() if span else ""
    out = {}
    m = re.search(r'(芝|ダート|ダ|障)\s*:\s*(良|稍重|重|不良)', text)
    if m:
        out["track_condition"] = m.group(2)
    m = re.search(r'天候\s*:\s*(\S+?)\s*/', text)
    if m:
        out["weather"] = m.group(1)
    m = re.search(r'発走\s*:\s*(\d{1,2}:\d{2})', text)
    if m:
        out["start_time"] = m.group(1)
    return out


def parse_passing(soup):
    """結果テーブルから {馬番: (passing, last_3f)} を抜く"""
    table = soup.find("table", class_=re.compile("race_table_01"))
    if not table:
        return {}
    out = {}
    for row in table.find_all("tr")[1:]:
        tds = row.find_all("td")
        if len(tds) < 12:
            continue
        try:
            umaban = int(tds[2].text.strip())
        except ValueError:
            continue
        passing = tds[10].text.strip()
        try:
            last_3f = float(tds[11].text.strip())
        except ValueError:
            last_3f = None
        if passing or last_3f is not None:
            out[umaban] = (passing or None, last_3f)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since")
    ap.add_argument("--days", type=int)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    if args.days:
        since = (date.today() - timedelta(days=args.days)).strftime("%Y-%m-%d")
    elif args.since:
        since = args.since
    else:
        ap.error("--since か --days を指定")
    until = (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")  # 当日は未確定なので除外

    conn = sqlite3.connect(DB)
    c = conn.cursor()

    # 対象レース: 馬場状態が空 or passing欠損(確定済みのみ)
    c.execute("""SELECT DISTINCT ra.race_id FROM races ra
                 WHERE ra.date BETWEEN ? AND ?
                   AND (ra.track_condition IS NULL OR ra.track_condition = ''
                        OR EXISTS (SELECT 1 FROM results r WHERE r.race_id = ra.race_id
                                   AND r.finish_position > 0
                                   AND (r.passing IS NULL OR r.passing = '')))
                 ORDER BY ra.race_id""", (since, until))
    targets = [r[0] for r in c.fetchall()]
    if args.limit:
        targets = targets[:args.limit]
    print(f"対象レース: {len(targets)}件（{since}〜{until}）")
    if args.dry_run or not targets:
        conn.close()
        return

    upd_race = upd_pass = fail = 0
    for i, rid in enumerate(targets):
        try:
            soup = fetch_page(rid)
        except Exception as e:
            print(f"  fetch error {rid}: {e}")
            fail += 1
            time.sleep(INTERVAL)
            continue
        if soup is None:
            fail += 1
            time.sleep(INTERVAL)
            continue
        info = parse_race_info(soup)
        if info.get("track_condition"):
            c.execute("""UPDATE races SET
                           track_condition = CASE WHEN track_condition IS NULL OR track_condition = ''
                                                  THEN ? ELSE track_condition END,
                           weather = CASE WHEN weather IS NULL OR weather = '' THEN ? ELSE weather END,
                           start_time = CASE WHEN start_time IS NULL OR start_time = '' THEN ? ELSE start_time END
                         WHERE race_id = ?""",
                      (info.get("track_condition"), info.get("weather"), info.get("start_time"), rid))
            if c.rowcount:
                upd_race += 1
        for umaban, (passing, last_3f) in parse_passing(soup).items():
            c.execute("""UPDATE results SET
                           passing = CASE WHEN passing IS NULL OR passing = '' THEN ? ELSE passing END,
                           last_3f = CASE WHEN last_3f IS NULL THEN ? ELSE last_3f END
                         WHERE race_id = ? AND horse_number = ?""",
                      (passing, last_3f, rid, umaban))
            if c.rowcount:
                upd_pass += 1
        if (i + 1) % 50 == 0:
            conn.commit()
            print(f"  {i+1}/{len(targets)} 処理済 (races更新{upd_race} / passing更新{upd_pass}行 / 失敗{fail})", flush=True)
        time.sleep(INTERVAL)
    conn.commit()

    # 事後カバレッジ
    c.execute("""SELECT COUNT(*), SUM(CASE WHEN track_condition != '' AND track_condition IS NOT NULL THEN 1 ELSE 0 END)
                 FROM races WHERE date BETWEEN ? AND ?""", (since, until))
    tot, cond = c.fetchone()
    c.execute("""SELECT COUNT(*), SUM(CASE WHEN r.passing != '' AND r.passing IS NOT NULL THEN 1 ELSE 0 END)
                 FROM results r JOIN races ra ON ra.race_id = r.race_id
                 WHERE ra.date BETWEEN ? AND ? AND r.finish_position > 0""", (since, until))
    rtot, rpass = c.fetchone()
    print(f"完了: races更新{upd_race}件 / passing更新{upd_pass}行 / 失敗{fail}件")
    print(f"カバレッジ({since}〜{until}): track_condition {cond}/{tot} ({100*cond/tot:.1f}%) / "
          f"passing {rpass}/{rtot} ({100*rpass/rtot:.1f}%)")
    conn.close()


if __name__ == "__main__":
    main()
