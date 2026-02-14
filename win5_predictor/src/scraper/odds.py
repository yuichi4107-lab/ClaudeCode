"""オッズ情報の取得"""

import logging
import re
from datetime import datetime

from config.settings import NETKEIBA_RACE_URL
from scraper.base import BaseScraper

logger = logging.getLogger(__name__)


class OddsScraper(BaseScraper):
    """単勝・複勝オッズをスクレイピングする"""

    def scrape_win_odds(self, race_id: str) -> list[dict]:
        """単勝オッズを取得する"""
        url = f"{NETKEIBA_RACE_URL}/odds/index.html?race_id={race_id}&type=b1"
        try:
            soup = self.fetch_and_parse(url, encoding="euc-jp")
        except Exception as e:
            logger.error("Failed to scrape odds for %s: %s", race_id, e)
            return []

        odds_list = []
        table = soup.select_one("table.RaceOdds_HorseList_Table, table#odds_tan_block")
        if table is None:
            logger.warning("No odds table found for %s", race_id)
            return odds_list

        for row in table.select("tr"):
            cells = row.select("td")
            if len(cells) < 3:
                continue

            try:
                horse_number = int(cells[1].get_text(strip=True))
                odds_text = cells[2].get_text(strip=True)
                odds_val = float(odds_text) if odds_text and odds_text != "---" else None

                if odds_val is not None:
                    odds_list.append(
                        {
                            "horse_number": horse_number,
                            "win_odds": odds_val,
                            "timestamp": datetime.now().isoformat(),
                        }
                    )
            except (ValueError, IndexError):
                continue

        logger.info("Fetched %d odds for race %s", len(odds_list), race_id)
        return odds_list

    def scrape_place_odds(self, race_id: str) -> list[dict]:
        """複勝オッズを取得する"""
        url = f"{NETKEIBA_RACE_URL}/odds/index.html?race_id={race_id}&type=b1"
        try:
            soup = self.fetch_and_parse(url, encoding="euc-jp")
        except Exception as e:
            logger.error("Failed to scrape place odds for %s: %s", race_id, e)
            return []

        odds_list = []
        table = soup.select_one(
            "table.RaceOdds_HorseList_Table, table#odds_fuku_block"
        )
        if table is None:
            return odds_list

        for row in table.select("tr"):
            cells = row.select("td")
            if len(cells) < 5:
                continue

            try:
                horse_number = int(cells[1].get_text(strip=True))
                min_text = cells[3].get_text(strip=True)
                max_text = cells[4].get_text(strip=True)

                min_odds = (
                    float(min_text) if min_text and min_text != "---" else None
                )
                max_odds = (
                    float(max_text) if max_text and max_text != "---" else None
                )

                odds_list.append(
                    {
                        "horse_number": horse_number,
                        "place_odds_min": min_odds,
                        "place_odds_max": max_odds,
                        "timestamp": datetime.now().isoformat(),
                    }
                )
            except (ValueError, IndexError):
                continue

        return odds_list

    def get_all_odds(self, race_id: str) -> list[dict]:
        """単勝・複勝オッズを統合して取得する"""
        win_odds = {o["horse_number"]: o for o in self.scrape_win_odds(race_id)}
        place_odds = self.scrape_place_odds(race_id)

        for po in place_odds:
            hn = po["horse_number"]
            if hn in win_odds:
                win_odds[hn]["place_odds_min"] = po.get("place_odds_min")
                win_odds[hn]["place_odds_max"] = po.get("place_odds_max")

        return list(win_odds.values())
