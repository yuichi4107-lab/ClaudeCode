from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .config import BrowserConfig


class BrowserAutomationError(RuntimeError):
    pass


class LoginRequiredError(BrowserAutomationError):
    pass


ROOM_BUTTON_PATTERNS = [
    re.compile(r"ROOMに投稿|ROOMで紹介|ROOMへ投稿", re.IGNORECASE),
]
SUBMIT_PATTERNS = [
    re.compile(r"完了|投稿|紹介する|保存", re.IGNORECASE),
]
CAPTCHA_OR_VERIFICATION_PATTERNS = [
    re.compile(r"captcha|recaptcha", re.IGNORECASE),
    re.compile(r"ロボット|私はロボットではありません|画像認証|本人確認|追加認証|二段階認証|セキュリティ認証"),
]
LOGIN_URL_PATTERNS = [
    re.compile(r"login", re.IGNORECASE),
    re.compile(r"member\.id\.rakuten\.co\.jp|grp\d+\.id\.rakuten\.co\.jp", re.IGNORECASE),
]
LOGIN_FORM_PATTERNS = [
    re.compile(r"楽天会員ログイン|ログインしてください|ユーザID|ユーザーID|パスワード"),
]
ROOM_ITEM_COUNT_PATTERN = re.compile(r"商品\s*(\d+)")

# runner側の中断判定でも使うため、文言を変えるときは両方まとめて変える
SUBMIT_NOT_REFLECTED_PREFIX = "送信は完了しましたが、ROOM側の商品数が増えていません"


@dataclass
class PostResult:
    ok: bool
    message: str


