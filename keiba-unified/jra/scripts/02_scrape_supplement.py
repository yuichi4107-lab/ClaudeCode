"""データ補完スクレイパー

race.netkeiba.com を使用して不足レースデータを補完する。
db.netkeiba.com がブロックされているため、race.netkeiba.com の
result.html ページからデータを取得する。

使い方:
    python scripts/02_scrape_supplement.py [--year YEAR] [--venue VV] [--interval 1.5]
"""

import os
import re
import sys
import time
import sqlite3
import argparse
from datetime import datetime
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import requests
from bs4 import BeautifulSoup

from src.database.db_manager import DBManager
from src.utils.config_loader import get_db_path
from src.utils.constants import VENUE_CODES

# --- Config ---
BASE_URL = "https://race.netkeiba.com/race/result.html?race_id={race_id}"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ja,en-US;q=0.7,en;q=0.3",
    "Referer": "https://race.netkeiba.com/",
}
TIMEOUT = 30

# Bet type normalization (race.netkeiba uses "3連複" etc.)
BET_TYPE_NORMALIZE = {
    "単勝": "単勝",
    "複勝": "複勝",
    "枠連": "枠連",
    "馬連": "馬連",
    "ワイド": "ワイド",
    "馬単": "馬単",
    "三連複": "三連複",
    "三連単": "三連単",
    "3連複": "三連複",
    "3連単": "三連単",
}


def make_race_id(year: int, venue: str, kai: int, nichi: int, race: int) -> str:
    return f"{year}{venue}{kai:02d}{nichi:02d}{race:02d}"


def fetch_page(race_id: str, interval: float) -> Optional[BeautifulSoup]:
    """Fetch and parse a race result page. Returns None if no result table."""
    url = BASE_URL.format(race_id=race_id)
    time.sleep(interval)
    try:
        resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"  [ERROR] {race_id}: {e}")
        return None

    resp.encoding = "euc-jp"
    soup = BeautifulSoup(resp.text, "lxml")

    # Check if page has valid result table
    table = soup.select_one("table.RaceTable01")
    if not table:
        return None
    data_rows = [r for r in table.select("tr") if r.select("td") and len(r.select("td")) >= 10]
    if not data_rows:
        return None

    return soup


def extract_date(soup: BeautifulSoup, race_id: str) -> Optional[str]:
    """Extract race date from the page."""
    # Method 1: kaisai_date in active link
    active = soup.select_one(".Active a")
    if active:
        href = active.get("href", "")
        m = re.search(r"kaisai_date=(\d{8})", href)
        if m:
            d = m.group(1)
            return f"{d[:4]}-{d[4:6]}-{d[6:8]}"

    # Method 2: Full date in page text
    text = soup.get_text()
    m = re.search(r"(\d{4})[年/](\d{1,2})[月/](\d{1,2})", text)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"

    # Method 3: Derive from race_id year + RaceData02 month/day info
    # Fallback: use None and let caller handle
    return None


