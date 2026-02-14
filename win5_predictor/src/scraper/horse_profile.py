"""馬情報(血統・プロフィール)の取得"""

import logging
import re

from config.settings import NETKEIBA_BASE_URL
from database.models import Horse
from scraper.base import BaseScraper

logger = logging.getLogger(__name__)


class HorseProfileScraper(BaseScraper):
    """馬の詳細情報(血統含む)をスクレイピングする"""

    def scrape(self, horse_id: str) -> Horse | None:
        """馬のプロフィールを取得する"""
        url = f"{NETKEIBA_BASE_URL}/horse/{horse_id}/"
        try:
            soup = self.fetch_and_parse(url)
        except Exception as e:
            logger.error("Failed to scrape horse %s: %s", horse_id, e)
            return None

        try:
            # 馬名
            name_tag = soup.select_one(".horse_title h1, .Name_Wrap h1")
            horse_name = name_tag.get_text(strip=True) if name_tag else ""

            # プロフィールテーブル
            profile = {}
            for row in soup.select("table.db_prof_table tr, .db_prof_table tr"):
                th = row.select_one("th")
                td = row.select_one("td")
                if th and td:
                    key = th.get_text(strip=True)
                    val = td.get_text(strip=True)
                    profile[key] = val

                    # リンクからIDを抽出
                    link = td.select_one("a")
                    if link:
                        href = link.get("href", "")
                        m = re.search(r"/horse/(\w+)", href)
                        if m:
                            profile[key + "_id"] = m.group(1)

            # 性別
            sex = ""
            sex_text = profile.get("性齢", profile.get("性別", ""))
            if sex_text:
                sex = sex_text[0]

            # 生年
            birth_year = 0
            birth_text = profile.get("生年月日", "")
            birth_match = re.search(r"(\d{4})年", birth_text)
            if birth_match:
                birth_year = int(birth_match.group(1))

            # 毛色
            coat_color = profile.get("毛色", "")

            # 血統 - 父・母・母父
            sire_name = ""
            sire_id = ""
            dam_name = ""
            dam_id = ""
            damsire_name = ""
            damsire_id = ""

            pedigree_table = soup.select_one("table.blood_table, .Pedigree_Table")
            if pedigree_table:
                pedigree_links = pedigree_table.select("a[href*='/horse/']")
                if len(pedigree_links) >= 1:
                    sire_name = pedigree_links[0].get_text(strip=True)
                    m = re.search(r"/horse/(\w+)", pedigree_links[0].get("href", ""))
                    if m:
                        sire_id = m.group(1)
                if len(pedigree_links) >= 3:
                    dam_name = pedigree_links[2].get_text(strip=True)
                    m = re.search(r"/horse/(\w+)", pedigree_links[2].get("href", ""))
                    if m:
                        dam_id = m.group(1)
                if len(pedigree_links) >= 4:
                    damsire_name = pedigree_links[3].get_text(strip=True)
                    m = re.search(r"/horse/(\w+)", pedigree_links[3].get("href", ""))
                    if m:
                        damsire_id = m.group(1)

            # オーナー・生産者
            owner = profile.get("馬主", "")
            breeder = profile.get("生産者", "")

            # 通算成績
            total_wins = 0
            total_runs = 0
            total_earnings = 0.0
            record_text = profile.get("通算成績", "")
            record_match = re.search(r"(\d+)戦(\d+)勝", record_text)
            if record_match:
                total_runs = int(record_match.group(1))
                total_wins = int(record_match.group(2))

            earnings_text = profile.get("獲得賞金", profile.get("総賞金", ""))
            if earnings_text:
                e_match = re.search(r"([\d,]+)万", earnings_text)
                if e_match:
                    total_earnings = float(e_match.group(1).replace(",", ""))

            return Horse(
                horse_id=horse_id,
                horse_name=horse_name,
                sex=sex,
                birth_year=birth_year,
                coat_color=coat_color,
                sire_id=sire_id,
                sire_name=sire_name,
                dam_id=dam_id,
                dam_name=dam_name,
                damsire_id=damsire_id,
                damsire_name=damsire_name,
                owner=owner,
                breeder=breeder,
                total_wins=total_wins,
                total_runs=total_runs,
                total_earnings=total_earnings,
            )

        except Exception as e:
            logger.error("Failed to parse horse profile %s: %s", horse_id, e)
            return None
