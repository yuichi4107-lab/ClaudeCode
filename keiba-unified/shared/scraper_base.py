"""スクレイパー基底クラス 共通モジュール"""

import logging
import time
import requests
from bs4 import BeautifulSoup

from config.settings import REQUEST_INTERVAL, REQUEST_TIMEOUT, MAX_RETRIES, USER_AGENT

logger = logging.getLogger(__name__)


class ScraperBase:
    """スクレイパー共通基底クラス"""

    def __init__(self, interval: float = None):
        self.interval = interval or REQUEST_INTERVAL
        self._last_request_time = 0
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})

    def _rate_limit(self):
        elapsed = time.time() - self._last_request_time
        if elapsed < self.interval:
            time.sleep(self.interval - elapsed)
        self._last_request_time = time.time()

    def fetch(self, url: str) -> str | None:
        """HTTP GETでHTMLを取得"""
        for attempt in range(MAX_RETRIES):
            self._rate_limit()
            try:
                resp = self.session.get(url, timeout=REQUEST_TIMEOUT)
                resp.raise_for_status()
                resp.encoding = resp.apparent_encoding
                return resp.text
            except requests.RequestException as e:
                logger.warning("リクエスト失敗 (試行%d/%d): %s - %s",
                               attempt + 1, MAX_RETRIES, url, e)
                if attempt < MAX_RETRIES - 1:
                    time.sleep(2 ** attempt)
        logger.error("リクエスト最終失敗: %s", url)
        return None

    def fetch_soup(self, url: str) -> BeautifulSoup | None:
        """HTMLを取得してBeautifulSoupで解析"""
        html = self.fetch(url)
        if html is None:
            return None
        return BeautifulSoup(html, "lxml")
