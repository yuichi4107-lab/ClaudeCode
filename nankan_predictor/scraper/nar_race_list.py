#!/usr/bin/env python3
"""NAR スクレイパー: NARトップページおよび月別ページからレースを取得"""

import logging
import re
from datetime import datetime

from nankan_predictor.scraper.base import BaseScraper

logger = logging.getLogger(__name__)

NAR_TOP_URL = "https://nar.netkeiba.com/"
NAR_RACE_SHUTUBA_URL = "https://nar.netkeiba.com/race/shutuba.html?race_id={race_id}"
NAR_RACE_RESULT_URL = "https://nar.netkeiba.com/race/result.html?race_id={race_id}"


class NARRaceListScraper(BaseScraper):
    """NAR（地方競馬統一）のレースIDリストを取得する"""

    def get_latest_races(self) -> list[str]:
        """NARトップページから最新レース一覧を取得"""
        logger.info("Fetching latest races from NAR top page")
        html = self.get(NAR_TOP_URL)
        race_ids = self._extract_race_ids(html)
        logger.info("Found %d races from NAR top page", len(race_ids))
        return race_ids

    def _extract_race_ids(self, html: str) -> list[str]:
        """HTMLからレースIDを抽出"""
        # race_id=202655021404 のような形式を探す
        race_ids = list(set(re.findall(r'race_id=(\d{12})', html)))
        return race_ids


class NARRaceDetailsScraper(BaseScraper):
    """NAR レース詳細ページから情報を取得"""

    def scrape_race_details(self, race_id: str) -> dict:
        """レース詳細ページからレース情報を取得"""
        
        # 出走馬一覧ページからレース情報を取得
        shutuba_url = NAR_RACE_SHUTUBA_URL.format(race_id=race_id)
        logger.info("Fetching race details for %s", race_id)
        
        html = self.get(shutuba_url)
        
        # HTMLから必要な情報を抽出
        # この部分は実装が必要（HTMLの実際の構造に合わせて）
        
        return {
            "race_id": race_id,
            # 以下は後で実装
        }

    def scrape_race_result(self, race_id: str) -> dict:
        """レース結果ページからレース結果を取得"""
        
        result_url = NAR_RACE_RESULT_URL.format(race_id=race_id)
        logger.info("Fetching race result for %s", race_id)
        
        html = self.get(result_url)
        
        # HTMLから結果情報を抽出
        # この部分は実装が必要
        
        return {
            "race_id": race_id,
            # 以下は後で実装
        }


# テスト
if __name__ == "__main__":
    scraper = NARRaceListScraper(use_cache=False)
    races = scraper.get_latest_races()
    print(f"取得したレースID数: {len(races)}")
    print(f"サンプル: {races[:5]}")
