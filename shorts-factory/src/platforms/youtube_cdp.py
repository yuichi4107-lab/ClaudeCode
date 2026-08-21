"""YouTube Shorts アップロード（常駐Chrome + Playwright CDP接続）。

Data API v3 は未審査プロジェクトの動画が強制非公開になるため、
notebooklm-sync と同じ「常駐Chrome(専用プロファイル) + CDP」方式で
YouTube Studio をブラウザ操作してアップロードする。

前提:
- launchd com.ynfactory.shorts-chrome が port 9223 でChromeを常駐
- 初回のみ scripts/login_youtube.sh でそのプロファイルにGoogleログイン済み

セレクタは言語非依存の id / name のみ使用（UI文言変更に強い）。
失敗時は logs/ にスクリーンショットを保存して例外を投げる。
"""
from __future__ import annotations

import re
import time
from datetime import datetime
from pathlib import Path
from urllib import error as urlerror
from urllib import parse, request

from ..config import CONFIG

CDP_URL = f"http://127.0.0.1:{CONFIG.get('youtube', 'cdp_port', default=9223)}"
UPLOAD_URL = "https://www.youtube.com/upload"


class SessionExpired(RuntimeError):
    """Googleセッション失効。login_youtube.sh での再ログインが必要。"""


def _shot(page, tag: str) -> Path:
    p = CONFIG.logs_dir / f"yt_{tag}_{datetime.now().strftime('%m%d_%H%M%S')}.png"
    try:
        page.screenshot(path=str(p))
    except Exception:
        pass
    return p


def _set_contenteditable(locator, value: str) -> None:
    """Set YouTube Studio contenteditable fields without relying on click stability."""
    try:
        locator.fill(value, timeout=10000)
        return
    except Exception:
        pass
    locator.evaluate(
        """(el, value) => {
            el.focus();
            el.textContent = value;
            el.dispatchEvent(new InputEvent('input', {
                bubbles: true,
                inputType: 'insertText',
                data: value
            }));
            el.dispatchEvent(new Event('change', { bubbles: true }));
        }""",
        value,
    )


def _click(locator) -> None:
    """Click controls in YouTube Studio even while upload progress causes layout churn."""
    try:
        locator.click(timeout=10000)
        return
    except Exception:
        pass
    try:
        locator.click(timeout=10000, force=True)
        return
    except Exception:
        pass
    locator.evaluate("(el) => el.click()")


def _video_url(page) -> str:
    for selector in ("a[href*='youtube.com/shorts/']", "a[href^='https://youtu.be/']"):
        try:
            link = page.locator(selector).first
            if link.count():
                return link.get_attribute("href") or ""
        except Exception:
            continue
    return ""


def _normalize_shorts_url(url: str) -> str:
    parsed = parse.urlparse(url)
    if "youtu.be" in parsed.netloc:
        video_id = parsed.path.strip("/").split("/")[0]
    else:
        parts = [p for p in parsed.path.split("/") if p]
        video_id = ""
        if "shorts" in parts:
            idx = parts.index("shorts")
            if len(parts) > idx + 1:
                video_id = parts[idx + 1]
        elif "watch" in parts:
            video_id = parse.parse_qs(parsed.query).get("v", [""])[0]
    return f"https://youtube.com/shorts/{video_id}" if video_id else url


def _public_playability(url: str) -> tuple[str, str]:
    """Return YouTube public player status without using the logged-in browser."""
    req = request.Request(
        _normalize_shorts_url(url),
        headers={"User-Agent": "Mozilla/5.0"},
    )
    try:
        with request.urlopen(req, timeout=30) as res:
            body = res.read(1_500_000).decode("utf-8", "ignore")
    except urlerror.HTTPError as e:
        return f"HTTP_{e.code}", ""

    idx = body.find('"playabilityStatus"')
    if idx < 0:
        return "UNKNOWN", "playabilityStatus not found"
    snippet = body[idx : idx + 5000]
    status = re.search(r'"status"\s*:\s*"([^"]+)"', snippet)
    reason = re.search(r'"reason"\s*:\s*"([^"]+)"', snippet)
    message = re.search(r'"messages"\s*:\s*\[\s*"([^"]+)"', snippet)
    return (
        status.group(1) if status else "UNKNOWN",
        (reason or message).group(1) if (reason or message) else "",
    )


def _wait_for_public_playable(url: str, timeout_sec: int) -> None:
    """Wait until a logged-out viewer can actually play the uploaded Short."""
    deadline = time.time() + timeout_sec
    last_status = "UNKNOWN"
    last_reason = ""
    while time.time() < deadline:
        last_status, last_reason = _public_playability(url)
        if last_status == "OK":
            return
        if last_status == "LOGIN_REQUIRED":
            raise RuntimeError(f"YouTube公開検証失敗: 非公開状態です ({last_reason})")
        time.sleep(20)
    raise RuntimeError(
        "YouTube公開検証失敗: "
        f"{timeout_sec}秒待っても再生可能になりませんでした "
        f"({last_status}: {last_reason})"
    )


