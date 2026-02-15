import hashlib
import logging
import random
import time
from pathlib import Path

import requests

logger = logging.getLogger(__name__)


class BaseScraper:
    """レート制限・HTMLキャッシュ付きHTTPセッション。全スクレイパーの基底クラス。"""

    HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (research-only horse-racing predictor; "
            "contact: research@example.com)"
        ),
        "Accept-Language": "ja,en;q=0.9",
        "Accept-Encoding": "gzip, deflate",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }

    def __init__(
        self,
        rate_limit: float = 3.0,
        use_cache: bool = True,
        cache_dir: str = "data/cache",
    ):
        self.session = requests.Session()
        self.session.headers.update(self.HEADERS)
        self.rate_limit = rate_limit
        self.use_cache = use_cache
        self.cache_dir = Path(cache_dir)
        self._last_request_time = 0.0

    def get(self, url: str, params: dict = None) -> str:
        cache_key = self._cache_key(url, params)
        if self.use_cache:
            cached = self._load_cache(cache_key)
            if cached:
                logger.debug("Cache hit: %s", url)
                return cached

        self._enforce_rate_limit()

        for attempt in range(1, 4):
            try:
                resp = self.session.get(url, params=params, timeout=30)
                resp.raise_for_status()
                break
            except requests.RequestException as exc:
                if attempt == 3:
                    raise
                wait = attempt * 5
                logger.warning("Request failed (%s), retry %d/3 in %ds", exc, attempt, wait)
                time.sleep(wait)

        self._last_request_time = time.monotonic()

        html = resp.content.decode(resp.apparent_encoding or "utf-8", errors="replace")

        if self.use_cache:
            self._save_cache(cache_key, html)

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
