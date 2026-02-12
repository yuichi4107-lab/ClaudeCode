import logging
import re

from bs4 import BeautifulSoup

from nankan_predictor.scraper.base import BaseScraper
from nankan_predictor.config.settings import VENUE_NAMES

logger = logging.getLogger(__name__)


def _safe_int(s: str):
    try:
        return int(str(s).strip().replace(",", ""))
    except (ValueError, TypeError):
        return None


def _safe_float(s: str):
    try:
        return float(str(s).strip().replace(",", ""))
    except (ValueError, TypeError):
        return None


def _parse_time(s: str):
    """'1:23.4' -> 83.4 秒"""
    s = str(s).strip()
    m = re.match(r"(?:(\d+):)?(\d+)\.(\d+)", s)
    if not m:
        return None
    minutes = int(m.group(1) or 0)
    seconds = int(m.group(2))
    tenths = int(m.group(3))
    return minutes * 60 + seconds + tenths / 10


def _extract_id(href: str, kind: str) -> str:
    """href から horse_id / jockey_id を抽出する。"""
    parts = [p for p in href.strip("/").split("/") if p]
    # 例: /horse/2019104308/ -> ["horse", "2019104308"]
    if len(parts) >= 2 and parts[0] == kind:
        return parts[1]
    if len(parts) >= 3 and parts[1] == kind:
        return parts[2]
    return ""


class RaceResultScraper(BaseScraper):
    """db.netkeiba.com/race/{race_id}/ から確定レース結果をスクレイピングする。"""

    def scrape(self, race_id: str) -> dict:
        url = f"https://db.netkeiba.com/race/{race_id}/"
        logger.info("Scraping result: %s", race_id)
        html = self.get(url)
        soup = BeautifulSoup(html, "lxml")
        return {
            "race_info": self._parse_race_info(soup, race_id),
            "entries": self._parse_result_table(soup, race_id),
            "payouts": self._parse_payouts(soup, race_id),
        }

    def _parse_payouts(self, soup: BeautifulSoup, race_id: str) -> list[dict]:
        """払戻金テーブルから馬単・単勝の払戻情報を取得する。"""
        payouts = []
        # db.netkeiba.com の払戻テーブルは .pay_block または table.pay_table
        for table in soup.select("table.pay_table_01, .payout_table, div.pay_block table"):
            rows = table.select("tr")
            for tr in rows:
                th = tr.select_one("th")
                if not th:
                    continue
                bet_type_text = th.get_text(strip=True)

                if "馬単" in bet_type_text:
                    bet_type = "exacta"
                elif "単勝" in bet_type_text:
                    bet_type = "win"
                else:
                    continue

                tds = tr.select("td")
                for td in tds:
                    text = td.get_text(strip=True)
                    # 組み合わせ: "3→7" や "3 - 7" など
                    combo_m = re.search(r"(\d+)[→\-\s]+(\d+)", text)
                    # 払戻金額: "12,340円" など
                    amount_m = re.search(r"([\d,]+)円", text)
                    if combo_m and amount_m:
                        combination = f"{combo_m.group(1)}-{combo_m.group(2)}"
                        payout = float(amount_m.group(1).replace(",", ""))
                        payouts.append({
                            "race_id": race_id,
                            "bet_type": bet_type,
                            "combination": combination,
                            "payout": payout,
                        })
                    elif bet_type == "win":
                        # 単勝は馬番と払戻が別セルのことが多い
                        horse_m = re.search(r"^\s*(\d+)\s*$", text)
                        if horse_m:
                            # 次のセルを探す
                            pass

        return payouts

    def _parse_race_info(self, soup: BeautifulSoup, race_id: str) -> dict:
        info = {"race_id": race_id}

        # 会場・日付・レース番号はレースIDから抽出
        info["venue_code"] = race_id[4:6]
        info["venue_name"] = VENUE_NAMES.get(race_id[4:6], race_id[4:6])
        info["race_date"] = f"{race_id[0:4]}-{race_id[6:8]}-{race_id[8:10]}"
        info["race_number"] = _safe_int(race_id[10:12])

        race_name_el = soup.select_one(".RaceName")
        if race_name_el:
            info["race_name"] = race_name_el.get_text(strip=True)

        data01 = soup.select_one(".RaceData01")
        if data01:
            text = data01.get_text()
            m = re.search(r"(ダ|芝)(\d+)m", text)
            if m:
                info["track_type"] = "ダート" if m.group(1) == "ダ" else "芝"
                info["distance"] = int(m.group(2))
            weather_m = re.search(r"天候\s*:\s*(\S+)", text)
            cond_m = re.search(r"馬場\s*:\s*(\S+)", text)
            if weather_m:
                info["weather"] = weather_m.group(1)
            if cond_m:
                info["track_condition"] = cond_m.group(1)

        return info

    def _parse_result_table(self, soup: BeautifulSoup, race_id: str) -> list[dict]:
        entries = []
        table = soup.select_one("table.race_table_01")
        if not table:
            logger.warning("Result table not found for race_id=%s", race_id)
            return entries

        rows = table.select("tr")[1:]
        for tr in rows:
            tds = tr.select("td")
            if len(tds) < 12:
                continue

            entry: dict = {"race_id": race_id}
            entry["finish_position"] = _safe_int(tds[0].get_text(strip=True))
            entry["gate_number"] = _safe_int(tds[1].get_text(strip=True))
            entry["horse_number"] = _safe_int(tds[2].get_text(strip=True))

            horse_a = tds[3].select_one("a")
            if horse_a:
                entry["horse_name"] = horse_a.get_text(strip=True)
                entry["horse_id"] = _extract_id(horse_a.get("href", ""), "horse")

            age_text = tds[4].get_text(strip=True)
            age_m = re.match(r"(\d+)(牡|牝|セ|騸)?", age_text)
            if age_m:
                entry["horse_age"] = int(age_m.group(1))
                entry["horse_sex"] = age_m.group(2) or ""

            entry["weight_carried"] = _safe_float(tds[5].get_text(strip=True))

            jockey_a = tds[6].select_one("a")
            if jockey_a:
                entry["jockey_name"] = jockey_a.get_text(strip=True)
                entry["jockey_id"] = _extract_id(jockey_a.get("href", ""), "jockey")

            entry["finish_time"] = _parse_time(tds[7].get_text(strip=True))
            entry["margin"] = tds[8].get_text(strip=True)
            entry["passing_positions"] = tds[9].get_text(strip=True) if len(tds) > 9 else None
            entry["pace"] = tds[10].get_text(strip=True) if len(tds) > 10 else None
            entry["last_3f_time"] = _safe_float(tds[11].get_text(strip=True)) if len(tds) > 11 else None
            entry["trainer_name"] = tds[12].get_text(strip=True) if len(tds) > 12 else None

            # 馬体重: "456(+2)" のような形式
            if len(tds) > 13:
                weight_text = tds[13].get_text(strip=True)
                wm = re.match(r"(\d+)\(([+-]?\d+)\)", weight_text)
                if wm:
                    entry["horse_weight"] = int(wm.group(1))
                    entry["weight_change"] = int(wm.group(2))

            entry["win_odds"] = _safe_float(tds[14].get_text(strip=True)) if len(tds) > 14 else None
            entry["popularity_rank"] = _safe_int(tds[15].get_text(strip=True)) if len(tds) > 15 else None

            pos = entry.get("finish_position")
            entry["is_winner"] = 1 if pos == 1 else (0 if pos is not None else None)
            entries.append(entry)

        return entries
