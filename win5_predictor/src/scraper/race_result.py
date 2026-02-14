"""レース結果の取得"""

import logging
import re

from bs4 import BeautifulSoup

from config.settings import NETKEIBA_BASE_URL
from config.venues import (
    RACE_CLASS,
    SURFACE_TYPES,
    TRACK_CONDITIONS,
    VENUE_CODE,
)
from database.models import Race, RaceResult
from scraper.base import BaseScraper

logger = logging.getLogger(__name__)


class RaceResultScraper(BaseScraper):
    """レース結果ページをスクレイピングする"""

    def scrape(self, race_id: str) -> tuple[Race | None, list[RaceResult]]:
        """レース結果を取得する"""
        url = f"{NETKEIBA_BASE_URL}/race/{race_id}/"
        try:
            soup = self.fetch_and_parse(url)
        except Exception as e:
            logger.error("Failed to scrape race %s: %s", race_id, e)
            return None, []

        race = self._parse_race_info(soup, race_id)
        results = self._parse_results_table(soup, race_id)
        return race, results

    def _parse_race_info(self, soup: BeautifulSoup, race_id: str) -> Race | None:
        """レース情報をパースする"""
        try:
            # レース名
            race_name = ""
            name_tag = soup.select_one(".racedata h1, .RaceName")
            if name_tag:
                race_name = name_tag.get_text(strip=True)

            # 日付・競馬場・レース番号をrace_idからデコード
            # race_id形式: YYYYPPKKHHNN (年4+場2+回2+日2+R2)
            year = int(race_id[:4])
            venue_code = race_id[4:6]
            race_number = int(race_id[10:12])

            # 日付はページから取得
            race_date = None
            date_tag = soup.select_one(".racedata .smalltxt, .RaceData01")
            if date_tag:
                date_text = date_tag.get_text()
                date_match = re.search(r"(\d{4})/(\d{1,2})/(\d{1,2})", date_text)
                if date_match:
                    from datetime import date as dt_date
                    race_date = dt_date(
                        int(date_match.group(1)),
                        int(date_match.group(2)),
                        int(date_match.group(3)),
                    )

            if race_date is None:
                # race_idから推定
                from datetime import date as dt_date
                race_date = dt_date(year, 1, 1)

            # コース情報 (例: "芝右 2000m")
            surface = ""
            distance = 0
            track_condition = ""
            weather = ""

            course_tag = soup.select_one(".racedata p span, .RaceData01")
            if course_tag:
                course_text = course_tag.get_text()

                # 馬場
                for jp, en in SURFACE_TYPES.items():
                    if jp in course_text:
                        surface = en
                        break

                # 距離
                dist_match = re.search(r"(\d{3,4})m", course_text)
                if dist_match:
                    distance = int(dist_match.group(1))

                # 馬場状態
                for jp, en in TRACK_CONDITIONS.items():
                    if jp in course_text:
                        track_condition = en
                        break

                # 天候
                weather_match = re.search(r"天候:(\S+)", course_text)
                if weather_match:
                    weather = weather_match.group(1)

            # クラス
            race_class = ""
            race_class_code = 0
            for cls_name, cls_code in RACE_CLASS.items():
                if cls_name in race_name:
                    race_class = cls_name
                    race_class_code = cls_code
                    break

            # 出走頭数
            num_runners = len(soup.select("table.race_table_01 tr, .HorseList tr")) - 1
            if num_runners < 0:
                num_runners = 0

            # 賞金
            prize_1st = 0.0
            prize_tag = soup.select_one(".pay_block, .RaceData02")
            if prize_tag:
                prize_text = prize_tag.get_text()
                prize_match = re.search(r"本賞金:(.+?)万", prize_text)
                if prize_match:
                    try:
                        prizes = prize_match.group(1).split(",")
                        prize_1st = float(prizes[0].strip())
                    except (ValueError, IndexError):
                        pass

            # 年齢条件・重量規定
            age_condition = ""
            weight_rule = ""
            data2_tag = soup.select_one(".RaceData02, .racedata .smalltxt")
            if data2_tag:
                data2_text = data2_tag.get_text()
                if "歳" in data2_text:
                    age_match = re.search(r"(\d歳(?:以上)?)", data2_text)
                    if age_match:
                        age_condition = age_match.group(1)
                for rule in ("定量", "別定", "ハンデ", "馬齢"):
                    if rule in data2_text:
                        weight_rule = rule
                        break

            return Race(
                race_id=race_id,
                race_date=race_date,
                venue_code=venue_code,
                venue_name=VENUE_CODE.get(venue_code, ""),
                race_number=race_number,
                race_name=race_name,
                surface=surface,
                distance=distance,
                track_condition=track_condition,
                weather=weather,
                race_class=race_class,
                race_class_code=race_class_code,
                age_condition=age_condition,
                weight_rule=weight_rule,
                num_runners=num_runners,
                prize_1st=prize_1st,
            )
        except Exception as e:
            logger.error("Failed to parse race info for %s: %s", race_id, e)
            return None

    def _parse_results_table(
        self, soup: BeautifulSoup, race_id: str
    ) -> list[RaceResult]:
        """レース結果テーブルをパースする"""
        results = []
        table = soup.select_one("table.race_table_01, .ResultTableWrap table")
        if table is None:
            logger.warning("No results table found for %s", race_id)
            return results

        rows = table.select("tr")[1:]  # ヘッダー除外
        for row in rows:
            try:
                result = self._parse_result_row(row, race_id)
                if result:
                    results.append(result)
            except Exception as e:
                logger.debug("Failed to parse result row: %s", e)

        return results

    def _parse_result_row(
        self, row: BeautifulSoup, race_id: str
    ) -> RaceResult | None:
        """結果テーブルの1行をパースする"""
        cells = row.select("td")
        if len(cells) < 10:
            return None

        # 着順
        finish_text = cells[0].get_text(strip=True)
        finish_position = None
        if finish_text.isdigit():
            finish_position = int(finish_text)

        # 枠番・馬番
        post_position = _safe_int(cells[1].get_text(strip=True))
        horse_number = _safe_int(cells[2].get_text(strip=True))

        # 馬名・horse_id
        horse_link = cells[3].select_one("a[href*='/horse/']")
        horse_name = cells[3].get_text(strip=True)
        horse_id = ""
        if horse_link:
            href = horse_link.get("href", "")
            m = re.search(r"/horse/(\w+)", href)
            if m:
                horse_id = m.group(1)

        # 性齢
        sex_age_text = cells[4].get_text(strip=True)
        sex = sex_age_text[0] if sex_age_text else ""
        age = _safe_int(sex_age_text[1:]) if len(sex_age_text) > 1 else 0

        # 斤量
        weight_carried = _safe_float(cells[5].get_text(strip=True))

        # 騎手
        jockey_link = cells[6].select_one("a[href*='/jockey/']")
        jockey_name = cells[6].get_text(strip=True)
        jockey_id = ""
        if jockey_link:
            href = jockey_link.get("href", "")
            m = re.search(r"/jockey/(\w+)", href)
            if m:
                jockey_id = m.group(1)

        # タイム
        finish_time = _parse_time(cells[7].get_text(strip=True))

        # 着差
        margin = cells[8].get_text(strip=True) if len(cells) > 8 else ""

        # 上がり3F (後半のセル)
        last_3f = None
        if len(cells) > 11:
            last_3f = _safe_float(cells[11].get_text(strip=True))

        # 単勝オッズ
        odds = None
        if len(cells) > 12:
            odds = _safe_float(cells[12].get_text(strip=True))

        # 人気
        popularity = None
        if len(cells) > 13:
            popularity = _safe_int(cells[13].get_text(strip=True))

        # 馬体重
        horse_weight = None
        weight_change = None
        if len(cells) > 14:
            wt_text = cells[14].get_text(strip=True)
            wt_match = re.match(r"(\d+)\(([+-]?\d+)\)", wt_text)
            if wt_match:
                horse_weight = int(wt_match.group(1))
                weight_change = int(wt_match.group(2))

        # 調教師
        trainer_id = ""
        trainer_name = ""
        if len(cells) > 18:
            trainer_link = cells[18].select_one("a[href*='/trainer/']")
            trainer_name = cells[18].get_text(strip=True)
            if trainer_link:
                href = trainer_link.get("href", "")
                m = re.search(r"/trainer/(\w+)", href)
                if m:
                    trainer_id = m.group(1)

        # 通過順位
        corner_positions = ""
        if len(cells) > 10:
            corner_positions = cells[10].get_text(strip=True)

        return RaceResult(
            race_id=race_id,
            horse_id=horse_id,
            horse_name=horse_name,
            finish_position=finish_position,
            post_position=post_position,
            horse_number=horse_number,
            sex=sex,
            age=age,
            weight_carried=weight_carried,
            jockey_id=jockey_id,
            jockey_name=jockey_name,
            trainer_id=trainer_id,
            trainer_name=trainer_name,
            finish_time=finish_time,
            margin=margin,
            last_3f=last_3f,
            horse_weight=horse_weight,
            weight_change=weight_change,
            odds=odds,
            popularity=popularity,
            corner_positions=corner_positions,
        )


def _safe_int(text: str) -> int:
    try:
        return int(text)
    except (ValueError, TypeError):
        return 0


def _safe_float(text: str) -> float | None:
    try:
        return float(text)
    except (ValueError, TypeError):
        return None


def _parse_time(text: str) -> float | None:
    """タイム文字列を秒に変換 (例: "1:34.5" -> 94.5)"""
    match = re.match(r"(\d+):(\d+\.\d+)", text)
    if match:
        minutes = int(match.group(1))
        seconds = float(match.group(2))
        return minutes * 60 + seconds
    return _safe_float(text)