class RakutenRoomBrowser:
    def __init__(self, config: BrowserConfig):
        self.config = config
        self._playwright: Any = None
        self._browser: Any = None
        self._context: Any = None
        self._pages: list[Any] = []

    def __enter__(self) -> "RakutenRoomBrowser":
        self.connect()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def connect(self) -> None:
        from playwright.sync_api import sync_playwright

        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.connect_over_cdp(self.config.cdp_endpoint)
        if not self._browser.contexts:
            raise BrowserAutomationError("Chromeのコンテキストが見つかりません。専用Chromeを起動してから再実行してください。")
        self._context = self._browser.contexts[0]
        self._context.set_default_timeout(self.config.action_timeout_ms)
        self._context.set_default_navigation_timeout(self.config.navigation_timeout_ms)

    def close(self) -> None:
        for page in reversed(self._pages):
            try:
                page.close()
            except Exception:
                pass
        if self._playwright:
            self._playwright.stop()
        self._browser = None
        self._playwright = None
        self._context = None
        self._pages = []

    def _new_page(self):
        if self._context is None:
            raise BrowserAutomationError("ブラウザに接続されていません。")
        page = self._context.new_page()
        self._pages.append(page)
        return page

    def _check_blocked(self, page) -> None:
        body = page.locator("body").inner_text(timeout=5000)[:4000]
        url = page.url
        for pattern in CAPTCHA_OR_VERIFICATION_PATTERNS:
            if pattern.search(body):
                raise LoginRequiredError(f"画像認証など追加の本人確認が必要です。専用Chromeで手動確認してください。 url={url}")
        if any(pattern.search(url) for pattern in LOGIN_URL_PATTERNS):
            raise LoginRequiredError(f"楽天へのログインが切れています。専用Chromeで再ログインしてください。 url={url}")
        has_password_input = page.locator('input[type="password"]').count() > 0
        if has_password_input and any(pattern.search(body) for pattern in LOGIN_FORM_PATTERNS):
            raise LoginRequiredError(f"楽天へのログインが切れています。専用Chromeで再ログインしてください。 url={url}")

    def check_session(self) -> PostResult:
        page = self._new_page()
        try:
            page.goto(self.config.my_room_url, wait_until="domcontentloaded")
            self._check_blocked(page)
            body = page.locator("body").inner_text(timeout=10000)
            title = page.title()
            expected = self.config.expected_profile_name
            if expected and expected not in body and expected not in title:
                return PostResult(False, f"ログイン済みですが、想定したプロフィール名が見つかりません: {expected}")
            return PostResult(True, "楽天ROOMのセッションは有効です。")
        finally:
            page.close()

    def fetch_ranking_items(self, ranking_url: str, limit: int = 20) -> list[dict[str, str]]:
        """楽天ランキングページから実在の商品URLとタイトルを取得する。"""
        page = self._new_page()
        try:
            response = page.goto(ranking_url, wait_until="domcontentloaded")
            if response is not None and response.status >= 400:
                raise BrowserAutomationError(
                    f"ランキングページが開けません (HTTP {response.status})。 url={ranking_url}"
                )
            self._check_blocked(page)
            page.wait_for_timeout(2500)
            items = page.evaluate(
                """
                (limit) => {
                  const seen = new Set();
                  const out = [];
                  for (const a of document.querySelectorAll('a[href*="item.rakuten.co.jp"]')) {
                    const m = a.href.match(/https:\\/\\/item\\.rakuten\\.co\\.jp\\/[^\\/]+\\/[^\\/?#]+\\//);
                    if (!m) continue;
                    const url = m[0];
                    const title = (a.textContent || '').trim();
                    if (seen.has(url) || title.length < 15) continue;
                    seen.add(url);
                    out.push({ url, title: title.slice(0, 120) });
                    if (out.length >= limit) break;
                  }
                  return out;
                }
                """,
                limit,
            )
            return list(items)
        finally:
            page.close()

    def post_product(self, product_url: str, description: str, dry_run: bool = False) -> PostResult:
        page = self._new_page()
        try:
            before_count = self._read_my_room_item_count()
            response = page.goto(product_url, wait_until="domcontentloaded")
            if response is not None and response.status >= 400:
                raise BrowserAutomationError(
                    f"商品ページが開けません (HTTP {response.status})。商品URLが無効か販売終了の可能性があります。"
                )
            self._check_blocked(page)
            post_page = self._click_room_button(page)
            post_page.wait_for_load_state("domcontentloaded")
            self._check_blocked(post_page)
            self._fill_description(post_page, description)
            if dry_run:
                return PostResult(True, "dry-run: 投稿画面まで到達しました（送信はしていません）。")
            self._click_submit(post_page)
            post_page.wait_for_load_state("domcontentloaded")
            self._check_blocked(post_page)
            self._wait_for_post_reflected(before_count)
            return PostResult(True, "楽天ROOMに投稿しました。")
        finally:
            page.close()

    def _click_room_button(self, page):
        context = page.context
        direct_links = page.locator('a[href*="room.rakuten.co.jp/mix"], a[href*="/mix?itemcode="]')
        for index in range(min(direct_links.count(), 5)):
            link = direct_links.nth(index)
            if not link.is_visible():
                continue
            href = link.get_attribute("href")
            if not href:
                continue
            page.goto(href, wait_until="domcontentloaded")
            return page
        for pattern in ROOM_BUTTON_PATTERNS:
            candidates = page.get_by_text(pattern)
            count = min(candidates.count(), 5)
            for index in range(count):
                candidate = candidates.nth(index)
                if not candidate.is_visible():
                    continue
                before = set(context.pages)
                candidate.click()
                page.wait_for_timeout(1500)
                new_pages = [candidate_page for candidate_page in context.pages if candidate_page not in before]
                if new_pages:
                    self._pages.extend(new_pages)
                    return new_pages[-1]
                return page
        clicked = page.evaluate(
            """
            () => {
              const nodes = [...document.querySelectorAll('a,button,[role="button"]')];
              const target = nodes.find((node) => {
                const text = [node.innerText, node.getAttribute('aria-label'), node.getAttribute('title'), node.href]
                  .filter(Boolean).join(' ');
                return /ROOM/i.test(text);
              });
              if (!target) return false;
              target.click();
              return true;
            }
            """
        )
        if not clicked:
            raise BrowserAutomationError(
                "商品ページにROOM投稿ボタンが見つかりません。掲載終了か商品URLが無効の可能性があります。"
            )
        page.wait_for_timeout(1500)
        return page

    def _fill_description(self, page, description: str) -> None:
        textareas = page.locator("textarea")
        if textareas.count() > 0:
            textarea = textareas.first
            textarea.click()
            textarea.fill(description)
            page.wait_for_timeout(300)
            if textarea.input_value(timeout=5000).strip() == description.strip():
                return
            textarea.click()
            textarea.press("Meta+A")
            textarea.press("Backspace")
            textarea.type(description, delay=5)
            if textarea.input_value(timeout=5000).strip() != description.strip():
                raise BrowserAutomationError("投稿画面のコメント欄に紹介文を入力できませんでした。")
            return
        editable = page.locator('[contenteditable="true"]')
        if editable.count() > 0:
            target = editable.first
            target.click()
            target.press("Meta+A")
            target.press("Backspace")
            target.type(description, delay=5)
            return
        raise BrowserAutomationError("投稿画面にコメント入力欄が見つかりませんでした。ROOM側の画面仕様が変わった可能性があります。")

    def _click_submit(self, page) -> None:
        for pattern in SUBMIT_PATTERNS:
            candidates = page.get_by_role("button", name=pattern)
            count = min(candidates.count(), 5)
            for index in range(count):
                candidate = candidates.nth(index)
                if candidate.is_visible() and candidate.is_enabled():
                    try:
                        candidate.click()
                    except Exception:
                        candidate.evaluate("(element) => element.click()")
                    return
        clicked = page.evaluate(
            """
            () => {
              const nodes = [...document.querySelectorAll('button,input[type="submit"],[role="button"]')];
              const target = nodes.find((node) => {
                const text = [node.innerText, node.value, node.getAttribute('aria-label'), node.getAttribute('title')]
                  .filter(Boolean).join(' ');
                return /(完了|投稿|紹介する|保存)/.test(text) && !node.disabled;
              });
              if (!target) return false;
              target.click();
              return true;
            }
            """
        )
        if not clicked:
            raise BrowserAutomationError("投稿画面で送信（完了）ボタンが見つかりませんでした。ROOM側の画面仕様が変わった可能性があります。")

    def _read_my_room_item_count(self) -> int | None:
        page = self._new_page()
        try:
            page.goto(self.config.my_room_url, wait_until="domcontentloaded")
            self._check_blocked(page)
            page.wait_for_timeout(3000)
            body = page.locator("body").inner_text(timeout=10000)
            return parse_room_item_count(body)
        finally:
            page.close()

    def _wait_for_post_reflected(self, before_count: int | None) -> None:
        if before_count is None:
            raise BrowserAutomationError("投稿前にmy ROOMの商品数を読み取れませんでした。")
        last_count: int | None = None
        for _ in range(6):
            page = self._new_page()
            try:
                page.goto(self.config.my_room_url, wait_until="domcontentloaded")
                self._check_blocked(page)
                page.wait_for_timeout(3000)
                body = page.locator("body").inner_text(timeout=10000)
                last_count = parse_room_item_count(body)
                if last_count is not None and last_count > before_count:
                    return
            finally:
                page.close()
        raise BrowserAutomationError(
            f"{SUBMIT_NOT_REFLECTED_PREFIX}。実際に投稿されたかmy ROOMを手動確認してください。"
            f" before={before_count}, after={last_count}"
        )


def parse_room_item_count(body_text: str) -> int | None:
    match = ROOM_ITEM_COUNT_PATTERN.search(body_text)
    if not match:
        return None
    return int(match.group(1))