def parse_race_info(soup: BeautifulSoup, race_id: str) -> Dict:
    """Parse race metadata from race.netkeiba.com result page."""
    info = {
        "race_id": race_id,
        "race_date": None,
        "venue_code": race_id[4:6],
        "venue_name": VENUE_CODES.get(race_id[4:6], ""),
        "kai": int(race_id[6:8]),
        "nichi": int(race_id[8:10]),
        "race_number": int(race_id[10:12]),
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

    # Date
    info["race_date"] = extract_date(soup, race_id)

    # Race name
    name_tag = soup.select_one(".RaceName")
    if name_tag:
        info["race_name"] = name_tag.get_text(strip=True)

    # Grade
    icon = soup.select_one(".RaceName img")
    if icon:
        alt = icon.get("alt", "").upper()
        for g in ["G1", "G2", "G3"]:
            if g in alt:
                info["grade"] = g
                break

    # RaceData01: distance, weather, track condition
    rd1 = soup.select_one(".RaceData01")
    if rd1:
        rd1_text = rd1.get_text(strip=True)
        # Distance and surface
        m = re.search(r"(芝|ダート|障害)\D*?(\d{3,4})m", rd1_text)
        if m:
            info["race_type"] = m.group(1)
            info["distance"] = int(m.group(2))
        # Direction
        m = re.search(r"(右|左|直線)", rd1_text)
        if m:
            info["direction"] = m.group(1)
        # Weather
        m = re.search(r"天候[:：]\s*(晴|曇|雨|小雨|小雪|雪)", rd1_text)
        if m:
            info["weather"] = m.group(1)
        # Track condition
        m = re.search(r"馬場[:：]\s*(良|稍重|重|不良)", rd1_text)
        if m:
            info["track_condition"] = m.group(1)

    # RaceData02: grade, horse count, prize
    rd2 = soup.select_one(".RaceData02")
    if rd2:
        rd2_text = rd2.get_text(strip=True)
        # Grade from text
        if not info["grade"]:
            if "オープン" in rd2_text or "OP" in rd2_text:
                info["grade"] = "オープン"
        # Horse count
        m = re.search(r"(\d+)頭", rd2_text)
        if m:
            info["horse_count"] = int(m.group(1))
        # Prize (1st) - format: "本賞金:2700,1100,680,..." take first
        m = re.search(r"本賞金[:：]?([\d,]+)", rd2_text)
        if m:
            try:
                # First number before any non-digit-comma
                first_prize = m.group(1).split(",")[0] if "," in m.group(1) else m.group(1)
                info["prize_1st"] = int(first_prize.replace(",", ""))
            except (ValueError, IndexError):
                pass

    # Fallback horse_count from table rows
    if not info["horse_count"]:
        table = soup.select_one("table.RaceTable01")
        if table:
            data_rows = [r for r in table.select("tr")
                         if r.select("td") and len(r.select("td")) >= 10]
            info["horse_count"] = len(data_rows)

    return info


def parse_results(soup: BeautifulSoup, race_id: str) -> List[Dict]:
    """Parse result table from race.netkeiba.com.

    Column mapping:
    [0]着順 [1]枠 [2]馬番 [3]馬名 [4]性齢 [5]斤量
    [6]騎手 [7]タイム [8]着差 [9]人気 [10]単勝オッズ [11]後3F
    [12]コーナー通過順 [13]厩舎 [14]馬体重(増減)
    """
    results = []
    table = soup.select_one("table.RaceTable01")
    if not table:
        return results

    for row in table.select("tr"):
        cells = row.select("td")
        if len(cells) < 14:
            continue

        r = {"race_id": race_id}

        # [0] 着順
        try:
            r["finish_order"] = int(cells[0].get_text(strip=True))
        except ValueError:
            r["finish_order"] = None

        # [1] 枠番
        try:
            r["frame_number"] = int(cells[1].get_text(strip=True))
        except ValueError:
            r["frame_number"] = None

        # [2] 馬番
        try:
            r["horse_number"] = int(cells[2].get_text(strip=True))
        except ValueError:
            r["horse_number"] = None

        # [3] 馬名 + horse_id
        r["horse_name"] = cells[3].get_text(strip=True)
        r["horse_id"] = None
        link = cells[3].select_one("a")
        if link:
            m = re.search(r"/horse/(\w+)", link.get("href", ""))
            if m:
                r["horse_id"] = m.group(1)

        # [4] 性齢
        r["sex_age"] = cells[4].get_text(strip=True)

        # [5] 斤量
        try:
            r["weight_carry"] = float(cells[5].get_text(strip=True))
        except ValueError:
            r["weight_carry"] = None

        # [6] 騎手 + jockey_id
        r["jockey_name"] = cells[6].get_text(strip=True)
        r["jockey_id"] = None
        link = cells[6].select_one("a")
        if link:
            m = re.search(r"/jockey/(?:result/(?:recent/)?)?(\w+)/", link.get("href", ""))
            if m:
                r["jockey_id"] = m.group(1)

        # [7] タイム
        r["finish_time"] = _parse_time(cells[7].get_text(strip=True))

        # [8] 着差
        r["margin"] = cells[8].get_text(strip=True) or None

        # [9] 人気
        try:
            r["popularity"] = int(cells[9].get_text(strip=True))
        except ValueError:
            r["popularity"] = None

        # [10] 単勝オッズ
        try:
            r["odds"] = float(cells[10].get_text(strip=True))
        except ValueError:
            r["odds"] = None

        # [11] 後3F
        try:
            r["final_3f"] = float(cells[11].get_text(strip=True))
        except ValueError:
            r["final_3f"] = None

        # [12] コーナー通過順
        r["corner_positions"] = cells[12].get_text(strip=True) or None

        # [13] 厩舎 (trainer)
        r["trainer_name"] = None
        r["trainer_id"] = None
        trainer_link = cells[13].select_one("a")
        if trainer_link:
            raw = trainer_link.get_text(strip=True)
            # Remove affiliation prefix like "[東]" or "美浦"
            r["trainer_name"] = re.sub(r"^(美浦|栗東)", "", raw)
            m = re.search(r"/trainer/(?:result/(?:recent/)?)?(\w+)/",
                          trainer_link.get("href", ""))
            if m:
                r["trainer_id"] = m.group(1)
        else:
            r["trainer_name"] = cells[13].get_text(strip=True) or None

        # [14] 馬体重(増減)
        wt = cells[14].get_text(strip=True)
        r["horse_weight"], r["weight_change"] = _parse_weight(wt)

        results.append(r)

    return results


def parse_payoffs(soup: BeautifulSoup, race_id: str) -> List[Dict]:
    """Parse payout tables from race.netkeiba.com.

    Structure: table.Payout_Detail_Table
    - Single-horse bets (単勝): <div><span>N</span></div>
    - Multi-horse bets (馬連 etc.): <ul><li><span>N</span></li>...</ul>
    - Multi-entry bets (複勝, ワイド): multiple <div>s or <ul>s per row
    """
    payoffs = []
    tables = soup.select("table.Payout_Detail_Table")

    for table in tables:
        for row in table.select("tr"):
            th = row.select_one("th")
            tds = row.select("td")
            if not th or len(tds) < 2:
                continue

            bet_type_raw = th.get_text(strip=True)
            bet_type = BET_TYPE_NORMALIZE.get(bet_type_raw, bet_type_raw)

            combo_td = tds[0]
            payout_td = tds[1]
            pop_td = tds[2] if len(tds) >= 3 else None

            # Parse based on bet type structure
            if bet_type in ("単勝",):
                # Single number
                combos = _extract_single_combos(combo_td)
                payouts_raw = _extract_payouts(payout_td)
                pops_raw = _extract_pops(pop_td) if pop_td else []
                for i, combo in enumerate(combos):
                    payout = payouts_raw[i] if i < len(payouts_raw) else 0
                    pop = pops_raw[i] if i < len(pops_raw) else 0
                    if combo and payout > 0:
                        payoffs.append({
                            "race_id": race_id,
                            "bet_type": bet_type,
                            "combination": combo,
                            "payout": payout,
                            "popularity": pop,
                        })

            elif bet_type in ("複勝",):
                # Multiple single entries (each <div> is one entry)
                combos = _extract_single_combos(combo_td)
                payouts_raw = _extract_payouts(payout_td)
                pops_raw = _extract_pops(pop_td) if pop_td else []
                for i, combo in enumerate(combos):
                    payout = payouts_raw[i] if i < len(payouts_raw) else 0
                    pop = pops_raw[i] if i < len(pops_raw) else 0
                    if combo and payout > 0:
                        payoffs.append({
                            "race_id": race_id,
                            "bet_type": bet_type,
                            "combination": combo,
                            "payout": payout,
                            "popularity": pop,
                        })

            elif bet_type in ("ワイド",):
                # Multiple multi-number entries (each <ul> is one entry)
                groups = combo_td.select("ul")
                payouts_raw = _extract_payouts(payout_td)
                pops_raw = _extract_pops(pop_td) if pop_td else []
                for i, ul in enumerate(groups):
                    nums = [li.get_text(strip=True) for li in ul.select("li > span") if li.get_text(strip=True)]
                    if not nums:
                        nums = [li.get_text(strip=True) for li in ul.select("span") if li.get_text(strip=True)]
                    combo = " - ".join(nums)
                    payout = payouts_raw[i] if i < len(payouts_raw) else 0
                    pop = pops_raw[i] if i < len(pops_raw) else 0
                    if combo and payout > 0:
                        payoffs.append({
                            "race_id": race_id,
                            "bet_type": bet_type,
                            "combination": combo,
                            "payout": payout,
                            "popularity": pop,
                        })

            else:
                # 枠連, 馬連, 馬単, 三連複, 三連単: single multi-number entry
                ul = combo_td.select_one("ul")
                if ul:
                    nums = [li.get_text(strip=True) for li in ul.select("li > span") if li.get_text(strip=True)]
                    if not nums:
                        nums = [li.get_text(strip=True) for li in ul.select("span") if li.get_text(strip=True)]
                else:
                    # Fallback: split by separator
                    text = combo_td.get_text("|", strip=True)
                    nums = [n.strip() for n in text.split("|") if n.strip()]
                combo = " - ".join(nums)
                payouts_raw = _extract_payouts(payout_td)
                pops_raw = _extract_pops(pop_td) if pop_td else []
                payout = payouts_raw[0] if payouts_raw else 0
                pop = pops_raw[0] if pops_raw else 0
                if combo and payout > 0:
                    payoffs.append({
                        "race_id": race_id,
                        "bet_type": bet_type,
                        "combination": combo,
                        "payout": payout,
                        "popularity": pop,
                    })

    return payoffs


def _extract_single_combos(td) -> List[str]:
    """Extract individual number entries from <div><span> structure."""
    spans = td.select("div > span")
    nums = [s.get_text(strip=True) for s in spans if s.get_text(strip=True)]
    if nums:
        return nums
    # Fallback
    text = td.get_text("|", strip=True)
    return [n.strip() for n in text.split("|") if n.strip()]


def _extract_payouts(td) -> List[int]:
    """Extract payout amounts from td."""
    text = td.get_text("|", strip=True)
    parts = [p.strip() for p in text.split("|") if p.strip()]
    results = []
    for p in parts:
        p_clean = p.replace(",", "").replace("円", "").replace("¥", "").strip()
        m = re.search(r"(\d+)", p_clean)
        if m:
            results.append(int(m.group(1)))
    return results


def _extract_pops(td) -> List[int]:
    """Extract popularity from td."""
    text = td.get_text("|", strip=True)
    parts = [p.strip() for p in text.split("|") if p.strip()]
    results = []
    for p in parts:
        m = re.search(r"(\d+)", p)
        results.append(int(m.group(1)) if m else 0)
    return results


def _parse_time(time_str: str) -> Optional[float]:
    """Parse time string like '1:35.2' -> 95.2"""
    if not time_str or not time_str.strip():
        return None
    time_str = time_str.strip()
    m = re.match(r"(\d+):(\d+)\.(\d+)", time_str)
    if m:
        return int(m.group(1)) * 60.0 + int(m.group(2)) + int(m.group(3)) * 0.1
    m = re.match(r"(\d+)\.(\d+)", time_str)
    if m:
        return float(time_str)
    return None


def _parse_weight(wt_str: str) -> Tuple[Optional[int], Optional[int]]:
    """Parse horse weight like '480(+4)' -> (480, 4)"""
    if not wt_str or not wt_str.strip():
        return None, None
    m = re.match(r"(\d+)\(([+-]?\d+)\)", wt_str.strip())
    if m:
        return int(m.group(1)), int(m.group(2))
    m = re.match(r"(\d+)", wt_str.strip())
    if m:
        return int(m.group(1)), None
    return None, None


def get_scraped_ids(db_path: str) -> set:
    """Get already-scraped race IDs from DB."""
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT race_id FROM scrape_log WHERE status = 'done'"
        ).fetchall()
        return {r[0] for r in rows}
    finally:
        conn.close()


