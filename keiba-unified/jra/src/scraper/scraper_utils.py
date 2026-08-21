"""スクレイピング共通ユーティリティ"""

import time
from typing import Optional

import requests
from bs4 import BeautifulSoup

from src.utils.config_loader import load_settings
from src.utils.logger import setup_logger

logger = setup_logger(__name__)

_settings = load_settings()
_scraping_cfg = _settings.get("scraping", {})

DEFAULT_HEADERS = {
    "User-Agent": _scraping_cfg.get(
        "user_agent",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ja,en-US;q=0.7,en;q=0.3",
}

_TIMEOUT = _scraping_cfg.get("timeout_sec", 30)
_last_request_time: float = 0.0


def throttled_get(
    url: str,
    interval: float = None,
    headers: Optional[dict] = None,
) -> requests.Response:
    """レートリミット付きHTTP GETリクエスト"""
    global _last_request_time

    if interval is None:
        interval = _scraping_cfg.get("request_interval_sec", 2.0)

    elapsed = time.time() - _last_request_time
    if elapsed < interval:
        wait = interval - elapsed
        logger.debug("Throttling: waiting %.1f sec", wait)
        time.sleep(wait)

    req_headers = {**DEFAULT_HEADERS, **(headers or {})}
    logger.debug("GET %s", url)

    response = requests.get(url, headers=req_headers, timeout=_TIMEOUT)
    _last_request_time = time.time()

    response.raise_for_status()
    return response


def parse_html(html_text: str) -> BeautifulSoup:
    """HTML文字列をBeautifulSoupオブジェクトとして返す"""
    return BeautifulSoup(html_text, "lxml")


def retry_request(
    url: str,
    max_retries: int = None,
    delay: float = None,
) -> Optional[requests.Response]:
    """リトライ付きHTTPリクエスト"""
    if max_retries is None:
        max_retries = _scraping_cfg.get("max_retries", 3)
    if delay is None:
        delay = _scraping_cfg.get("retry_delay_sec", 5.0)

    for attempt in range(1, max_retries + 1):
        try:
            return throttled_get(url)
        except requests.RequestException as e:
            logger.warning(
                "Request failed (attempt %d/%d): %s - %s",
                attempt, max_retries, url, e,
            )
            if attempt < max_retries:
                time.sleep(delay)
            else:
                logger.error("All %d retries failed for %s", max_retries, url)
                raise
    return None
