#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
netkeiba スクレイパー
レース結果・出馬表を取得してSQLiteに格納する
"""

import requests
from bs4 import BeautifulSoup
import sqlite3
import re
import time
import os
import sys

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "keiba.db")
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36"}
REQUEST_INTERVAL = 1.5  # サーバー負荷軽減のため1.5秒間隔


def init_db():
    """DB初期化"""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute("""CREATE TABLE IF NOT EXISTS horses (
        horse_id TEXT PRIMARY KEY,
        name TEXT,
        sex TEXT,
        birth_year INTEGER,
        sire TEXT,
        broodmare_sire TEXT
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS jockeys (
        jockey_id TEXT PRIMARY KEY,
        name TEXT
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS trainers (
        trainer_id TEXT PRIMARY KEY,
        name TEXT
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS races (
        race_id TEXT PRIMARY KEY,
        date TEXT,
        venue TEXT,
        race_number INTEGER,
        name TEXT,
        class TEXT,
        distance INTEGER,
        surface TEXT,
        direction TEXT,
        track_condition TEXT,
        weather TEXT,
        head_count INTEGER,
        start_time TEXT
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS results (
        race_id TEXT,
        horse_id TEXT,
        jockey_id TEXT,
        trainer_id TEXT,
        post_position INTEGER,
        horse_number INTEGER,
        weight_carried REAL,
        horse_weight INTEGER,
        weight_change INTEGER,
        finish_position INTEGER,
        finish_time REAL,
        margin TEXT,
        passing TEXT,
        last_3f REAL,
        odds_win REAL,
        popularity INTEGER,
        sex_age TEXT,
        prize REAL,
        PRIMARY KEY (race_id, horse_number)
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS payouts (
        race_id TEXT,
        bet_type TEXT,
        combination TEXT,
        payout INTEGER,
        popularity INTEGER,
        PRIMARY KEY (race_id, bet_type, combination)
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS scrape_log (
        race_id TEXT PRIMARY KEY,
        scraped_at TEXT
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS predictions (
        date TEXT,
        race_id TEXT,
        bet_type TEXT,
        combination TEXT,
        amount INTEGER,
        quality_score REAL,
        PRIMARY KEY (date, race_id, combination)
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS prediction_results (
        date TEXT,
        race_id TEXT,
        venue TEXT,
        race_number INTEGER,
        race_name TEXT,
        bet_type TEXT,
        bet_total INTEGER,
        hit INTEGER,
        payout INTEGER,
        profit INTEGER,
        quality_score REAL,
        PRIMARY KEY (date, race_id)
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS daily_summary (
        date TEXT PRIMARY KEY,
        races_bet INTEGER,
        races_hit INTEGER,
        total_bet INTEGER,
        total_payout INTEGER,
        profit INTEGER,
        roi REAL,
        hit_rate REAL
    )""")

    conn.commit()
    return conn


def parse_time(time_str):
    """タイム文字列を秒に変換 (例: '1:33.8' -> 93.8)"""
    time_str = time_str.strip()
    if not time_str or time_str == '--':
        return None
    try:
        if ':' in time_str:
            parts = time_str.split(':')
            return float(parts[0]) * 60 + float(parts[1])
        else:
            return float(time_str)
    except ValueError:
        return None


def parse_weight(weight_str):
    """馬体重を解析 (例: '460(+12)' -> (460, 12))"""
    weight_str = weight_str.strip()
    if not weight_str or weight_str == '--':
        return None, None
    m = re.match(r'(\d+)\(([+-]?\d+)\)', weight_str)
    if m:
        return int(m.group(1)), int(m.group(2))
    m2 = re.match(r'(\d+)', weight_str)
    if m2:
        return int(m2.group(1)), None
    return None, None


def extract_id_from_href(href, pattern):
    """hrefからIDを抽出"""
    if not href:
        return None
    m = re.search(pattern, href)
    return m.group(1) if m else None


def scrape_race(race_id, conn):
    """1レースの結果を取得してDBに格納"""
    url = f"https://db.netkeiba.com/race/{race_id}/"
    try:
        res = requests.get(url, headers=HEADERS, timeout=10)
        res.encoding = "EUC-JP"
    except requests.RequestException as e:
        print(f"  Error fetching {race_id}: {e}")
        return False

    if res.status_code != 200:
        print(f"  HTTP {res.status_code} for {race_id}")
        return False

    soup = BeautifulSoup(res.text, "lxml")
    c = conn.cursor()

    # レース情報
    race_info = soup.find("div", class_="data_intro")
    if not race_info:
        print(f"  No race info for {race_id}")
        return False

    race_name = ""
    title_el = race_info.find("h1")
    if title_el:
        race_name = title_el.text.strip()

    # コース情報をパース
    span = race_info.find("span")
    span_text = span.text.strip() if span else ""

    surface = ""
    direction = ""
    distance = 0
    track_condition = ""
    weather = ""

    # 芝左1600m / 天候 : 雨 / 芝 : 稍重 / 発走 : 15:45
    surface_m = re.search(r'(芝|ダ|障)(右|左|直)?(\d+)m', span_text)
    if surface_m:
        surface = surface_m.group(1)
        if surface == 'ダ':
            surface = 'ダート'
        elif surface == '障':
            surface = '障害'
        direction = surface_m.group(2) or ''
        distance = int(surface_m.group(3))

    cond_m = re.search(r'(?:芝|ダート)\s*:\s*(良|稍重|重|不良)', span_text)
    if cond_m:
        track_condition = cond_m.group(1)

    weather_m = re.search(r'天候\s*:\s*(\S+)', span_text)
    if weather_m:
        weather = weather_m.group(1)

    start_time = ""
    start_m = re.search(r'(\d{1,2}:\d{2})\s*発走', span_text) or re.search(r'発走\s*[:\s]*(\d{1,2}:\d{2})', span_text)
    if start_m:
        start_time = start_m.group(1)

    # 日付・場所をrace_idからパース
    # race_id: YYYYJJKKRRNN (年4+場所2+回2+日2+レース番号2)
    # ただしnetkeibaのIDは12桁: 202505040811
    venue_code = race_id[4:6] if len(race_id) >= 6 else ""
    venue_map = {
        "01": "札幌", "02": "函館", "03": "福島", "04": "新潟",
        "05": "東京", "06": "中山", "07": "中京", "08": "京都",
        "09": "阪神", "10": "小倉"
    }
    venue = venue_map.get(venue_code, "")
    race_number = int(race_id[10:12]) if len(race_id) >= 12 else 0

    # 日付はページから取得
    date_el = race_info.find("p", class_="smalltxt")
    date_str = ""
    if date_el:
        date_m = re.search(r'(\d{4})/(\d{1,2})/(\d{1,2})', date_el.text)
        if not date_m:
            date_m = re.search(r'(\d{4})年(\d{1,2})月(\d{1,2})日', date_el.text)
        if date_m:
            date_str = f"{date_m.group(1)}-{int(date_m.group(2)):02d}-{int(date_m.group(3)):02d}"

    # クラス判定（race_nameとclass_infoの両方を使用）
    class_info = ""
    if date_el:
        class_info = date_el.text
    full_text = race_name + " " + class_info
    race_class = ""
    class_keywords = [
        ("GIII", "G3"), ("GII", "G2"), ("GI", "G1"),
        ("(G3)", "G3"), ("(G2)", "G2"), ("(G1)", "G1"),
        ("オープン", "OP"), ("3勝", "3勝"), ("2勝", "2勝"),
        ("1勝", "1勝"), ("未勝利", "未勝利"), ("新馬", "新馬")
    ]
    for keyword, cls in class_keywords:
        if keyword in full_text:
            race_class = cls
            break

    # レース結果テーブル
    result_table = soup.find("table", class_="race_table_01")
    if not result_table:
        print(f"  No result table for {race_id}")
        return False

    rows = result_table.find_all("tr")[1:]  # ヘッダー行をスキップ
    head_count = len(rows)

    # レース情報をDB挿入
    c.execute("""INSERT OR REPLACE INTO races VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
              (race_id, date_str, venue, race_number, race_name, race_class,
               distance, surface, direction, track_condition, weather, head_count, start_time))

    # 各馬の結果
    for row in rows:
        tds = row.find_all("td")
        if len(tds) < 15:
            continue

        # 着順
        finish_pos_str = tds[0].text.strip()
        try:
            finish_pos = int(finish_pos_str)
        except ValueError:
            finish_pos = 0  # 除外、中止、取消など

        post_position = int(tds[1].text.strip()) if tds[1].text.strip().isdigit() else 0
        horse_number = int(tds[2].text.strip()) if tds[2].text.strip().isdigit() else 0

        # 馬情報
        horse_link = row.find("a", href=lambda x: x and "/horse/" in x)
        horse_id = ""
        horse_name = ""
        if horse_link:
            horse_id = extract_id_from_href(horse_link.get("href"), r'/horse/(\w+)')
            horse_name = horse_link.text.strip()

        sex_age = tds[4].text.strip()  # 例: "牝2"

        weight_carried = 0
        try:
            weight_carried = float(tds[5].text.strip())
        except ValueError:
            pass

        # 騎手
        jockey_link = row.find("a", href=lambda x: x and "/jockey/" in x)
        jockey_id = ""
        jockey_name = ""
        if jockey_link:
            jockey_id = extract_id_from_href(jockey_link.get("href"), r'/jockey/.*?/(\d+)')
            jockey_name = jockey_link.text.strip()

        # タイム
        finish_time = parse_time(tds[7].text.strip())
        margin = tds[8].text.strip()

        # 通過順・上がり3F
        passing = tds[10].text.strip()
        last_3f = None
        try:
            last_3f = float(tds[11].text.strip())
        except (ValueError, IndexError):
            pass

        # 単勝オッズ・人気
        odds_win = None
        popularity = 0
        try:
            odds_win = float(tds[12].text.strip())
        except (ValueError, IndexError):
            pass
        try:
            popularity = int(tds[13].text.strip())
        except (ValueError, IndexError):
            pass

        # 馬体重
        horse_weight, weight_change = parse_weight(tds[14].text.strip())

        # 調教師
        trainer_link = row.find("a", href=lambda x: x and "/trainer/" in x)
        trainer_id = ""
        trainer_name = ""
        if trainer_link:
            trainer_id = extract_id_from_href(trainer_link.get("href"), r'/trainer/.*?/(\d+)')
            trainer_name = trainer_link.text.strip()

        # 賞金
        prize = 0
        try:
            prize_text = tds[20].text.strip().replace(',', '')
            prize = float(prize_text) if prize_text else 0
        except (ValueError, IndexError):
            pass

        # DB挿入
        if horse_id:
            sex = sex_age[0] if sex_age else ""
            birth_year = None
            c.execute("INSERT OR IGNORE INTO horses (horse_id, name, sex) VALUES (?,?,?)",
                      (horse_id, horse_name, sex))

        if jockey_id:
            c.execute("INSERT OR IGNORE INTO jockeys VALUES (?,?)", (jockey_id, jockey_name))

        if trainer_id:
            c.execute("INSERT OR IGNORE INTO trainers VALUES (?,?)", (trainer_id, trainer_name))

        c.execute("""INSERT OR REPLACE INTO results VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                  (race_id, horse_id, jockey_id, trainer_id,
                   post_position, horse_number, weight_carried,
                   horse_weight, weight_change, finish_pos,
                   finish_time, margin, passing, last_3f,
                   odds_win, popularity, sex_age, prize))

    # 払戻金テーブル
    payout_tables = soup.find_all("table", class_="pay_table_01")
    for pt in payout_tables:
        for row in pt.find_all("tr"):
            tds = row.find_all(["th", "td"])
            if len(tds) < 3:
                continue
            bet_type = tds[0].text.strip()

            # <br>タグで区切られた複数エントリを分割
            def split_by_br(td):
                """<br>タグで区切られたテキストをリストで返す"""
                parts = []
                for item in td.children:
                    if hasattr(item, 'name') and item.name == 'br':
                        continue
                    text = item.text.strip() if hasattr(item, 'text') else str(item).strip()
                    if text:
                        parts.append(text)
                return parts if parts else [td.text.strip()]

            combos = split_by_br(tds[1])
            payouts_raw = split_by_br(tds[2])
            pops = split_by_br(tds[3]) if len(tds) > 3 else ['0'] * len(combos)

            for i, combo in enumerate(combos):
                combo = combo.strip()
                if not combo:
                    continue
                payout = payouts_raw[i] if i < len(payouts_raw) else '0'
                pop = pops[i] if i < len(pops) else '0'
                try:
                    payout_val = int(re.sub(r'[^\d]', '', payout)) if payout.strip() else 0
                except ValueError:
                    payout_val = 0
                try:
                    pop_val = int(re.sub(r'[^\d]', '', pop)) if pop.strip() else 0
                except ValueError:
                    pop_val = 0

                c.execute("INSERT OR REPLACE INTO payouts VALUES (?,?,?,?,?)",
                          (race_id, bet_type, combo, payout_val, pop_val))

    # スクレイプログ
    from datetime import datetime
    c.execute("INSERT OR REPLACE INTO scrape_log VALUES (?,?)",
              (race_id, datetime.now().isoformat()))

    conn.commit()
    return True


def _decode_result_html(content):
    """netkeibaライブ結果ページのバイト列をデコードする。

    2026-06-20頃にページがEUC-JPからUTF-8へ移行し、EUC-JP固定デコードでは
    券種名が文字化けしたままDBへ保存されてしまう(2026-07-05修復)。厳密デコードを
    両方試し、既知の券種語を含むテキストのみ採用する。判定不能なら例外を投げ、
    化けたデータをDBへ書き込まない。
    """
    candidates = []
    for enc in ("utf-8", "euc-jp"):
        try:
            candidates.append(content.decode(enc))
        except UnicodeDecodeError:
            continue
    for text in candidates:
        if "複勝" in text or "単勝" in text:
            return text
    if candidates:
        return candidates[0]
    for enc in ("utf-8", "euc-jp"):
        text = content.decode(enc, "replace")
        if "複勝" in text or "単勝" in text:
            return text
    raise ValueError("result page encoding detection failed")


def scrape_result_live_netkeiba(race_id, conn):
    """当日ライブ結果ページ(race.netkeiba.com)から着順＋払戻を取得してDBへ格納する。

    db.netkeiba.com(履歴DB)は当日結果の反映が遅く、レース当日17:30時点では
    結果テーブルが未掲載になる。対してライブ結果ページは当日中に着順・払戻を
    掲載するため、当日分のフォールバックとして使用する(エンコーディング自動判定)。

    既存の出走馬エントリ行(当日朝に作成済)を壊さないよう、着順は
    UPDATE results SET finish_position=... で更新する。払戻は payouts へ
    INSERT OR REPLACE する。着順>0 を1件以上書き込めたとき True を返す。
    """
    url = f"https://race.netkeiba.com/race/result.html?race_id={race_id}"
    try:
        res = requests.get(url, headers=HEADERS, timeout=15)
    except requests.RequestException as e:
        print(f"  Error fetching live {race_id}: {e}")
        return False
    if res.status_code != 200:
        print(f"  HTTP {res.status_code} (live) for {race_id}")
        return False

    try:
        html = _decode_result_html(res.content)
        soup = BeautifulSoup(html, "lxml")

        # 着順テーブル
        wrap = soup.find(id="All_Result_Table") or soup.find("table", class_=re.compile("RaceTable01"))
        if not wrap:
            div = soup.find("div", class_="ResultTableWrap")
            wrap = div.find("table") if div else None
        if not wrap:
            return False

        c = conn.cursor()
        updated = 0
        for tr in wrap.find_all("tr")[1:]:
            tds = tr.find_all("td")
            if len(tds) < 3:
                continue
            chaku = tds[0].get_text(strip=True)
            try:
                finish_pos = int(chaku)
            except ValueError:
                finish_pos = 0  # 中止・取消・除外
            uma = tds[2].get_text(strip=True)
            if not uma.isdigit():
                continue
            horse_number = int(uma)
            # 既存エントリ行の着順のみ更新（エントリ情報は保持）
            c.execute(
                "UPDATE results SET finish_position = ? WHERE race_id = ? AND horse_number = ?",
                (finish_pos, race_id, horse_number),
            )
            if finish_pos > 0:
                updated += 1

        if updated == 0:
            return False

        # 払戻テーブル
        _bet_normalize = {"3連複": "三連複", "3連単": "三連単"}
        _ordered_types = {"馬単", "三連単"}  # 順序あり券種はソートしない
        for pt in soup.find_all("table", class_=re.compile("Payout_Detail_Table")):
            for tr in pt.find_all("tr"):
                th = tr.find("th")
                tds = tr.find_all("td")
                if not th or len(tds) < 2:
                    continue
                bt = _bet_normalize.get(th.get_text(strip=True), th.get_text(strip=True))
                combos_raw = [s for s in tds[0].stripped_strings]
                payouts_raw = [s for s in tds[1].stripped_strings]
                pops_raw = [s for s in tds[2].stripped_strings] if len(tds) > 2 else []
                num = len(payouts_raw)
                if num == 0 or not combos_raw or len(combos_raw) % num != 0:
                    continue
                hpc = len(combos_raw) // num  # 1組合せあたりの頭数
                for i in range(num):
                    horses = combos_raw[i * hpc:(i + 1) * hpc]
                    if bt not in _ordered_types and hpc > 1:
                        try:
                            horses = sorted(horses, key=lambda x: int(x))
                        except ValueError:
                            pass
                    combo = " - ".join(horses)
                    pay = int(re.sub(r"[^\d]", "", payouts_raw[i]) or 0)
                    pop = int(re.sub(r"[^\d]", "", pops_raw[i]) or 0) if i < len(pops_raw) else 0
                    c.execute(
                        "INSERT OR REPLACE INTO payouts VALUES (?,?,?,?,?)",
                        (race_id, bt, combo, pay, pop),
                    )

        conn.commit()
        return True
    except Exception as e:
        print(f"  Parse error (live) for {race_id}: {e}")
        try:
            conn.rollback()
        except Exception:
            pass
        return False


def get_race_dates(year, month):
    """指定年月の開催日リストを取得"""
    url = f"https://db.netkeiba.com/race/list/{year}{month:02d}/"
    try:
        res = requests.get(url, headers=HEADERS, timeout=10)
        res.encoding = "EUC-JP"
    except requests.RequestException as e:
        print(f"Error fetching race dates: {e}")
        return []

    soup = BeautifulSoup(res.text, "lxml")
    dates = []
    for a in soup.find_all("a", href=True):
        m = re.search(r'/race/list/(\d{8})/', a.get("href", ""))
        if m:
            dates.append(m.group(1))
    return sorted(set(dates))


def get_race_id_list(date_str):
    """指定日のレースID一覧を取得"""
    url = f"https://db.netkeiba.com/race/list/{date_str}/"
    try:
        res = requests.get(url, headers=HEADERS, timeout=10)
        res.encoding = "EUC-JP"
    except requests.RequestException as e:
        print(f"Error fetching race list: {e}")
        return []

    soup = BeautifulSoup(res.text, "lxml")
    race_ids = []

    for a in soup.find_all("a", href=True):
        m = re.search(r'/race/(\d{12})/', a.get("href", ""))
        if m:
            race_ids.append(m.group(1))

    return sorted(set(race_ids))


def scrape_month(year, month, conn):
    """指定年月の全レースを取得"""
    print(f"\n=== {year}年{month}月 ===")
    dates = get_race_dates(year, month)
    print(f"開催日数: {len(dates)}")

    c = conn.cursor()
    scraped = 0
    skipped = 0
    total = 0

    for date_str in dates:
        time.sleep(REQUEST_INTERVAL)
        race_ids = get_race_id_list(date_str)
        total += len(race_ids)
        print(f"  {date_str}: {len(race_ids)}レース")

        for race_id in race_ids:
            # 既にスクレイプ済みならスキップ
            c.execute("SELECT 1 FROM scrape_log WHERE race_id = ?", (race_id,))
            if c.fetchone():
                skipped += 1
                continue

            print(f"    取得中: {race_id}", end="")
            if scrape_race(race_id, conn):
                scraped += 1
                print(" OK")
            else:
                print(" FAILED")

            time.sleep(REQUEST_INTERVAL)

    print(f"取得: {scraped}, スキップ: {skipped}, 合計: {total}")
    return scraped


def main():
    """メイン処理"""
    conn = init_db()

    if len(sys.argv) < 2:
        print("Usage:")
        print("  python3 scraper.py 2025          # 2025年の全データ取得")
        print("  python3 scraper.py 2025 6        # 2025年6月のデータ取得")
        print("  python3 scraper.py race 202505040811  # 特定レース取得")
        print("  python3 scraper.py status         # DB状況確認")
        sys.exit(1)

    if sys.argv[1] == "status":
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM races")
        print(f"レース数: {c.fetchone()[0]}")
        c.execute("SELECT COUNT(*) FROM results")
        print(f"出走結果数: {c.fetchone()[0]}")
        c.execute("SELECT COUNT(*) FROM horses")
        print(f"馬数: {c.fetchone()[0]}")
        c.execute("SELECT COUNT(*) FROM jockeys")
        print(f"騎手数: {c.fetchone()[0]}")
        c.execute("SELECT COUNT(*) FROM payouts")
        print(f"払戻データ数: {c.fetchone()[0]}")
        c.execute("SELECT MIN(date), MAX(date) FROM races WHERE date != ''")
        row = c.fetchone()
        print(f"期間: {row[0]} 〜 {row[1]}")
        conn.close()
        return

    if sys.argv[1] == "race":
        race_id = sys.argv[2]
        print(f"レース {race_id} を取得中...")
        if scrape_race(race_id, conn):
            print("完了")
        else:
            print("失敗")
        conn.close()
        return

    year = int(sys.argv[1])
    if len(sys.argv) >= 3:
        month = int(sys.argv[2])
        scrape_month(year, month, conn)
    else:
        for month in range(1, 13):
            scrape_month(year, month, conn)

    conn.close()
    print("\n完了")


if __name__ == "__main__":
    main()
