"""Win5対象レースの特定"""

import logging
import re
from datetime import date

from config.settings import NETKEIBA_RACE_URL
from database.models import Win5Event
from scraper.base import BaseScraper

logger = logging.getLogger(__name__)


class Win5TargetScraper(BaseScraper):
    """Win5対象レースの情報を取得する"""

    def scrape(self, target_date: date) -> Win5Event | None:
        """指定日のWin5対象レース・配当情報を取得する"""
        date_str = target_date.strftime("%Y%m%d")
        url = f"{NETKEIBA_RACE_URL}/top/win5.html?kaisai_date={date_str}"

        try:
            soup = self.fetch_and_parse(url, encoding="euc-jp")
        except Exception as e:
            logger.error("Failed to scrape Win5 for %s: %s", target_date, e)
            return None

        race_ids = []

        # Win5対象レースのリンクを抽出
        for link in soup.select("a[href*='/race/']"):
            href = link.get("href", "")
            m = re.search(r"/race/(\d{12})", href)
            if m:
                rid = m.group(1)
                if rid not in race_ids:
                    race_ids.append(rid)

        if len(race_ids) < 5:
            # 代替: 日曜後半5レースをWin5対象と推定
            logger.warning(
                "Found only %d Win5 races on %s, expected 5",
                len(race_ids),
                target_date,
            )
            if not race_ids:
                return None

        # 最大5つまで
        race_ids = race_ids[:5]

        # 配当情報
        payout = None
        carryover = None
        num_winners = None
        total_sales = None

        result_div = soup.select_one(".Win5_Result, .pay_block")
        if result_div:
            text = result_div.get_text()

            pay_match = re.search(r"払戻金.*?([\d,]+)円", text)
            if pay_match:
                payout = float(pay_match.group(1).replace(",", ""))

            carry_match = re.search(r"キャリーオーバー.*?([\d,]+)円", text)
            if carry_match:
                carryover = float(carry_match.group(1).replace(",", ""))

            winners_match = re.search(r"的中.*?(\d+)票", text)
            if winners_match:
                num_winners = int(winners_match.group(1))

            sales_match = re.search(r"発売.*?([\d,]+)円", text)
            if sales_match:
                total_sales = float(sales_match.group(1).replace(",", ""))

        event = Win5Event(
            event_id=date_str,
            event_date=target_date,
            race1_id=race_ids[0] if len(race_ids) > 0 else "",
            race2_id=race_ids[1] if len(race_ids) > 1 else "",
            race3_id=race_ids[2] if len(race_ids) > 2 else "",
            race4_id=race_ids[3] if len(race_ids) > 3 else "",
            race5_id=race_ids[4] if len(race_ids) > 4 else "",
            payout=payout,
            carryover=carryover,
            num_winners=num_winners,
            total_sales=total_sales,
        )

        logger.info(
            "Win5 on %s: races=%s, payout=%s",
            target_date,
            race_ids,
            payout,
        )
        return event

    def get_win5_race_ids(self, target_date: date) -> list[str]:
        """Win5対象レースIDだけを返す"""
        event = self.scrape(target_date)
        if event is None:
            return []
        return [
            rid
            for rid in [
                event.race1_id,
                event.race2_id,
                event.race3_id,
                event.race4_id,
                event.race5_id,
            ]
            if rid
        ]