def check_session() -> bool:
    """Studioに到達できるか（ログイン生存確認）。"""
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.connect_over_cdp(CDP_URL, no_defaults=True, is_local=True)
        ctx = browser.contexts[0] if browser.contexts else browser.new_context()
        page = ctx.new_page()
        try:
            try:
                page.goto(
                    "https://studio.youtube.com",
                    timeout=45000,
                    wait_until="domcontentloaded",
                )
            except PlaywrightTimeoutError:
                if "studio.youtube.com" not in page.url:
                    raise
            time.sleep(3)
            return "accounts.google.com" not in page.url
        finally:
            page.close()


def upload(video_path: Path, title: str, description: str, timeout_sec: int = 420) -> str:
    """動画をアップロードして公開し、URLを返す。"""
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    from playwright.sync_api import sync_playwright

    if not video_path.exists():
        raise FileNotFoundError(video_path)

    with sync_playwright() as pw:
        browser = pw.chromium.connect_over_cdp(CDP_URL, no_defaults=True, is_local=True)
        ctx = browser.contexts[0] if browser.contexts else browser.new_context()
        ctx.set_default_timeout(45000)
        page = ctx.new_page()
        try:
            loaded = True
            try:
                page.goto(UPLOAD_URL, timeout=60000, wait_until="domcontentloaded")
            except PlaywrightTimeoutError:
                loaded = False
                # The upload modal can be usable even when YouTube keeps the
                # page load pending. Continue if the upload UI is already there.
                if not (
                    page.locator("input[type=file]").count()
                    or page.locator("ytcp-uploads-dialog").count()
                ):
                    raise
            if loaded:
                page.wait_for_load_state("domcontentloaded")
            time.sleep(4)
            if "accounts.google.com" in page.url:
                raise SessionExpired(
                    "YouTubeセッション失効。scripts/login_youtube.sh で再ログインしてください"
                )

            # ファイル選択（アップロードダイアログの input[type=file]）
            page.wait_for_selector("input[type=file]", state="attached", timeout=60000)
            page.set_input_files("input[type=file]", str(video_path))

            # メタデータダイアログ
            # YouTube Studio sometimes keeps the dialog host hidden while its
            # inner controls are already visible, so wait for attachment and
            # target the visible textboxes directly.
            page.wait_for_selector("ytcp-uploads-dialog", state="attached", timeout=90000)
            time.sleep(3)
            boxes = page.locator("#textbox")
            _set_contenteditable(boxes.nth(0), title)
            _set_contenteditable(boxes.nth(1), description[:4500])

            # 「子ども向けではない」
            _click(page.locator("tp-yt-paper-radio-button[name='VIDEO_MADE_FOR_KIDS_NOT_MFK']").first)

            # 動画URLを先に取得（ダイアログ内の youtu.be リンク）
            url = ""
            try:
                page.wait_for_selector(
                    "a[href*='youtube.com/shorts/'], a[href^='https://youtu.be/']",
                    timeout=60000,
                )
                url = _video_url(page)
            except Exception:
                pass

            # 次へ ×3（詳細 → 動画の要素 → チェック）
            for _ in range(3):
                _click(page.locator("#next-button").first)
                time.sleep(2)

            # 公開設定
            _click(page.locator("tp-yt-paper-radio-button[name='PUBLIC']").first)
            time.sleep(1)

            # アップロード完了を待ってから保存（done が有効になるまで）
            deadline = time.time() + timeout_sec
            ready = False
            while time.time() < deadline:
                btn = page.locator("#done-button")
                if btn.count() and btn.first.is_enabled():
                    ready = True
                    break
                time.sleep(3)
            if not ready:
                raise RuntimeError(f"アップロードが{timeout_sec}秒以内に完了しませんでした")
            _click(page.locator("#done-button").first)
            time.sleep(3)
            publish_anyway = page.locator("button:has-text('公開する')").last
            try:
                if publish_anyway.count() and publish_anyway.is_visible(timeout=2000):
                    _click(publish_anyway)
                    time.sleep(5)
            except Exception:
                pass

            # 「処理中」ダイアログが出たら閉じる
            try:
                dialog_close = page.locator(
                    "ytcp-uploads-still-processing-dialog #close-button, "
                    "ytcp-uploads-still-processing-dialog ytcp-button"
                )
                if dialog_close.count():
                    dialog_close.first.click()
            except Exception:
                pass

            if not url:
                url = _video_url(page)
            if not url:
                raise RuntimeError("動画URLが取得できませんでした（アップロードは完了している可能性あり）")
            url = _normalize_shorts_url(url)
            verify_timeout = int(
                CONFIG.get("youtube", "public_verify_timeout_sec", default=900)
            )
            _wait_for_public_playable(url, verify_timeout)
            return url
        except SessionExpired:
            raise
        except Exception as e:
            shot = _shot(page, "fail")
            raise RuntimeError(f"YouTubeアップロード失敗: {e}（スクショ: {shot}）") from e
        finally:
            page.close()
