"""スクレイパー基底クラス - レート制限・キャッシュ・リトライ"""

import hashlib
import logging
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from config.settings import (
    CACHE_DIR,
    MAX_RETRIES,
    REQUEST_INTERVAL_SEC,
    REQUEST_TIMEOUT_SEC,
    USER_AGENT,
)

logger = logging.getLogger(__name__)


class BaseScraper:
    """Webスクレイピングの基底クラス"""

    def __init__(self, use_cache: bool = True):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})
        self.use_cache = use_cache
        self._last_request_time = 0.0

    def _rate_limit(self):
        """リクエスト間隔を制御する"""
        elapsed = time.time() - self._last_request_time
        if elapsed < REQUEST_INTERVAL_SEC:
            sleep_time = REQUEST_INTERVAL_SEC - elapsed
            time.sleep(sleep_time)
        self._last_request_time = time.time()

    def _cache_path(self, url: str) -> Path:
        """URLからキャッシュファイルパスを生成"""
        url_hash = hashlib.md5(url.encode()).hexdigest()
        return CACHE_DIR / f"{url_hash}.html"

    def _load_cache(self, url: str) -> str | None:
        """キャッシュからHTMLを読み込み"""
        if not self.use_cache:
            return None
        path = self._cache_path(url)
        if path.exists():
            return path.read_text(encoding="utf-8")
        return None

    def _save_cache(self, url: str, html: str):
        """HTMLをキャッシュに保存"""
        if not self.use_cache:
            return
        path = self._cache_path(url)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(html, encoding="utf-8")

    def fetch(self, url: str, encoding: str = "euc-jp") -> str:
        """URLからHTMLを取得する(キャッシュ・レート制限・リトライ付き)"""
        cached = self._load_cache(url)
        if cached is not None:
            logger.debug("Cache hit: %s", url)
            return cached

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                self._rate_limit()
                resp = self.session.get(url, timeout=REQUEST_TIMEOUT_SEC)
                resp.encoding = encoding
                resp.raise_for_status()
                html = resp.text
                self._save_cache(url, html)
                logger.debug("Fetched: %s", url)
                return html
            except requests.RequestException as e:
                logger.warning(
                    "Request failed (attempt %d/%d): %s - %s",
                    attempt,
                    MAX_RETRIES,
                    url,
                    e,
                )
                if attempt == MAX_RETRIES:
                    raise
                time.sleep(2 ** attempt)

        raise RuntimeError(f"Failed to fetch: {url}")

    def parse(self, html: str) -> BeautifulSoup:
        """HTMLをBeautifulSoupでパースする"""
        return BeautifulSoup(html, "lxml")

    def fetch_and_parse(self, url: str, encoding: str = "euc-jp") -> BeautifulSoup:
        """HTMLの取得とパースを一括で行う"""
        html = self.fetch(url, encoding=encoding)
        return self.parse(html)

    def clear_cache(self):
        """キャッシュを全削除"""
        if CACHE_DIR.exists():
            for f in CACHE_DIR.glob("*.html"):
                f.unlink()
            logger.info("Cache cleared.")
