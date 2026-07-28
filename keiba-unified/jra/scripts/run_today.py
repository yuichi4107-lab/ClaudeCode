#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
競馬予想 本番用スクリプト
当日の出馬表を取得し、予測レポートを出力する

Usage:
  python3 run_today.py              # 今日のレースを予測
  python3 run_today.py 2026-03-15   # 指定日のレースを予測
  python3 run_today.py --scrape-only  # データ取得のみ（予測しない）
"""

import sys
import os
import re
import time
import requests
from bs4 import BeautifulSoup
from datetime import datetime, date

sys.path.insert(0, os.path.dirname(__file__))
from predictor_v1 import get_conn, predict_day, DAILY_BUDGET
from scraper_legacy import HEADERS, REQUEST_INTERVAL, init_db, parse_time, parse_weight, extract_id_from_href

# ============================================================
# 出馬表スクレイピング（当日レース用）
# ============================================================

def get_today_race_ids(target_date):
    """指定日の開催レースID一覧を取得"""
    date_str = target_date.strftime("%Y%m%d")
    url = f"https://race.netkeiba.com/top/race_list_sub.html?kaisai_date={date_str}"
    try:
        res = requests.get(url, headers=HEADERS, timeout=15)
        res.encoding = "UTF-8"
    except requests.RequestException as e:
        print(f"Error fetching race list: {e}")
        return []

    soup = BeautifulSoup(res.text, "lxml")
    race_ids = []
    for a in soup.find_all("a", href=True):
        m = re.search(r'race_id=(\d{12})', a.get("href", ""))
        if m:
            race_ids.append(m.group(1))

    return sorted(set(race_ids))


def scrape_shutuba(race_id, conn):
    """出馬表ページから当日のエントリーデータを取得"""
    url = f"https://race.netkeiba.com/race/shutuba.html?race_id={race_id}"
    try:
        res = requests.get(url, headers=HEADERS, timeout=15)
        res.encoding = "UTF-8"
    except requests.RequestException as e:
        print(f"  Error fetching shutuba {race_id}: {e}")
        return False

    if res.status_code != 200:
        print(f"  HTTP {res.status_code} for shutuba {race_id}")
        return False

    soup = BeautifulSoup(res.text, "lxml")
    c = conn.cursor()

    # レース情報
    race_name = ""
    title_el = soup.find("h1", class_="RaceName")
    if not title_el:
        title_el = soup.find("div", class_="RaceName")
    if title_el:
        race_name = title_el.get_text(strip=True)

    # コース情報
    race_data = soup.find("div", class_="RaceData01")
    race_data_text = race_data.get_text(strip=True) if race_data else ""

    surface = ""
    direction = ""
    distance = 0
    track_condition = ""
    weather = ""

    surface_m = re.search(r'(芝|ダ)(右|左|直)?(\d+)m', race_data_text)
    if surface_m:
        surface = surface_m.group(1)
        if surface == 'ダ':
            surface = 'ダート'
        direction = surface_m.group(2) or ''
        distance = int(surface_m.group(3))

    weather_m = re.search(r'天候:(\S+)', race_data_text)
    if weather_m:
        weather = weather_m.group(1)

    cond_m = re.search(r'(?:芝|ダート):(\S+)', race_data_text)
    if cond_m:
        track_condition = cond_m.group(1)

    # 発走時刻
    start_time = ""
    start_m = re.search(r'(\d{1,2}:\d{2})\s*発走', race_data_text) or re.search(r'発走\s*[:\s]*(\d{1,2}:\d{2})', race_data_text)
    if start_m:
        start_time = start_m.group(1)

    # 開催場所・日付
    venue_code = race_id[4:6] if len(race_id) >= 6 else ""
    venue_map = {
        "01": "札幌", "02": "函館", "03": "福島", "04": "新潟",
        "05": "東京", "06": "中山", "07": "中京", "08": "京都",
        "09": "阪神", "10": "小倉"
    }
    venue = venue_map.get(venue_code, "")
    race_number = int(race_id[10:12]) if len(race_id) >= 12 else 0

    # 日付はレースIDから推定 or ページから取得
    date_el = soup.find("dd", class_="Active")
    date_str = ""
    if date_el:
        date_m = re.search(r'(\d+)月(\d+)日', date_el.get_text())
        if date_m:
            year = datetime.now().year
            date_str = f"{year}-{int(date_m.group(1)):02d}-{int(date_m.group(2)):02d}"
    if not date_str:
        # race_idから推定は困難なのでコマンドライン日付を使う
        date_str = ""

    # クラス判定
    race_data2 = soup.find("div", class_="RaceData02")
    class_text = (race_name + " " + (race_data2.get_text() if race_data2 else ""))
    race_class = ""
    class_keywords = [
        ("GIII", "G3"), ("GII", "G2"), ("GI", "G1"),
        ("(G3)", "G3"), ("(G2)", "G2"), ("(G1)", "G1"),
        ("G3", "G3"), ("G2", "G2"), ("G1", "G1"),
        ("オープン", "OP"), ("リステッド", "OP"),
        ("3勝", "3勝"), ("2勝", "2勝"), ("1勝", "1勝"),
        ("未勝利", "未勝利"), ("新馬", "新馬"),
    ]
    for keyword, cls in class_keywords:
        if keyword in class_text:
            race_class = cls
            break

    # 出馬表テーブル
    shutuba_table = soup.find("table", class_="Shutuba_Table")
    if not shutuba_table:
        # 別のクラス名を試す
        shutuba_table = soup.find("table", id="shutuba_table")
    if not shutuba_table:
        print(f"  No shutuba table for {race_id}")
        return False

    rows = shutuba_table.find_all("tr", class_="HorseList")
    head_count = len(rows)

    if head_count == 0:
        print(f"  No entries for {race_id}")
        return False

    return {
        "race_id": race_id,
        "date_str": date_str,
        "venue": venue,
        "race_number": race_number,
        "race_name": race_name,
        "race_class": race_class,
        "distance": distance,
        "surface": surface,
        "direction": direction,
        "track_condition": track_condition,
        "weather": weather,
        "start_time": start_time,
        "head_count": head_count,
        "rows": rows,
        "soup": soup,
    }


def parse_shutuba_entries(race_data, conn):
    """出馬表の各馬データをパースしてDBに挿入"""
    c = conn.cursor()
    race_id = race_data["race_id"]

    # レース情報をDB挿入
    c.execute("""INSERT OR REPLACE INTO races VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
              (race_id, race_data["date_str"], race_data["venue"],
               race_data["race_number"], race_data["race_name"],
               race_data["race_class"], race_data["distance"],
               race_data["surface"], race_data["direction"],
               race_data["track_condition"], race_data["weather"],
               race_data["head_count"], race_data.get("start_time", "")))

    entries = []
    for row in race_data["rows"]:
        tds = row.find_all("td")
        if len(tds) < 8:
            continue

        # 枠番・馬番
        post_position = 0
        horse_number = 0
        try:
            post_position = int(tds[0].get_text(strip=True))
        except (ValueError, IndexError):
            pass
        try:
            horse_number = int(tds[1].get_text(strip=True))
        except (ValueError, IndexError):
            pass

        # 馬情報
        horse_link = row.find("a", href=lambda x: x and "/horse/" in x)
        horse_id = ""
        horse_name = ""
        if horse_link:
            horse_id = extract_id_from_href(horse_link.get("href"), r'/horse/(\w+)')
            horse_name = horse_link.get_text(strip=True)

        # 性齢
        sex_age = ""
        for td in tds:
            text = td.get_text(strip=True)
            if re.match(r'^[牡牝セ]\d$', text):
                sex_age = text
                break

        # 斤量
        weight_carried = 0
        for td in tds:
            text = td.get_text(strip=True)
            try:
                val = float(text)
                if 48.0 <= val <= 62.0:
                    weight_carried = val
                    break
            except ValueError:
                pass

        # 騎手
        jockey_link = row.find("a", href=lambda x: x and "/jockey/" in x)
        jockey_id = ""
        jockey_name = ""
        if jockey_link:
            jockey_id = extract_id_from_href(jockey_link.get("href"), r'/jockey/(\w+)')
            if not jockey_id:
                jockey_id = extract_id_from_href(jockey_link.get("href"), r'/jockey/.*?/(\d+)')
            jockey_name = jockey_link.get_text(strip=True)

        # 調教師
        trainer_link = row.find("a", href=lambda x: x and "/trainer/" in x)
        trainer_id = ""
        trainer_name = ""
        if trainer_link:
            trainer_id = extract_id_from_href(trainer_link.get("href"), r'/trainer/(\w+)')
            if not trainer_id:
                trainer_id = extract_id_from_href(trainer_link.get("href"), r'/trainer/.*?/(\d+)')
            trainer_name = trainer_link.get_text(strip=True)

        # 馬体重（当日発表前はなし）
        horse_weight = None
        weight_change = None

        # 出馬表ページからオッズ・人気を取得（発売中の場合）
        odds_win = None
        popularity = None
        for td in tds:
            cls = td.get("class", [])
            text = td.get_text(strip=True)
            if "Popular" in cls and "Popular_Ninki" not in cls and text != "---.-" and text:
                try:
                    odds_win = float(text.replace(",", ""))
                except ValueError:
                    pass
            if "Popular_Ninki" in cls and text != "**" and text:
                try:
                    popularity = int(text)
                except ValueError:
                    pass

        # DB挿入
        if horse_id:
            sex = sex_age[0] if sex_age else ""
            c.execute("INSERT OR IGNORE INTO horses (horse_id, name, sex) VALUES (?,?,?)",
                      (horse_id, horse_name, sex))
        if jockey_id:
            c.execute("INSERT OR IGNORE INTO jockeys VALUES (?,?)", (jockey_id, jockey_name))
        if trainer_id:
            c.execute("INSERT OR IGNORE INTO trainers VALUES (?,?)", (trainer_id, trainer_name))

        # results テーブルに挿入 (finish_position=0, finish_time=None等)
        c.execute("""INSERT OR REPLACE INTO results
                     (race_id, horse_id, jockey_id, trainer_id,
                      post_position, horse_number, weight_carried,
                      horse_weight, weight_change, finish_position,
                      finish_time, margin, passing, last_3f,
                      odds_win, popularity, sex_age, prize)
                     VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                  (race_id, horse_id, jockey_id, trainer_id,
                   post_position, horse_number, weight_carried,
                   horse_weight, weight_change, 0,  # finish_position=0 (未確定)
                   None, None, None, None,
                   odds_win, popularity, sex_age, 0))

        entries.append({
            "horse_number": horse_number,
            "horse_id": horse_id,
            "horse_name": horse_name,
            "jockey_name": jockey_name,
        })

    conn.commit()
    return entries


def _build_jra_cname_map(target_date):
    """JRA公式サイトから当日全場・全レースの CNAME マッピングを構築

    手順:
      1. thisweek ページから1場の11R CNAMEを取得
      2. その出馬表ページ内の他場11Rリンクを収集
      3. 各場の11Rページから全12レースのCNAMEを取得
    Returns: dict  {netkeiba_race_id: cname_string}
    """
    import re as _re
    mmdd = target_date.strftime("%m%d")
    jra_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    date_ymd = target_date.strftime("%Y%m%d")

    def _extract_cnames(html_text):
        """HTML内の全dde01 CNAMEを抽出して {netkeiba_race_id: cname} に変換（対象日のみ）"""
        result = {}
        pattern = r"(pw01dde01(\d{2})(\d{4})(\d{2})(\d{2})(\d{2})(\d{8})/[0-9A-Fa-f]{2})"
        for m in _re.finditer(pattern, html_text):
            full = m.group(1)
            jou, _nen, kai, nichi, race_num, cname_date = (
                m.group(2), m.group(3), m.group(4), m.group(5), m.group(6), m.group(7))
            # 対象日のCNAMEのみ採用
            if cname_date != date_ymd:
                continue
            nk_race_id = f"{target_date.year}{jou}{kai}{nichi}{race_num}"
            result[nk_race_id] = full
        return result

    def _fetch_jra_page(cname):
        """JRADB出馬表ページを取得してshift_jisデコード"""
        url = f"https://www.jra.go.jp/JRADB/accessD.html?CNAME={cname}"
        try:
            r = requests.get(url, headers=jra_headers, timeout=10)
            if r.status_code == 200:
                return r.content.decode("shift_jis", errors="replace")
        except requests.RequestException:
            pass
        return None

    cname_map = {}
    visited_venues = set()  # 場コード（全R取得済み）

    # Step 1: thisweekの全ページから起点CNAMEを収集
    # JRAのthisweek配下は「その週の土曜MMDD」で固定されるため、
    # target_dateが日曜・祝日の場合は1〜3日前まで遡って試す
    from datetime import timedelta as _td
    seed_cnames = []
    for _back in range(0, 4):
        cand_date = target_date - _td(days=_back)
        cand_mmdd = cand_date.strftime("%m%d")
        found_any = False
        for page_idx in range(1, 5):
            page_url = (f"https://www.jra.go.jp/keiba/thisweek/"
                        f"{cand_date.year}/{cand_mmdd}_{page_idx}/race.html")
            try:
                r = requests.get(page_url, headers=jra_headers, timeout=10)
                if r.status_code != 200:
                    continue
            except requests.RequestException:
                continue

            text = r.content.decode("shift_jis", errors="replace")
            found = _re.findall(r"CNAME=(pw01dde01[^\"&\s]+)", text)
            for c in found:
                if c not in seed_cnames:
                    seed_cnames.append(c)
            found_any = True
        if found_any:
            break

    if not seed_cnames:
        return cname_map

    # Step 2: 各起点ページにアクセスして自場全R + 他場11Rリンクを取得
    for seed_cname in seed_cnames:
        seed_text = _fetch_jra_page(seed_cname)
        if not seed_text:
            continue

        extracted = _extract_cnames(seed_text)
        cname_map.update(extracted)

        # この場を取得済みに記録
        seed_venue = _re.match(r"pw01dde01(\d{2})", seed_cname)
        if seed_venue:
            visited_venues.add(seed_venue.group(1))
        time.sleep(0.5)

    # Step 3: 12R揃っていない場について、その場のレースページ（11R優先）を辿って補完
    # （日曜日に土曜の seed を使う運用では visited_venues が正しく機能しないため、
    #  ここでは「カバレッジが12未満の場」を一律で再取得する）
    while True:
        from collections import defaultdict as _dd
        venue_races = _dd(set)
        for nk_id in cname_map:
            venue_races[nk_id[4:6]].add(nk_id[-2:])
        incomplete = [v for v, races in venue_races.items() if len(races) < 12]
        if not incomplete:
            break
        progress = False
        for venue in incomplete:
            # 11R を優先、なければ任意のレース
            pick = None
            for nk_id, cname in cname_map.items():
                if nk_id[4:6] != venue:
                    continue
                if nk_id[-2:] == "11":
                    pick = cname
                    break
                if pick is None:
                    pick = cname
            if pick is None:
                continue
            before = len(cname_map)
            page_text = _fetch_jra_page(pick)
            if page_text:
                cname_map.update(_extract_cnames(page_text))
            time.sleep(0.5)
            if len(cname_map) > before:
                progress = True
        if not progress:
            break

    return cname_map


# ============================================================
# JRA公式サイトからレース結果を取得
# ============================================================

def _build_jra_result_cname_map(target_date):
    """JRA公式サイトから結果ページ用のCNAMEマッピングを構築

    手順:
      1. 出馬表ページ(dde01)から各場1レース分のsde01を取得
      2. その結果ページ内の全sde01リンクを収集（各場全12R + 他場1R）
      3. 未取得の場は辿って全レースのsde01を収集

    Returns: dict {netkeiba_race_id: sde01_cname_string}
    """
    import re as _re
    date_ymd = target_date.strftime("%Y%m%d")
    jra_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    def _extract_result_cnames(html_text):
        """HTML内のsde01 CNAMEを抽出して {netkeiba_race_id: cname} に変換"""
        found = {}
        pattern = r"(pw01sde01(\d{2})(\d{4})(\d{2})(\d{2})(\d{2})(\d{8})/[0-9A-Fa-f]{2})"
        for m in _re.finditer(pattern, html_text):
            full = m.group(1)
            jou, _nen, kai, nichi, race_num, cname_date = (
                m.group(2), m.group(3), m.group(4), m.group(5), m.group(6), m.group(7))
            if cname_date != date_ymd:
                continue
            nk_race_id = f"{target_date.year}{jou}{kai}{nichi}{race_num}"
            found[nk_race_id] = full
        return found

    def _fetch_result_page(cname):
        """JRA結果ページを取得"""
        url = f"https://www.jra.go.jp/JRADB/accessS.html?CNAME={cname}"
        try:
            r = requests.get(url, headers=jra_headers, timeout=15)
            if r.status_code == 200:
                return r.content.decode("shift_jis", errors="replace")
        except requests.RequestException:
            pass
        return None

    # Step 1: 出馬表ページからsde01を1つずつ取得（各場1レース）
    dde_map = _build_jra_cname_map(target_date)
    if not dde_map:
        return {}

    seed_sde = {}  # {venue: sde01_cname}
    for nk_id, dde_cname in sorted(dde_map.items()):
        m = _re.match(r"pw01dde01(\d{2})", dde_cname)
        if not m:
            continue
        venue = m.group(1)
        if venue in seed_sde:
            continue

        url = f"https://www.jra.go.jp/JRADB/accessD.html?CNAME={dde_cname}"
        try:
            r = requests.get(url, headers=jra_headers, timeout=15)
            if r.status_code == 200:
                html = r.content.decode("shift_jis", errors="replace")
                found = _extract_result_cnames(html)
                for rid, scname in found.items():
                    m2 = _re.match(r"pw01sde01(\d{2})", scname)
                    if m2 and m2.group(1) == venue:
                        seed_sde[venue] = scname
                        break
        except requests.RequestException:
            pass
        time.sleep(0.5)

    if not seed_sde:
        return {}

    # Step 2: 各場の結果ページから全レースのsde01を取得
    result_map = {}
    visited_venues = set()

    for venue, seed_cname in seed_sde.items():
        if venue in visited_venues:
            continue
        visited_venues.add(venue)

        html = _fetch_result_page(seed_cname)
        if html:
            result_map.update(_extract_result_cnames(html))
        time.sleep(0.5)

    # Step 3: 他場のsde01が1Rだけ含まれていた場合、そこからも全レース取得
    for nk_id, scname in list(result_map.items()):
        m = _re.match(r"pw01sde01(\d{2})", scname)
        if not m:
            continue
        venue = m.group(1)
        if venue in visited_venues:
            continue
        visited_venues.add(venue)

        html = _fetch_result_page(scname)
        if html:
            result_map.update(_extract_result_cnames(html))
        time.sleep(0.5)

    return result_map


# JRA払戻種別名 → DB保存名 のマッピング
_JRA_BET_TYPE_MAP = {
    "単勝": "単勝",
    "複勝": "複勝",
    "枠連": "枠連",
    "ワイド": "ワイド",
    "馬連": "馬連",
    "馬単": "馬単",
    "3連複": "三連複",
    "3連単": "三連単",
}


def scrape_result_jra(race_id, conn, cname):
    """JRA公式サイトの結果ページをスクレイピングしてDBに格納

    既存の出馬表データ(resultsテーブル)を着順・タイム等で更新し、
    払戻金(payoutsテーブル)を挿入する。
    """
    jra_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    url = f"https://www.jra.go.jp/JRADB/accessS.html?CNAME={cname}"
    try:
        r = requests.get(url, headers=jra_headers, timeout=15)
        if r.status_code != 200:
            return False
    except requests.RequestException:
        return False

    html = r.content.decode("shift_jis", errors="replace")
    soup = BeautifulSoup(html, "lxml")

    tables = soup.find_all("table")
    if not tables:
        return False

    rows = tables[0].find_all("tr")[1:]  # ヘッダー行スキップ
    if not rows:
        return False

    c = conn.cursor()
    updated = 0

    for row in rows:
        tds = row.find_all(["th", "td"])
        if len(tds) < 14:
            continue

        # 着順
        finish_str = tds[0].text.strip()
        try:
            finish_pos = int(finish_str)
        except ValueError:
            finish_pos = 0  # 除外・中止・取消

        post_position = 0
        gate_str = tds[1].text.strip()
        if gate_str.isdigit():
            post_position = int(gate_str)

        horse_number = 0
        hnum_str = tds[2].text.strip()
        if hnum_str.isdigit():
            horse_number = int(hnum_str)

        if horse_number == 0:
            continue

        sex_age = tds[4].text.strip()
        weight_carried = 0
        try:
            weight_carried = float(tds[5].text.strip())
        except ValueError:
            pass

        finish_time = parse_time(tds[7].text.strip())
        margin = tds[8].text.strip()
        passing = tds[9].text.strip().replace("\n", "-")
        last_3f = None
        try:
            last_3f = float(tds[10].text.strip())
        except ValueError:
            pass

        horse_weight, weight_change = parse_weight(tds[11].text.strip())
        popularity = 0
        try:
            popularity = int(tds[13].text.strip())
        except ValueError:
            pass

        # resultsテーブルを更新（horse_numberで既存行をマッチ）
        c.execute("""UPDATE results SET
                        finish_position = ?, post_position = ?,
                        weight_carried = ?, horse_weight = ?, weight_change = ?,
                        finish_time = ?, margin = ?, passing = ?, last_3f = ?,
                        popularity = ?, sex_age = ?
                     WHERE race_id = ? AND horse_number = ?""",
                  (finish_pos, post_position,
                   weight_carried, horse_weight, weight_change,
                   finish_time, margin, passing, last_3f,
                   popularity, sex_age,
                   race_id, horse_number))
        updated += 1

    # --- 払戻金パース ---
    refund = soup.find("div", class_="refund_area")
    if refund:
        dls = refund.find_all("dl")
        for dl in dls:
            dt = dl.find("dt")
            if not dt:
                continue
            raw_type = dt.text.strip()

            # JRA名 → DB名に変換
            bet_type = None
            for jra_name, db_name in _JRA_BET_TYPE_MAP.items():
                if jra_name in raw_type:
                    bet_type = db_name
                    break
            if not bet_type:
                continue

            dd = dl.find("dd")
            if not dd:
                continue

            for line in dd.find_all("div", class_="line"):
                num_div = line.find("div", class_="num")
                yen_div = line.find("div", class_="yen")
                pop_div = line.find("div", class_="pop")
                combo = num_div.text.strip() if num_div else ""
                if not combo:
                    continue

                payout_text = yen_div.text.strip() if yen_div else "0"
                pop_text = pop_div.text.strip() if pop_div else "0"
                payout_val = int(re.sub(r"[^\d]", "", payout_text) or "0")
                pop_val = int(re.sub(r"[^\d]", "", pop_text) or "0")

                c.execute("INSERT OR REPLACE INTO payouts VALUES (?,?,?,?,?)",
                          (race_id, bet_type, combo, payout_val, pop_val))

    # スクレイプログ
    c.execute("INSERT OR REPLACE INTO scrape_log VALUES (?,?)",
              (race_id, datetime.now().isoformat()))

    if updated > 0:
        conn.commit()
    return updated > 0


# モジュールレベルのキャッシュ
_jra_cname_cache = {}


def _scrape_odds_jra(race_id, conn, cname, verbose=False):
    """JRA公式サイトの出馬表ページからオッズを取得"""
    import re as _re
    jra_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    url = f"https://www.jra.go.jp/JRADB/accessD.html?CNAME={cname}"
    try:
        r = requests.get(url, headers=jra_headers, timeout=15)
        if r.status_code != 200:
            return False
    except requests.RequestException:
        return False

    from bs4 import BeautifulSoup
    text = r.content.decode("shift_jis", errors="replace")
    soup = BeautifulSoup(text, "html.parser")

    tables = soup.find_all("table")
    if not tables:
        return False

    c = conn.cursor()
    updated = 0
    for row in tables[0].find_all("tr")[1:]:
        tds = row.find_all("td")
        if len(tds) < 3:
            continue
        horse_num_str = tds[1].get_text(strip=True)
        info_text = tds[2].get_text(strip=True)
        # パターン: 馬名 + オッズ(N番人気)
        m = _re.match(r".+?([\d.]+)\((\d+)番人気\)", info_text)
        if not m:
            continue
        try:
            horse_num = int(horse_num_str)
            odds = float(m.group(1))
            pop = int(m.group(2))
            c.execute("""UPDATE results SET odds_win = ?, popularity = ?
                        WHERE race_id = ? AND horse_number = ?""",
                      (odds, pop, race_id, horse_num))
            updated += 1
        except (ValueError, IndexError):
            continue

    if updated > 0:
        conn.commit()
    return updated > 0


def _scrape_odds_netkeiba(race_id, conn, retries=3, verbose=False):
    """netkeiba APIから単勝オッズを取得してresultsを更新。成功時True。
    netkeibaのオッズAPIは &action=update を付けないと data空 を返す仕様。"""
    import json
    url = f"https://race.netkeiba.com/api/api_get_jra_odds.html?race_id={race_id}&type=1&action=update"

    for attempt in range(retries):
        try:
            res = requests.get(url, headers=HEADERS, timeout=15)
        except requests.RequestException as e:
            if verbose:
                print(f"  netkeiba取得エラー ({attempt+1}/{retries}): {e}")
            time.sleep(2)
            continue

        if res.status_code != 200:
            if verbose:
                print(f"  netkeiba HTTPエラー {res.status_code} ({attempt+1}/{retries})")
            time.sleep(2)
            continue

        try:
            data = json.loads(res.text)
        except json.JSONDecodeError:
            if verbose:
                print(f"  netkeiba JSONパースエラー ({attempt+1}/{retries})")
            time.sleep(2)
            continue

        status = data.get("status")
        if status not in ("result", "middle"):
            if verbose:
                print(f"  netkeiba APIステータス: {status} ({attempt+1}/{retries})")
            time.sleep(3)
            continue
        if not data.get("data") or not isinstance(data["data"], dict):
            if verbose:
                print(f"  netkeiba オッズ更新中(data空) ({attempt+1}/{retries})")
            time.sleep(5)
            continue

        odds_data = data["data"].get("odds", {})
        tan_odds = odds_data.get("1", {})
        if not tan_odds:
            if verbose:
                print(f"  netkeiba 単勝オッズデータなし ({attempt+1}/{retries})")
            time.sleep(2)
            continue

        c = conn.cursor()
        updated = 0
        for horse_num_str, values in tan_odds.items():
            try:
                horse_num = int(horse_num_str)
                odds = float(values[0])
                pop = int(values[2]) if len(values) > 2 and values[2] else None
                c.execute("""UPDATE results SET odds_win = ?, popularity = ?
                            WHERE race_id = ? AND horse_number = ?""",
                          (odds, pop, race_id, horse_num))
                updated += 1
            except (ValueError, IndexError):
                continue

        if updated > 0:
            conn.commit()
            return True

    return False


def scrape_odds(race_id, conn, retries=3, verbose=False):
    """単勝オッズを取得してresultsを更新。
    取得順: ① netkeiba（主経路） → ② JRA公式（フォールバック・現状403で休眠中）。
    どちらもオッズ発表後のみ成功。未発表時は両方失敗し、呼び出し側はオッズなし暫定予想へ。"""
    global _jra_cname_cache

    # --- 1) netkeiba API（主経路） ---
    if _scrape_odds_netkeiba(race_id, conn, retries, verbose):
        if verbose:
            print(f"  netkeibaからオッズ取得成功", flush=True)
        return True

    # --- 2) JRA公式サイト（フォールバック） ---
    if verbose:
        print(f"  netkeiba失敗 → JRA公式にフォールバック", flush=True)
    c = conn.cursor()
    c.execute("SELECT date FROM races WHERE race_id = ?", (race_id,))
    row = c.fetchone()
    if row:
        target_date = datetime.strptime(row[0], "%Y-%m-%d").date()
        date_key = row[0]

        # CNAMEマップをキャッシュ（1日1回のみ構築）
        if date_key not in _jra_cname_cache:
            if verbose:
                print(f"  JRA公式CNAMEマップ構築中...", flush=True)
            _jra_cname_cache[date_key] = _build_jra_cname_map(target_date)
            if verbose:
                print(f"  {len(_jra_cname_cache[date_key])}レース分取得", flush=True)

        cname = _jra_cname_cache[date_key].get(race_id)
        if cname:
            if _scrape_odds_jra(race_id, conn, cname, verbose):
                if verbose:
                    print(f"  JRA公式からオッズ取得成功", flush=True)
                return True

    return False


# ============================================================
# レポート生成
# ============================================================

def generate_report(prediction, conn):
    """予測結果からレポートを生成"""
    d = prediction["date"]
    races = prediction["races"]

    c = conn.cursor()

    # ヘッダー
    try:
        dt = datetime.strptime(d, "%Y-%m-%d")
        weekday = ["月", "火", "水", "木", "金", "土", "日"][dt.weekday()]
        header_date = f"{dt.year}年{dt.month}月{dt.day}日（{weekday}）"
    except ValueError:
        header_date = d

    lines = []
    lines.append(f"=== {header_date} 競馬予想レポート ===")
    lines.append("")

    if not races:
        lines.append("本日は選定基準を満たすレースがありません。")
        return "\n".join(lines)

    # 全レース数を取得
    c.execute("""SELECT COUNT(*) FROM races WHERE date = ? AND surface IN ('芝', 'ダート')
                 AND name NOT LIKE '%障害%'""", (d,))
    total_races = c.fetchone()[0]

    # オッズの有無で実際に使われた閾値を表示
    has_odds = any(
        (h.get("odds_win") or 0) > 0
        for race in races
        for h in race["scored_horses"][:3]
    )
    actual_threshold = 0.80 if has_odds else 0.70

    lines.append(f"【選定レース: {len(races)}レース / 全{total_races}レース中】")
    if not has_odds:
        lines.append(f" ※ オッズ未発表のため暫定予測（オッズ発表後に再実行推奨）")
    lines.append(f" 選定基準: 品質スコア {actual_threshold:.2f} 以上")
    lines.append("")

    total_bet = 0
    for i, race in enumerate(races):
        ri = race["race_info"]
        qi = race["quality"]
        bets = race["bets"]
        horse_names = race["horse_names"]

        # レースヘッダー
        cond_str = f" {ri.get('track_condition', '')}" if ri.get('track_condition') else ""
        lines.append(f"■ {ri['venue']} {ri['race_number']}R {ri['name']} "
                     f"{ri['surface']}{ri['distance']}m{cond_str}")

        reasons = ", ".join(qi["reasons"]) if qi["reasons"] else "総合スコア"
        lines.append(f"  選定理由: 品質スコア {qi['quality_score']:.2f}  [{reasons}]")
        lines.append("")

        # 推奨馬券種
        lines.append(f"  推奨: {bets['bet_type']}")

        # 上位馬のスコア表示
        lines.append(f"  順位  馬番  馬名              スコア  人気  オッズ")
        lines.append(f"  {'─' * 52}")
        for j, h in enumerate(race["scored_horses"][:5]):
            hn = h["horse_number"]
            name = horse_names.get(h["horse_id"], "???")
            # 日本語文字幅を考慮してパディング
            name_display = name[:8] if len(name) > 8 else name
            name_pad = 16 - len(name_display.encode('utf-8', errors='replace')) + len(name_display)
            pop = h.get("popularity") or "-"
            odds = h.get("odds_win")
            odds_str = f"{odds:.1f}" if odds else "-"
            v2_str = ""
            if "v2_prob" in h:
                v2_str = f" (v2:{h['v2_prob']:.3f})"
            lines.append(f"  {j+1:>4d}  {hn:>4d}  {name_display:<{name_pad}s} "
                        f"{h['total_score']:.4f}  {str(pop):>4s}  {odds_str:>6s}{v2_str}")
        lines.append("")

        # 買い目
        lines.append(f"  買い目:")
        for bet in bets["bets"]:
            lines.append(f"    {bet['combination']:>12s}  {bet['amount']:>5,}円")
        race_bet = race["bet_total"]
        total_bet += race_bet
        lines.append(f"  小計: {race_bet:,}円")
        lines.append("")

    # フッター
    lines.append("=" * 50)
    lines.append(f"本日合計投資: {total_bet:,}円")
    lines.append("=" * 50)

    return "\n".join(lines)


# ============================================================
# メイン処理
# ============================================================

def save_predictions(prediction, conn, source="morning"):
    """予測結果をDBに保存（結果チェック用）

    source: "morning" (朝予想) or "live" (ライブモード)
    """
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS predictions (
        date TEXT, race_id TEXT, bet_type TEXT,
        combination TEXT, amount INTEGER, quality_score REAL,
        source TEXT DEFAULT 'morning',
        PRIMARY KEY (date, race_id, combination, source))""")
    # est_odds: 買い目生成時の推定オッズ。配当均等配分の反実仮想ROI計算用（2026-07-11追加）
    try:
        c.execute("ALTER TABLE predictions ADD COLUMN est_odds REAL")
    except Exception:
        pass  # 既に列がある

    d = prediction["date"]
    for race in prediction["races"]:
        q_score = race["quality"]["quality_score"]
        bt = race["bets"]["bet_type"]
        for bet in race["bets"]["bets"]:
            c.execute("""INSERT OR REPLACE INTO predictions
                         (date, race_id, bet_type, combination, amount, quality_score, source, est_odds)
                         VALUES (?,?,?,?,?,?,?,?)""",
                      (d, race["race_id"], bt, bet["combination"], bet["amount"], q_score, source,
                       bet.get("est_odds")))
    conn.commit()
    print(f"予測データ保存: {len(prediction['races'])}レース ({source})")


