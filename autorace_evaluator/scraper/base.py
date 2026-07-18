import hashlib
import logging
import random
import time
from pathlib import Path

import requests

from autorace_evaluator.config import settings

logger = logging.getLogger(__name__)


class BaseScraper:
    """レート制限・HTMLキャッシュ付きHTTPセッション。全スクレイパーの基底クラス。"""

    HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (research-only autorace player evaluation; "
            "contact: research@example.com)"
        ),
        "Accept-Language": "ja,en;q=0.9",
        "Accept-Encoding": "gzip, deflate",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }

    def __init__(
        self,
        rate_limit: float = settings.RATE_LIMIT_SECONDS,
        use_cache: bool = settings.USE_CACHE,
        cache_dir: str = settings.CACHE_DIR,
        dump_dir: str | None = None,
    ):
        self.session = requests.Session()
        self.session.headers.update(self.HEADERS)
        self.rate_limit = rate_limit
        self.use_cache = use_cache
        self.cache_dir = Path(cache_dir)
        self.dump_dir = Path(dump_dir) if dump_dir else None
        self._last_request_time = 0.0

    def get(
        self,
        url: str,
        params: dict = None,
        dump_name: str | None = None,
    ) -> str | None:
        """URLを取得する。

        404 の場合は例外を投げず None を返す(呼び出し側で scrape_log への
        記録を行うこと)。404以外の HTTPError・接続エラーは3回までリトライ
        (attempt*5秒待機)し、それでも失敗すれば例外を送出する。
        """
        cache_key = self._cache_key(url, params)
        if self.use_cache:
            cached = self._load_cache(cache_key)
            if cached:
                logger.debug("Cache hit: %s", url)
                self._save_dump(cached, dump_name)
                return cached

        self._enforce_rate_limit()

        resp = None
        for attempt in range(1, settings.MAX_RETRIES + 1):
            try:
                resp = self.session.get(
                    url, params=params, timeout=settings.REQUEST_TIMEOUT
                )
                if resp.status_code == 404:
                    self._last_request_time = time.monotonic()
                    logger.debug("404 Not Found: %s", url)
                    return None
                resp.raise_for_status()
                break
            except requests.RequestException as exc:
                if attempt == settings.MAX_RETRIES:
                    raise
                wait = attempt * 5
                logger.warning(
                    "Request failed (%s), retry %d/%d in %ds",
                    exc, attempt, settings.MAX_RETRIES, wait,
                )
                time.sleep(wait)

        self._last_request_time = time.monotonic()

        html = resp.content.decode(resp.apparent_encoding or "utf-8", errors="replace")

        if self.use_cache:
            self._save_cache(cache_key, html)
        self._save_dump(html, dump_name)

        return html

    def _enforce_rate_limit(self) -> None:
        elapsed = time.monotonic() - self._last_request_time
        jitter = random.uniform(0, self.rate_limit * 0.5)
        wait = self.rate_limit + jitter - elapsed
        if wait > 0:
            time.sleep(wait)

    def _cache_key(self, url: str, params: dict) -> str:
        full = url + str(sorted(params.items()) if params else "")
        return hashlib.md5(full.encode()).hexdigest()

    def _load_cache(self, key: str):
        path = self.cache_dir / f"{key}.html"
        if path.exists():
            return path.read_text(encoding="utf-8")
        return None

    def _save_cache(self, key: str, html: str) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        path = self.cache_dir / f"{key}.html"
        path.write_text(html, encoding="utf-8")

    def _save_dump(self, html: str, dump_name: str | None) -> None:
        """可読名デバッグ用に取得成功HTMLを保存する(dump_dir・dump_name両方指定時のみ)。"""
        if not (self.dump_dir and dump_name):
            return
        self.dump_dir.mkdir(parents=True, exist_ok=True)
        path = self.dump_dir / f"{dump_name}.html"
        path.write_text(html, encoding="utf-8")
