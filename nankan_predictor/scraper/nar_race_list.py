#!/usr/bin/env python3
"""NAR スクレイパー: NARトップページおよび月別ページからレースを取得"""

import logging
import re
from datetime import datetime

from bs4 import BeautifulSoup
from nankan_predictor.scraper.base import BaseScraper

logger = logging.getLogger(__name__)

NAR_TOP_URL = "https://nar.netkeiba.com/"
NAR_RACE_SHUTUBA_URL = "https://nar.netkeiba.com/race/shutuba.html?race_id={race_id}"
NAR_RACE_RESULT_URL = "https://nar.netkeiba.com/race/result.html?race_id={race_id}"

# NAR 会場コードマッピング（NAR venue_code -> DB venue_code）
NAR_VENUE_MAP = {
    "01": 45,  # 船橋
    "02": 47,  # 川崎
    "03": 46,  # 大井
    "04": 44,  # 浦和
    "55": 82,  # 佐賀
    "54": 83,  # 中津 (仮)
}


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
        """レース詳細ページからレース情報と出走馬情報を取得"""
        
        # 出走馬一覧ページからレース情報を取得
        shutuba_url = NAR_RACE_SHUTUBA_URL.format(race_id=race_id)
        logger.info("Fetching race details for %s", race_id)
        
        html = self.get(shutuba_url)
        soup = BeautifulSoup(html, 'html.parser')
        
        # ページタイトルから日付と会場を抽出
        race_date = None
        race_name = None
        race_number = None
        venue_name = None
        venue_code = None
        
        title = soup.find('title')
        if title:
            title_text = title.get_text()
            # "レース名 | YYYY年M月D日 会場NR 説明 - netkeiba"
            match = re.search(r'(\d{4})年(\d{1,2})月(\d{1,2})日\s+(\S+?)(\d+)R', title_text)
            if match:
                year, month, day, venue_name, race_num = match.groups()
                race_date = f"{year}-{int(month):02d}-{int(day):02d}"
                race_number = int(race_num)
            
            # レース名（最初の「|」まで）
            if '|' in title_text:
                race_name = title_text.split('|')[0].strip()
        
        # race_id から venue_code を推定
        venue_code = race_id[4:6]
        
        # テーブルから出走馬情報を取得
        entries = []
        tables = soup.find_all('table')
        
        if tables:
            # メインテーブル（最初のテーブル）から馬情報を抽出
            main_table = tables[0]
            rows = main_table.find_all('tr')[1:]  # ヘッダー行をスキップ
            
            for row in rows:
                cols = row.find_all('td')
                if len(cols) >= 10:
                    try:
                        # 馬リンクから horse_id を取得
                        horse_link = cols[3].find('a')
                        horse_id = None
                        if horse_link and horse_link.get('href'):
                            # href: /horse/2020102771
                            href = horse_link.get('href', '')
                            match = re.search(r'/horse/(\d+)', href)
                            if match:
                                horse_id = match.group(1)
                        
                        # 騎手リンクから jockey_id を取得
                        jockey_link = None
                        jockey_id = None
                        for td in cols:
                            jk_link = td.find('a', href=lambda x: x and '/jockey/' in x)
                            if jk_link:
                                jockey_link = jk_link
                                href = jk_link.get('href', '')
                                match = re.search(r'/jockey/(\d+)', href)
                                if match:
                                    jockey_id = match.group(1)
                                break
                        
                        entry = {
                            'race_id': race_id,
                            'horse_number': int(cols[1].get_text(strip=True)),
                            'frame': int(cols[0].get_text(strip=True)),
                            'horse_name': cols[3].get_text(strip=True),
                            'horse_id': horse_id,
                            'sex_age': cols[4].get_text(strip=True),
                            'weight': cols[5].get_text(strip=True),
                            'jockey': cols[6].get_text(strip=True),
                            'jockey_id': jockey_id,
                            'trainer': cols[7].get_text(strip=True),
                        }
                        entries.append(entry)
                    except (IndexError, AttributeError, ValueError) as e:
                        logger.warning("Failed to parse entry: %s", e)
                        continue
        
        return {
            "race_id": race_id,
            "race_date": race_date,
            "race_name": race_name,
            "race_number": race_number,
            "venue_code": venue_code,
            "venue_name": venue_name,
            "entries": entries,
        }

    def scrape_race_result(self, race_id: str) -> dict:
        """レース結果ページからレース結果と払戻を取得"""
        
        result_url = NAR_RACE_RESULT_URL.format(race_id=race_id)
        logger.info("Fetching race result for %s", race_id)
        
        html = self.get(result_url)
        soup = BeautifulSoup(html, 'html.parser')
        
        # 結果情報（着順）
        results = []
        tables = soup.find_all('table')
        
        if tables:
            # メインテーブル（最初のテーブル）から着順情報を抽出
            main_table = tables[0]
            rows = main_table.find_all('tr')[1:]  # ヘッダー行をスキップ
            
            for row in rows:
                cols = row.find_all('td')
                if len(cols) >= 8:
                    try:
                        # 時間をパースして秒に変換
                        time_str = cols[7].get_text(strip=True)
                        time_seconds = self._parse_time(time_str)
                        
                        result = {
                            'race_id': race_id,
                            'finish_order': int(cols[0].get_text(strip=True)),
                            'horse_number': int(cols[2].get_text(strip=True)),
                            'horse_name': cols[3].get_text(strip=True),
                            'time': time_seconds,
                            'time_str': time_str,
                            'win_odds': self._parse_odds(cols[10].get_text(strip=True)) if len(cols) > 10 else None,
                        }
                        results.append(result)
                    except (IndexError, AttributeError, ValueError) as e:
                        logger.warning("Failed to parse result: %s", e)
                        continue
        
        # 払戻情報（テーブル1以降から抽出）
        payouts = {}
        if len(tables) > 1:
            # テーブル1: 単勝
            try:
                payout_table = tables[1]
                payout_rows = payout_table.find_all('tr')[1:]
                for row in payout_rows:
                    cols = row.find_all('td')
                    if len(cols) >= 2:
                        try:
                            horse_numbers = cols[0].get_text(strip=True)
                            amount = cols[1].get_text(strip=True)
                            # horse_numbers は複数の場合がある（例: "683"）
                            payouts[f"win_{horse_numbers}"] = amount
                        except (IndexError, AttributeError):
                            continue
            except (IndexError, AttributeError):
                pass
        
        return {
            "race_id": race_id,
            "results": results,
            "payouts": payouts,
        }

    def _parse_time(self, time_str: str) -> float:
        """'1:23.4' -> 83.4 秒"""
        time_str = str(time_str).strip()
        match = re.match(r'(?:(\d+):)?(\d+)\.(\d+)', time_str)
        if not match:
            return None
        minutes = int(match.group(1) or 0)
        seconds = int(match.group(2))
        tenths = int(match.group(3))
        return minutes * 60 + seconds + tenths / 10

    def _parse_odds(self, odds_str: str) -> float:
        """'3.2' -> 3.2"""
        try:
            return float(odds_str.strip())
        except (ValueError, AttributeError):
            return None


# テスト
if __name__ == "__main__":
    scraper = NARRaceListScraper(use_cache=False)
    races = scraper.get_latest_races()
    print(f"取得したレースID数: {len(races)}")
    print(f"サンプル: {races[:5]}")
