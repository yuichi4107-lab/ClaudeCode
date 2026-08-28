import hashlib
import json
import logging
import random
import re
import time
from pathlib import Path

import requests

from autorace_evaluator.config import settings
from autorace_evaluator.parsers import selectors

logger = logging.getLogger(__name__)

_CSRF_RE = re.compile(selectors.CSRF_TOKEN_PATTERN)


class BaseScraper:
    """レート制限・応答キャッシュ付きHTTPセッション。全スクレイパーの基底クラス。

    autorace.jp の JSON API は Laravel の CSRF 保護下にあるため、POST 時は
    HTMLシェルを一度取得して csrf-token メタタグとセッションクッキーを
    確保してから X-CSRF-TOKEN ヘッダ付きで送信する(419 応答時は再取得)。
    """

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
        self._csrf_token: str | None = None

    # ------------------------------------------------------------------ GET

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
            cached = self._load_cache(cache_key, "html")
            if cached:
                logger.debug("Cache hit: %s", url)
                self._save_dump(cached, dump_name, "html")
                return cached

        resp = self._request_with_retry("GET", url, params=params)
        if resp is None:
            return None

        html = resp.content.decode(resp.apparent_encoding or "utf-8", errors="replace")

        if self.use_cache:
            self._save_cache(cache_key, html, "html")
        self._save_dump(html, dump_name, "html")

        return html

    def get_json(
        self,
        url: str,
        params: dict = None,
        dump_name: str | None = None,
    ) -> dict | None:
        """JSON応答のGET(カレンダーAPI用)。404 は None。"""
        cache_key = self._cache_key(url, params)
        if self.use_cache:
            cached = self._load_cache(cache_key, "json")
            if cached:
                logger.debug("Cache hit: %s", url)
                return json.loads(cached)

        resp = self._request_with_retry("GET", url, params=params)
        if resp is None:
            return None

        data = resp.json()
        if self.use_cache:
            self._save_cache(
                cache_key, json.dumps(data, ensure_ascii=False), "json")
        return data

    # ----------------------------------------------------------------- POST

    def post_json(
        self,
        url: str,
        payload: dict,
        dump_name: str | None = None,
    ) -> dict | None:
        """CSRFトークン付きで JSON を POST し、JSON応答を返す。404 は None。

        419 (トークン不一致) は一度だけトークンを再取得してリトライする。
        """
        cache_key = self._cache_key(url, payload)
        if self.use_cache:
            cached = self._load_cache(cache_key, "json")
            if cached:
                logger.debug("Cache hit: %s %s", url, payload)
                self._save_dump(cached, dump_name, "json")
                return json.loads(cached)

        headers = {
            "X-CSRF-TOKEN": self._ensure_csrf_token(),
            "X-Requested-With": "XMLHttpRequest",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        resp = self._request_with_retry("POST", url, json_body=payload, headers=headers)
        if resp is None:
            return None
        if resp.status_code == 419:
            logger.info("CSRF token expired, refreshing")
            self._csrf_token = None
            headers["X-CSRF-TOKEN"] = self._ensure_csrf_token()
            resp = self._request_with_retry("POST", url, json_body=payload, headers=headers)
            if resp is None:
                return None

        data = resp.json()
        text = json.dumps(data, ensure_ascii=False)
        if self.use_cache:
            self._save_cache(cache_key, text, "json")
        self._save_dump(text, dump_name, "json")
        return data

    def _ensure_csrf_token(self) -> str:
        """CSRFトークンを(必要ならHTMLシェルを取得して)返す。"""
        if self._csrf_token:
            return self._csrf_token
        html = self.get_token_page()
        m = _CSRF_RE.search(html or "")
        if not m:
            raise RuntimeError("CSRFトークンをHTMLから抽出できません")
        self._csrf_token = m.group(1)
        return self._csrf_token

    def get_token_page(self) -> str | None:
        """CSRFトークン取得用ページのHTML。キャッシュ不使用(トークンは揮発)。"""
        self._enforce_rate_limit()
        resp = self.session.get(
            settings.BASE_URLS["race_info_top"], timeout=settings.REQUEST_TIMEOUT
        )
        self._last_request_time = time.monotonic()
        resp.raise_for_status()
        return resp.text

    # ------------------------------------------------------------- internal

    def _request_with_retry(
        self,
        method: str,
        url: str,
        params: dict = None,
        json_body: dict = None,
        headers: dict = None,
    ):
        """レート制限+リトライ付きリクエスト。404 は None、419 はそのまま返す。"""
        self._enforce_rate_limit()

        resp = None
        for attempt in range(1, settings.MAX_RETRIES + 1):
            try:
                resp = self.session.request(
                    method, url, params=params, json=json_body, headers=headers,
                    timeout=settings.REQUEST_TIMEOUT,
                )
                if resp.status_code == 404:
                    self._last_request_time = time.monotonic()
                    logger.debug("404 Not Found: %s", url)
                    return None
                if resp.status_code == 419:
                    self._last_request_time = time.monotonic()
                    return resp
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
        return resp

    def _enforce_rate_limit(self) -> None:
        elapsed = time.monotonic() - self._last_request_time
        jitter = random.uniform(0, self.rate_limit * 0.5)
        wait = self.rate_limit + jitter - elapsed
        if wait > 0:
            time.sleep(wait)

    def _cache_key(self, url: str, params: dict) -> str:
        full = url + str(sorted(params.items()) if params else "")
        return hashlib.md5(full.encode()).hexdigest()

    def _load_cache(self, key: str, ext: str):
        path = self.cache_dir / f"{key}.{ext}"
        if path.exists():
            return path.read_text(encoding="utf-8")
        return None

    def _save_cache(self, key: str, text: str, ext: str) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        path = self.cache_dir / f"{key}.{ext}"
        path.write_text(text, encoding="utf-8")

    def _save_dump(self, text: str, dump_name: str | None, ext: str) -> None:
        """可読名デバッグ用に取得成功応答を保存する(dump_dir・dump_name両方指定時のみ)。"""
        if not (self.dump_dir and dump_name):
            return
        self.dump_dir.mkdir(parents=True, exist_ok=True)
        path = self.dump_dir / f"{dump_name}.{ext}"
        path.write_text(text, encoding="utf-8")
