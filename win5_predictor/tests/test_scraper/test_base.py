"""BaseScraper のユニットテスト"""

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
import sys

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from scraper.base import BaseScraper


class TestBaseScraper:
    """BaseScraper クラスのテスト"""

    def test_init(self):
        """初期化テスト"""
        scraper = BaseScraper(use_cache=True)
        assert scraper.use_cache is True
        assert scraper._last_request_time == 0.0

    def test_cache_path_generation(self):
        """キャッシュパス生成テスト"""
        scraper = BaseScraper(use_cache=True)
        url = "https://example.com/test"
        cache_path = scraper._cache_path(url)
        assert cache_path.parent.name == "cache"
        assert cache_path.suffix == ".html"

    def test_cache_save_and_load(self, tmp_path, monkeypatch):
        """キャッシュの保存と読み込みテスト"""
        # キャッシュディレクトリを一時ディレクトリに変更
        import config.settings
        monkeypatch.setattr(config.settings, "CACHE_DIR", tmp_path)

        scraper = BaseScraper(use_cache=True)
        url = "https://example.com/test"
        html_content = "<html><body>Test</body></html>"

        # キャッシュに保存
        scraper._save_cache(url, html_content)

        # キャッシュから読み込み
        loaded = scraper._load_cache(url)
        assert loaded == html_content

    def test_no_cache_when_disabled(self, tmp_path, monkeypatch):
        """キャッシュを無効化した場合"""
        import config.settings
        monkeypatch.setattr(config.settings, "CACHE_DIR", tmp_path)

        scraper = BaseScraper(use_cache=False)
        url = "https://example.com/test"
        html_content = "<html><body>Test</body></html>"

        # キャッシュに保存を試みる（実際には保存されない）
        scraper._save_cache(url, html_content)

        # キャッシュから読み込みを試みる（Noneが返される）
        loaded = scraper._load_cache(url)
        assert loaded is None

    def test_parse_html(self):
        """HTMLパースのテスト"""
        scraper = BaseScraper()
        html = "<html><body><h1>Test Title</h1></body></html>"
        soup = scraper.parse(html)
        assert soup.h1.string == "Test Title"

    @patch("scraper.base.requests.Session.get")
    def test_fetch_success(self, mock_get):
        """正常なfetchのテスト"""
        mock_response = MagicMock()
        mock_response.text = "<html><body>Test</body></html>"
        mock_response.encoding = "utf-8"
        mock_get.return_value = mock_response

        scraper = BaseScraper(use_cache=False)
        result = scraper.fetch("https://example.com/test")
        assert result == "<html><body>Test</body></html>"

    @patch("scraper.base.requests.Session.get")
    def test_fetch_with_retry(self, mock_get):
        """リトライ機能のテスト"""
        import requests

        # 最初の2回は失敗、3回目は成功
        mock_response = MagicMock()
        mock_response.text = "<html><body>Success</body></html>"
        mock_response.encoding = "utf-8"

        mock_get.side_effect = [
            requests.Timeout("Timeout 1"),
            requests.Timeout("Timeout 2"),
            mock_response,
        ]

        scraper = BaseScraper(use_cache=False)
        result = scraper.fetch("https://example.com/test")
        assert result == "<html><body>Success</body></html>"
        assert mock_get.call_count == 3

    @patch("scraper.base.requests.Session.get")
    def test_fetch_max_retries_exceeded(self, mock_get):
        """最大リトライ回数超過のテスト"""
        import requests

        mock_get.side_effect = requests.Timeout("Timeout")

        scraper = BaseScraper(use_cache=False)
        with pytest.raises(requests.Timeout):
            scraper.fetch("https://example.com/test")

    def test_rate_limiting(self):
        """レート制限のテスト"""
        import time
        from config.settings import REQUEST_INTERVAL_SEC

        scraper = BaseScraper()
        start = time.time()
        scraper._rate_limit()
        scraper._rate_limit()
        elapsed = time.time() - start
        # 最低でも REQUEST_INTERVAL_SEC の待機があるはず
        assert elapsed >= REQUEST_INTERVAL_SEC * 0.9  # 多少の許容誤差

    def test_fetch_and_parse(self, sample_race_html):
        """fetch_and_parse メソッドのテスト"""
        with patch("scraper.base.BaseScraper.fetch") as mock_fetch:
            mock_fetch.return_value = sample_race_html
            scraper = BaseScraper()
            soup = scraper.fetch_and_parse("https://example.com/race/123456/")
            assert soup.h1 is not None
            assert "バレンタイン" in soup.h1.get_text()
