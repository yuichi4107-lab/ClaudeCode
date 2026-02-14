"""騎手・調教師情報の取得"""

import logging
import re

from config.settings import NETKEIBA_BASE_URL
from database.models import Jockey, Trainer
from scraper.base import BaseScraper

logger = logging.getLogger(__name__)


class JockeyTrainerScraper(BaseScraper):
    """騎手・調教師のプロフィールをスクレイピングする"""

    def scrape_jockey(self, jockey_id: str) -> Jockey | None:
        url = f"{NETKEIBA_BASE_URL}/jockey/{jockey_id}/"
        try:
            soup = self.fetch_and_parse(url)
        except Exception as e:
            logger.error("Failed to scrape jockey %s: %s", jockey_id, e)
            return None

        try:
            name_tag = soup.select_one(".Name_Wrap h1, h1")
            jockey_name = name_tag.get_text(strip=True) if name_tag else ""

            profile = {}
            for row in soup.select("table.db_prof_table tr"):
                th = row.select_one("th")
                td = row.select_one("td")
                if th and td:
                    profile[th.get_text(strip=True)] = td.get_text(strip=True)

            birth_year = 0
            birth_text = profile.get("生年月日", "")
            birth_match = re.search(r"(\d{4})年", birth_text)
            if birth_match:
                birth_year = int(birth_match.group(1))

            affiliation = profile.get("所属", "")

            # 通算成績テーブル
            total_wins = 0
            total_runs = 0
            win_rate = 0.0

            stats_table = soup.select_one("table.nk_tb_common")
            if stats_table:
                rows = stats_table.select("tr")
                for row in rows:
                    tds = row.select("td")
                    if len(tds) >= 4:
                        try:
                            total_runs = int(
                                tds[0].get_text(strip=True).replace(",", "")
                            )
                            total_wins = int(
                                tds[1].get_text(strip=True).replace(",", "")
                            )
                            break
                        except ValueError:
                            continue

            if total_runs > 0:
                win_rate = total_wins / total_runs

            return Jockey(
                jockey_id=jockey_id,
                jockey_name=jockey_name,
                birth_year=birth_year,
                affiliation=affiliation,
                total_wins=total_wins,
                total_runs=total_runs,
                win_rate=win_rate,
            )
        except Exception as e:
            logger.error("Failed to parse jockey %s: %s", jockey_id, e)
            return None

    def scrape_trainer(self, trainer_id: str) -> Trainer | None:
        url = f"{NETKEIBA_BASE_URL}/trainer/{trainer_id}/"
        try:
            soup = self.fetch_and_parse(url)
        except Exception as e:
            logger.error("Failed to scrape trainer %s: %s", trainer_id, e)
            return None

        try:
            name_tag = soup.select_one(".Name_Wrap h1, h1")
            trainer_name = name_tag.get_text(strip=True) if name_tag else ""

            profile = {}
            for row in soup.select("table.db_prof_table tr"):
                th = row.select_one("th")
                td = row.select_one("td")
                if th and td:
                    profile[th.get_text(strip=True)] = td.get_text(strip=True)

            affiliation = profile.get("所属", "")

            total_wins = 0
            total_runs = 0
            win_rate = 0.0

            stats_table = soup.select_one("table.nk_tb_common")
            if stats_table:
                rows = stats_table.select("tr")
                for row in rows:
                    tds = row.select("td")
                    if len(tds) >= 4:
                        try:
                            total_runs = int(
                                tds[0].get_text(strip=True).replace(",", "")
                            )
                            total_wins = int(
                                tds[1].get_text(strip=True).replace(",", "")
                            )
                            break
                        except ValueError:
                            continue

            if total_runs > 0:
                win_rate = total_wins / total_runs

            return Trainer(
                trainer_id=trainer_id,
                trainer_name=trainer_name,
                affiliation=affiliation,
                total_wins=total_wins,
                total_runs=total_runs,
                win_rate=win_rate,
            )
        except Exception as e:
            logger.error("Failed to parse trainer %s: %s", trainer_id, e)
            return None