def main():
    target_date = date.today()
    scrape_only = False

    for arg in sys.argv[1:]:
        if arg == "--scrape-only":
            scrape_only = True
        elif re.match(r'\d{4}-\d{2}-\d{2}', arg):
            target_date = datetime.strptime(arg, "%Y-%m-%d").date()
        else:
            print(f"Unknown argument: {arg}")
            print(__doc__)
            sys.exit(1)

    date_str = target_date.strftime("%Y-%m-%d")
    print(f"対象日: {date_str}")

    conn = get_conn()

    # 既にDBにデータがあるか確認
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM races WHERE date = ? AND surface IN ('芝', 'ダート')", (date_str,))
    existing = c.fetchone()[0]

    if existing > 0:
        print(f"DB内に {existing} レースのデータあり")
        # 結果データがあるか確認 (finish_position > 0)
        c.execute("""SELECT COUNT(DISTINCT r.race_id) FROM results r
                     JOIN races ra ON r.race_id = ra.race_id
                     WHERE ra.date = ? AND r.finish_position > 0""", (date_str,))
        results_exist = c.fetchone()[0]
        if results_exist > 0:
            print(f"  → {results_exist} レースは結果確定済み（既存データで予測します）")
        else:
            print(f"  → 出馬表データのみ（オッズ更新を試みます）")
            # オッズのみ更新
            c.execute("SELECT race_id FROM races WHERE date = ? AND surface IN ('芝', 'ダート')", (date_str,))
            for (rid,) in c.fetchall():
                scrape_odds(rid, conn)
                time.sleep(REQUEST_INTERVAL)
    else:
        # 出馬表を取得
        print("出馬表を取得中...")
        race_ids = get_today_race_ids(target_date)
        if not race_ids:
            print("本日の開催レースが見つかりません。")
            conn.close()
            return

        # JRA中央競馬のみ（race_idが2から始まるものを除外しないが、
        # venue_codeで01-10のみに限定）
        jra_ids = []
        for rid in race_ids:
            vc = rid[4:6] if len(rid) >= 6 else ""
            if vc in ("01", "02", "03", "04", "05", "06", "07", "08", "09", "10"):
                jra_ids.append(rid)

        print(f"JRA中央競馬: {len(jra_ids)} レース")

        for rid in jra_ids:
            print(f"  取得: {rid}", end="")
            race_data = scrape_shutuba(rid, conn)
            if race_data and isinstance(race_data, dict):
                # 日付を設定
                if not race_data["date_str"]:
                    race_data["date_str"] = date_str
                entries = parse_shutuba_entries(race_data, conn)
                print(f" → {len(entries)}頭")
            else:
                print(" SKIP")
            time.sleep(REQUEST_INTERVAL)

        # オッズ取得
        print("\nオッズ取得中...")
        for rid in jra_ids:
            print(f"  オッズ: {rid}", end="")
            if scrape_odds(rid, conn):
                print(" OK")
            else:
                print(" -")
            time.sleep(REQUEST_INTERVAL)

    if scrape_only:
        print("\nデータ取得完了（--scrape-only）")
        conn.close()
        return

    # 予測実行
    print("\n予測実行中...")
    prediction = predict_day(conn, date_str, DAILY_BUDGET)

    # 予測をDBに保存（結果チェック用）
    save_predictions(prediction, conn)

    # レポート生成
    report = generate_report(prediction, conn)
    print("\n" + report)

    # レポートをファイルにも保存
    report_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "reports")
    os.makedirs(report_dir, exist_ok=True)
    report_file = os.path.join(report_dir, f"report_{date_str}.txt")
    with open(report_file, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"\nレポート保存: {report_file}")

    conn.close()


if __name__ == "__main__":
    main()
