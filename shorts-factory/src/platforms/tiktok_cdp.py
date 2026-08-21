"""TikTok アップロード（常駐Chrome + Playwright CDP接続）。【実験的】

公式 Content Posting API は審査必須のため、TikTok Studio のアップロード画面を
ブラウザ操作する。TikTokはUI変更が頻繁なので、失敗時はスクリーンショットを
保存して blocked にし、人間へ通知する運用とする。

前提: shorts-tiktok-chrome の常駐Chromeプロファイルに TikTok ログイン済み。
config.yaml の queue.platforms に "tiktok" を加えると有効化される。
"""
from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path

from ..config import CONFIG

CDP_URL = f"http://127.0.0.1:{CONFIG.get('tiktok', 'cdp_port', default=9224)}"
UPLOAD_URL = "https://www.tiktok.com/tiktokstudio/upload?from=upload"


def _shot(page, tag: str) -> Path:
    p = CONFIG.logs_dir / f"tt_{tag}_{datetime.now().strftime('%m%d_%H%M%S')}.png"
    try:
        page.screenshot(path=str(p))
    except Exception:
        pass
    return p


def _dismiss_optional_auto_check_prompt(page) -> None:
    """Close TikTok's optional content auto-check prompt when it blocks upload."""
    for text in ("キャンセル", "Cancel"):
        btn = page.locator(f"button:has-text('{text}')").last
        try:
            if btn.count() and btn.is_visible(timeout=1000):
                btn.click()
                time.sleep(1)
                return
        except Exception:
            continue


def _discard_resume_draft_prompt(page) -> None:
    """Discard an unfinished failed upload draft if TikTok asks to resume it."""
    for text in ("破棄する", "Discard"):
        btn = page.locator(f"button:has-text('{text}')").last
        try:
            if btn.count() and btn.is_visible(timeout=1000):
                btn.click()
                time.sleep(2)
                confirm = page.locator(f"button:has-text('{text}')").last
                if confirm.count() and confirm.is_visible(timeout=1000):
                    confirm.click()
                    time.sleep(2)
                return
        except Exception:
            continue


def _is_login_page(page) -> bool:
    if "login" in page.url.lower():
        return True
    for text in (
        "TikTokにログイン",
        "Log in to TikTok",
        "電話番号/メール/ユーザー名を使う",
        "Use phone / email / username",
        "QRコードを使う",
    ):
        try:
            loc = page.get_by_text(text).first
            if loc.count() and loc.is_visible(timeout=1000):
                return True
        except Exception:
            continue
    return False


def _choose_video_file(page, video_path: Path) -> None:
    """Attach the video file, preferring TikTok's stable hidden file input."""
    try:
        page.wait_for_selector("input[type=file]", state="attached", timeout=30000)
        page.set_input_files("input[type=file]", str(video_path))
        return
    except Exception:
        pass

    chooser = page.locator(
        "button:has-text('動画を選択'), "
        "button:has-text('Select video'), "
        "button:has-text('アップロード'), "
        "[role=button]:has-text('動画を選択'), "
        "[role=button]:has-text('Select video')"
    ).first
    try:
        if chooser.count() and chooser.is_visible(timeout=3000):
            with page.expect_file_chooser(timeout=10000) as fc:
                chooser.click()
            fc.value.set_files(str(video_path))
            return
    except Exception:
        pass
    page.wait_for_selector("input[type=file]", state="attached", timeout=60000)
    page.set_input_files("input[type=file]", str(video_path))


def _set_editor_text(editor, value: str) -> None:
    """Replace TikTok's contenteditable caption reliably."""
    try:
        editor.click(timeout=10000, force=True)
    except Exception:
        editor.evaluate("(el) => el.focus()")
    editor.evaluate(
        """(el, value) => {
            el.focus();
            const selection = window.getSelection();
            const range = document.createRange();
            range.selectNodeContents(el);
            selection.removeAllRanges();
            selection.addRange(range);
            document.execCommand('insertText', false, value);
            el.dispatchEvent(new InputEvent('input', {
                bubbles: true,
                inputType: 'insertText',
                data: value
            }));
            el.dispatchEvent(new Event('change', { bubbles: true }));
            el.dispatchEvent(new KeyboardEvent('keyup', { bubbles: true }));
        }""",
        value,
    )


def check_session() -> bool:
    """TikTok Studio upload page に到達できるか確認する。投稿はしない。"""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.connect_over_cdp(CDP_URL, no_defaults=True, is_local=True)
        ctx = browser.contexts[0] if browser.contexts else browser.new_context()
        page = ctx.new_page()
        try:
            page.goto(UPLOAD_URL, timeout=60000)
            page.wait_for_load_state("domcontentloaded")
            time.sleep(4)
            if _is_login_page(page):
                _shot(page, "login_required")
                return False
            _discard_resume_draft_prompt(page)
            try:
                page.wait_for_selector("input[type=file]", state="attached", timeout=60000)
            except Exception:
                return False
            return page.locator("input[type=file]").count() > 0
        finally:
            page.close()


def upload(video_path: Path, caption: str, timeout_sec: int = 900) -> str:
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
            page.goto(UPLOAD_URL, timeout=60000)
            page.wait_for_load_state("domcontentloaded")
            time.sleep(5)
            if _is_login_page(page):
                shot = _shot(page, "login_required")
                raise RuntimeError(f"TikTokセッション失効。scripts/login_tiktok.sh で専用Chromeに再ログインしてください（スクショ: {shot}）")
            _discard_resume_draft_prompt(page)
            if _is_login_page(page):
                shot = _shot(page, "login_required")
                raise RuntimeError(f"TikTokセッヷョン失効。scripts/login_tiktok.sh で専用Chromeに再ログインしてください（スクショ: {shot}）")

            _choose_video_file(page, video_path)

            # アップロード完了（キャプション編集領域の出現）を待つ。
            # TikTok Studio can leave the chooser button spinning without
            # accepting the file; reload once and submit again in that case.
            try:
                page.wait_for_selector("div[contenteditable='true']", timeout=180000)
            except PlaywrightTimeoutError:
                _shot(page, "upload_stuck")
                page.goto(UPLOAD_URL, timeout=60000)
                page.wait_for_load_state("domcontentloaded")
                time.sleep(5)
                _discard_resume_draft_prompt(page)
                _choose_video_file(page, video_path)
                page.wait_for_selector("div[contenteditable='true']", timeout=240000)
            time.sleep(3)
            _dismiss_optional_auto_check_prompt(page)

            editor = page.locator("div[contenteditable='true']").first
            _set_editor_text(editor, caption[:2000])
            time.sleep(2)

            # 投稿ボタン（data-e2e属性は比較的安定）
            deadline = time.time() + timeout_sec
            posted = False
            while time.time() < deadline:
                btn = page.locator("button[data-e2e='post_video_button']")
                if not btn.count():
                    btn = page.locator("button:has-text('投稿')")
                if btn.count() and btn.first.is_enabled():
                    btn.first.click()
                    posted = True
                    break
                time.sleep(3)
            if not posted:
                raise RuntimeError("投稿ボタンが有効になりませんでした")
            time.sleep(8)
            return "https://www.tiktok.com/tiktokstudio/content"
        except Exception as e:
            shot = _shot(page, "fail")
            raise RuntimeError(f"TikTokアップロード失敗: {e}（スクショ: {shot}）") from e
        finally:
            page.close()
