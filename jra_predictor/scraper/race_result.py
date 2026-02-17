import logging
import re

from bs4 import BeautifulSoup

from jra_predictor.scraper.base import BaseScraper
from jra_predictor.config.settings import VENUE_NAMES_JP

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
    """db.netkeiba.com/race/{race_id}/ から確定レース結果をスクレイピングする（JRA中央競馬）。"""

    def scrape(self, race_id: str) -> dict:
        url = f"https://db.netkeiba.com/race/{race_id}/"
        logger.info("Scraping result: %s", race_id)
        html = self.get(url)
        soup = BeautifulSoup(html, "lxml")
        entries = self._parse_result_table(soup, race_id)
        race_info = self._parse_race_info(soup, race_id)
        race_info["field_size"] = len(entries)
        return {
            "race_info": race_info,
            "entries": entries,
            "payouts": self._parse_payouts(soup, race_id),
        }

    def _parse_payouts(self, soup: BeautifulSoup, race_id: str) -> list[dict]:
        """払戻金テーブルから馬連・三連複・単勝の払戻情報を取得する。"""
        payouts = []
        for table in soup.select("table.pay_table_01"):
            rows = table.select("tr")
            for tr in rows:
                cells = tr.select("td, th")
                if len(cells) < 2:
                    continue

                bet_type_text = cells[0].get_text(strip=True)

                if "三連複" in bet_type_text:
                    bet_type = "trio"
                elif "馬連" in bet_type_text:
                    bet_type = "quinella"
                elif "単勝" in bet_type_text:
                    bet_type = "win"
                else:
                    continue

                if len(cells) >= 3:
                    combo_text = cells[1].get_text(strip=True)
                    amount_text = cells[2].get_text(strip=True)
                    amount_m = re.search(r"([\d,]+)", amount_text)

                    if bet_type == "trio":
                        # 三連複: "3-7-12" のように3頭の組み合わせ
                        nums = re.findall(r"\d+", combo_text)
                        if len(nums) >= 3 and amount_m:
                            # ソートして順不同の正規形にする
                            sorted_nums = sorted(nums[:3], key=int)
                            combination = "-".join(sorted_nums)
                            payout = float(amount_m.group(1).replace(",", ""))
                            payouts.append({
                                "race_id": race_id,
                                "bet_type": bet_type,
                                "combination": combination,
                                "payout": payout,
                            })
                    elif bet_type == "quinella":
                        # 馬連: "3-7" のように2頭（順不同なのでソート）
                        combo_m = re.search(r"(\d+)\D+(\d+)", combo_text)
                        if combo_m and amount_m:
                            nums = sorted([int(combo_m.group(1)), int(combo_m.group(2))])
                            combination = f"{nums[0]}-{nums[1]}"
                            payout = float(amount_m.group(1).replace(",", ""))
                            payouts.append({
                                "race_id": race_id,
                                "bet_type": bet_type,
                                "combination": combination,
                                "payout": payout,
                            })
                    else:
                        # 単勝: "3" のように1頭
                        combo_m = re.search(r"(\d+)", combo_text)
                        if combo_m and amount_m:
                            combination = combo_m.group(1)
                            payout = float(amount_m.group(1).replace(",", ""))
                            payouts.append({
                                "race_id": race_id,
                                "bet_type": bet_type,
                                "combination": combination,
                                "payout": payout,
                            })

        return payouts

    def _parse_race_info(self, soup: BeautifulSoup, race_id: str) -> dict:
        info = {"race_id": race_id}

        # 会場・日付・レース番号はレースIDから抽出
        info["venue_code"] = race_id[4:6]
        info["venue_name"] = VENUE_NAMES_JP.get(race_id[4:6], race_id[4:6])
        info["race_date"] = f"{race_id[0:4]}-{race_id[6:8]}-{race_id[8:10]}"
        info["race_number"] = _safe_int(race_id[10:12])

        race_name_el = soup.select_one(".RaceName")
        if race_name_el:
            info["race_name"] = race_name_el.get_text(strip=True)

        data01 = soup.select_one(".RaceData01, .race_data")
        if data01:
            text = data01.get_text()
            # 距離とコース種別: "芝右1600m" "ダ左1200m" "芝直線1000m"
            m = re.search(r"(ダ|芝|障)(右|左|直線)?(\d+)m", text)
            if m:
                info["track_type"] = {"ダ": "ダート", "芝": "芝", "障": "障害"}.get(m.group(1), m.group(1))
                info["course_direction"] = m.group(2) or ""
                info["distance"] = int(m.group(3))
            weather_m = re.search(r"天候\s*:\s*(\S+)", text)
            cond_m = re.search(r"馬場\s*:\s*(\S+)", text)
            if weather_m:
                info["weather"] = weather_m.group(1)
            if cond_m:
                info["track_condition"] = cond_m.group(1)

        # レース条件 (RaceData02): "新馬", "未勝利", "1勝クラス", "オープン" 等
        data02 = soup.select_one(".RaceData02")
        if data02:
            text02 = data02.get_text()
            info["race_class"] = self._parse_race_class(text02)

        # fallback
        if "distance" not in info or info.get("distance") is None:
            alt = soup.select_one(".raceData, .data01")
            if alt:
                text = alt.get_text()
                m = re.search(r"(ダ|芝|障)(右|左|直線)?(\d+)m", text)
                if m:
                    info["track_type"] = {"ダ": "ダート", "芝": "芝", "障": "障害"}.get(m.group(1), m.group(1))
                    info["course_direction"] = m.group(2) or ""
                    info["distance"] = int(m.group(3))

        return info

    @staticmethod
    def _parse_race_class(text: str) -> str:
        """RaceData02 のテキストからレース条件を抽出する。"""
        # 優先度順にチェック
        if "障害" in text:
            return "障害"
        if "新馬" in text:
            return "新馬"
        if "未勝利" in text:
            return "未勝利"
        if "1勝クラス" in text or "500万下" in text:
            return "1勝クラス"
        if "2勝クラス" in text or "1000万下" in text:
            return "2勝クラス"
        if "3勝クラス" in text or "1600万下" in text:
            return "3勝クラス"
        if "オープン" in text or "OP" in text:
            return "オープン"
        # G1/G2/G3 もオープンに含まれる
        for g in ["(G1)", "(G2)", "(G3)", "(Ｇ１)", "(Ｇ２)", "(Ｇ３)", "(L)", "(Ｌ)"]:
            if g in text:
                return "オープン"
        return ""

    def _parse_result_table(self, soup: BeautifulSoup, race_id: str) -> list[dict]:
        entries = []
        table = soup.select_one("table.race_table_01")
        if not table:
            logger.warning("Result table not found for race_id=%s", race_id)
            return entries

        header = table.select_one("tr")
        header_texts = [h.get_text(strip=True) for h in header.select("th, td")]

        def find_col(keywords: list[str]) -> int | None:
            for i, txt in enumerate(header_texts):
                for k in keywords:
                    if k in txt:
                        return i
            return None

        pop_idx = find_col(["人気", "人", "人気順"])
        weight_idx = find_col(["馬体重", "馬体", "体重"])
        finish_idx = 0
        gate_idx = 1
        horse_no_idx = 2
        name_idx = 3

        rows = table.select("tr")[1:]
        for tr in rows:
            tds = tr.select("td")
            if len(tds) < 3:
                continue

            entry: dict = {"race_id": race_id}
            entry["finish_position"] = _safe_int(tds[finish_idx].get_text(strip=True))
            entry["gate_number"] = _safe_int(tds[gate_idx].get_text(strip=True))
            entry["horse_number"] = _safe_int(tds[horse_no_idx].get_text(strip=True))

            if len(tds) > name_idx:
                horse_a = tds[name_idx].select_one("a")
                if horse_a:
                    entry["horse_name"] = horse_a.get_text(strip=True)
                    entry["horse_id"] = _extract_id(horse_a.get("href", ""), "horse")

            # age/sex
            if len(tds) > 4:
                age_text = tds[4].get_text(strip=True)
                age_m = re.match(r"(\S*?)(\d+)", age_text)
                if age_m:
                    entry["horse_sex"] = age_m.group(1) or ""
                    entry["horse_age"] = int(age_m.group(2))

            # weight carried
            if len(tds) > 5:
                entry["weight_carried"] = _safe_float(tds[5].get_text(strip=True))

            # jockey
            if len(tds) > 6:
                jockey_a = tds[6].select_one("a")
                if jockey_a:
                    entry["jockey_name"] = jockey_a.get_text(strip=True)
                    entry["jockey_id"] = _extract_id(jockey_a.get("href", ""), "jockey")

            # finish_time/margin/passing/pace/last3f
            if len(tds) > 7:
                entry["finish_time"] = _parse_time(tds[7].get_text(strip=True))
            if len(tds) > 8:
                entry["margin"] = tds[8].get_text(strip=True)
            if len(tds) > 9:
                entry["passing_positions"] = tds[9].get_text(strip=True)
            if len(tds) > 10:
                entry["pace"] = tds[10].get_text(strip=True)
            if len(tds) > 11:
                entry["last_3f_time"] = _safe_float(tds[11].get_text(strip=True))
            if len(tds) > 12:
                entry["trainer_name"] = tds[12].get_text(strip=True)

            # horse weight
            if weight_idx is not None and weight_idx < len(tds):
                weight_text = tds[weight_idx].get_text(strip=True)
                wm = re.match(r"(\d+)\(([+-]?\d+)\)", weight_text)
                if wm:
                    entry["horse_weight"] = int(wm.group(1))
                    entry["weight_change"] = int(wm.group(2))
            else:
                for cell in tds:
                    wt = cell.get_text(strip=True)
                    wm = re.match(r"^(\d+)\(([+-]?\d+)\)$", wt)
                    if wm:
                        entry["horse_weight"] = int(wm.group(1))
                        entry["weight_change"] = int(wm.group(2))
                        break

            # popularity
            if pop_idx is not None and pop_idx < len(tds):
                entry["popularity_rank"] = _safe_int(tds[pop_idx].get_text(strip=True))
            else:
                for cell in tds:
                    txt = cell.get_text(strip=True)
                    m = re.match(r"^(\d+)\s*人?$", txt)
                    if m and int(m.group(1)) <= 20:
                        entry["popularity_rank"] = int(m.group(1))
                        break

            pos = entry.get("finish_position")
            entry["is_winner"] = 1 if pos == 1 else (0 if pos is not None else None)
            entries.append(entry)

        return entries