def save_race_data(db: DBManager, race_info: Dict, results: List[Dict],
                   payoffs: List[Dict], race_id: str):
    """Save parsed data to database."""
    try:
        db.insert_race(race_info)
        if results:
            db.insert_race_results_batch(results)
        if payoffs:
            db.insert_payoffs_batch(payoffs)
        db.update_scrape_log(race_id, "done")
    except Exception as e:
        db.update_scrape_log(race_id, "error", str(e))
        print(f"  [DB ERROR] {race_id}: {e}")


def scrape_venue_year(db: DBManager, year: int, venue: str, scraped: set,
                      interval: float, stats: Dict):
    """Scrape all races for one venue in one year."""
    venue_name = VENUE_CODES.get(venue, venue)
    print(f"\n--- {year} {venue_name}({venue}) ---")

    for kai in range(1, 7):
        # Probe kai: check if nichi=01 race=01 exists
        probe_id = make_race_id(year, venue, kai, 1, 1)
        if probe_id in scraped:
            # Kai exists (already have R01), check remaining
            pass
        else:
            soup = fetch_page(probe_id, interval)
            stats["requests"] += 1
            if soup is None:
                # This kai doesn't exist, skip
                continue
            # Save this probe result
            race_info = parse_race_info(soup, probe_id)
            if not race_info["race_date"]:
                print(f"  [WARN] No date for {probe_id}, skipping kai")
                continue
            results = parse_results(soup, probe_id)
            payoffs_data = parse_payoffs(soup, probe_id)
            save_race_data(db, race_info, results, payoffs_data, probe_id)
            scraped.add(probe_id)
            stats["new"] += 1
            print(f"  {probe_id} ({race_info['race_date']}) "
                  f"R:{len(results)} P:{len(payoffs_data)}")

        # Sweep remaining races for nichi=01
        for race in range(2, 13):
            rid = make_race_id(year, venue, kai, 1, race)
            if rid in scraped:
                continue
            soup = fetch_page(rid, interval)
            stats["requests"] += 1
            if soup is None:
                break  # No more races this day
            race_info = parse_race_info(soup, rid)
            results = parse_results(soup, rid)
            payoffs_data = parse_payoffs(soup, rid)
            save_race_data(db, race_info, results, payoffs_data, rid)
            scraped.add(rid)
            stats["new"] += 1

        # Now sweep nichi 02-12
        for nichi in range(2, 13):
            # Probe nichi
            probe_id = make_race_id(year, venue, kai, nichi, 1)
            if probe_id in scraped:
                nichi_valid = True
            else:
                soup = fetch_page(probe_id, interval)
                stats["requests"] += 1
                if soup is None:
                    # This nichi doesn't exist; try next (might have gaps)
                    continue
                race_info = parse_race_info(soup, probe_id)
                results = parse_results(soup, probe_id)
                payoffs_data = parse_payoffs(soup, probe_id)
                save_race_data(db, race_info, results, payoffs_data, probe_id)
                scraped.add(probe_id)
                stats["new"] += 1
                nichi_valid = True
                date_str = race_info.get("race_date", "?")
                print(f"  {probe_id} ({date_str}) "
                      f"R:{len(results)} P:{len(payoffs_data)}")

            if not nichi_valid:
                continue

            # Scrape remaining races for this nichi
            for race in range(2, 13):
                rid = make_race_id(year, venue, kai, nichi, race)
                if rid in scraped:
                    continue
                soup = fetch_page(rid, interval)
                stats["requests"] += 1
                if soup is None:
                    break
                race_info = parse_race_info(soup, rid)
                results = parse_results(soup, rid)
                payoffs_data = parse_payoffs(soup, rid)
                save_race_data(db, race_info, results, payoffs_data, rid)
                scraped.add(rid)
                stats["new"] += 1

        # Progress update
        print(f"  kai={kai} done | Total new: {stats['new']}, "
              f"requests: {stats['requests']}")


