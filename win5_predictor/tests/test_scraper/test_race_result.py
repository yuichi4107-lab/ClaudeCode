"""RaceResultScraper のユニットテスト"""

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from datetime import date
import sys

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from scraper.race_result import RaceResultScraper
from database.models import Race, RaceResult


class TestRaceResultScraper:
    """RaceResultScraper クラスのテスト"""

    def test_init(self):
        """初期化テスト"""
        scraper = RaceResultScraper(use_cache=False)
        assert scraper.use_cache is False

    def test_parse_race_result(self, sample_race_html):
        """レース結果HTMLのパーステスト"""
        scraper = RaceResultScraper(use_cache=False)
        soup = scraper.parse(sample_race_html)

        # HTMLが正しくパースできていることを確認
        assert soup.h1 is not None
        race_name = soup.h1.get_text(strip=True)
        assert "バレンタイン" in race_name

    @patch("scraper.race_result.RaceResultScraper.fetch_and_parse")
    def test_scrape_race_success(self, mock_fetch_parse, sample_race_html):
        """レース結果スクレイピングの成功テスト"""
        soup = BeautifulSoup(sample_race_html, "lxml")
        mock_fetch_parse.return_value = soup

        scraper = RaceResultScraper(use_cache=False)
        race_id = "202602150811"  # 形式: YYYYPPKKHHNN
        race, results = scraper.scrape(race_id)

        # Race オブジェクトが返されていることを確認
        assert race is not None
        assert race.race_id == race_id
        assert race.race_date == date(2026, 2, 15)

        # RaceResult オブジェクトが返されていることを確認
        assert len(results) > 0
        assert isinstance(results[0], RaceResult)
        assert results[0].race_id == race_id

    @patch("scraper.race_result.RaceResultScraper.fetch_and_parse")
    def test_scrape_race_failure(self, mock_fetch_parse):
        """レース結果スクレイピングの失敗テスト"""
        mock_fetch_parse.side_effect = Exception("Network error")

        scraper = RaceResultScraper(use_cache=False)
        race_id = "202602150811"
        race, results = scraper.scrape(race_id)

        # 失敗時は None と空リストが返される
        assert race is None
        assert results == []

    def test_parse_race_info(self, sample_race_html):
        """_parse_race_info メソッドのテスト"""
        scraper = RaceResultScraper(use_cache=False)
        soup = scraper.parse(sample_race_html)
        race_id = "202602150811"

        race = scraper._parse_race_info(soup, race_id)

        assert race is not None
        assert race.race_id == race_id
        assert race.race_date == date(2026, 2, 15)
        assert race.venue_code == "08"  # race_idから抽出
        assert race.race_number == 11  # race_idから抽出
        assert race.surface == "turf"  # 芝 -> turf
        assert race.distance == 2000
        assert race.race_name == "バレンタインステークス"

    def test_parse_results_table(self, sample_race_html):
        """_parse_results_table メソッドのテスト"""
        scraper = RaceResultScraper(use_cache=False)
        soup = scraper.parse(sample_race_html)
        race_id = "202602150811"

        results = scraper._parse_results_table(soup, race_id)

        assert len(results) >= 1
        assert all(isinstance(r, RaceResult) for r in results)

        # 最初の結果を確認
        first = results[0]
        assert first.race_id == race_id
        assert first.finish_position == 1
        assert first.horse_name == "ナスカ"
        assert first.jockey_name == "武豊"

    def test_decode_race_id(self):
        """Race ID のデコードテスト"""
        # race_id形式: YYYYPPKKHHNN (年4+場2+回2+日2+R2)
        race_id = "202602150811"
        year = int(race_id[:4])
        venue_code = race_id[4:6]
        race_number = int(race_id[10:12])

        assert year == 2026
        assert venue_code == "08"
        assert race_number == 11


# BeautifulSoup をインポート
try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None