def main():
    parser = argparse.ArgumentParser(description="Supplement missing race data")
    parser.add_argument("--year", type=int, help="Scrape specific year only")
    parser.add_argument("--venue", type=str, help="Scrape specific venue code only (01-10)")
    parser.add_argument("--interval", type=float, default=1.5,
                        help="Request interval in seconds (default: 1.5)")
    args = parser.parse_args()

    db_path = get_db_path()
    db = DBManager(db_path)
    db.init_db()

    scraped = get_scraped_ids(db_path)
    print(f"Already scraped: {len(scraped)} races")

    # Count existing by venue
    conn = sqlite3.connect(db_path)
    venue_counts = conn.execute(
        "SELECT venue_code, COUNT(*) FROM races GROUP BY venue_code ORDER BY venue_code"
    ).fetchall()
    conn.close()
    print("\nExisting races by venue:")
    for vc, cnt in venue_counts:
        print(f"  {vc} ({VENUE_CODES.get(vc, '?')}): {cnt}")

    years = [args.year] if args.year else [2021, 2022, 2023, 2024, 2025]
    venues = [args.venue] if args.venue else [
        "05", "06", "07", "08", "09", "10",  # Missing/underrepresented first
        "01", "02", "03", "04",               # Then existing ones
    ]

    stats = {"new": 0, "requests": 0}
    start_time = time.time()

    print(f"\nStarting scrape: years={years}, venues={venues}")
    print(f"Request interval: {args.interval}s")
    print("=" * 60)

    try:
        for year in years:
            for venue in venues:
                scrape_venue_year(db, year, venue, scraped, args.interval, stats)
    except KeyboardInterrupt:
        print("\n\n[INTERRUPTED] Saving progress...")

    elapsed = time.time() - start_time
    print("\n" + "=" * 60)
    print(f"Done! New races: {stats['new']}, "
          f"Requests: {stats['requests']}, "
          f"Time: {elapsed/60:.1f} min")

    # Final count
    conn = sqlite3.connect(db_path)
    total = conn.execute("SELECT COUNT(*) FROM races").fetchone()[0]
    venue_counts = conn.execute(
        "SELECT venue_code, COUNT(*) FROM races GROUP BY venue_code ORDER BY venue_code"
    ).fetchall()
    conn.close()
    print(f"Total races in DB: {total}")
    for vc, cnt in venue_counts:
        print(f"  {vc} ({VENUE_CODES.get(vc, '?')}): {cnt}")


if __name__ == "__main__":
    main()
