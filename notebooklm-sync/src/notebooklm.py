"""
PlaywrightでNotebookLM Web UIを操作し、YouTubeソースを追加する。
セレクタは上部定数に集約し、UI変更時の修正箇所を最小化する。
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from playwright.sync_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    TimeoutError as PlaywrightTimeoutError,
    sync_playwright,
)


def _css_escape_attr(s: str) -> str:
    """CSSセレクタ属性値のクォート内に入れる前にエスケープする。"""
    return s.replace("\\", "\\\\").replace('"', '\\"')

logger = logging.getLogger(__name__)

# --- UIセレクタ定数（NotebookLMのUI変更時はここだけ修正する） ---
# 2026-06時点のNotebookLM日本語UI構造に対応
SEL_ADD_SOURCE_BUTTON = "button[aria-label='ソースを追加'], button[aria-label='Add source']"
SEL_URL_INPUT_OPTION = "button:has-text('ウェブサイト'), button:has-text('Website')"
SEL_URL_TEXT_INPUT = "[aria-label='URL を入力'], [placeholder='リンクを貼り付ける'], textarea[placeholder*='URL']"
SEL_INSERT_CONFIRM = "button:has-text('挿入'), button:has-text('Insert')"
SEL_LOGIN_INDICATOR = "input[type='email'], #identifierId, [data-identifier='email']"

# ソース項目・リネーユ関連
SEL_SOURCE_BUTTON = "button.source-stretched-button"
SEL_MORE_BUTTON_IN_SOURCE = "button[aria-label='もっと見る'], button[aria-label='More']"
SEL_RENAME_MENU_ITEM = "[role='menuitem']:has-text('ソース名を変更'), [role='menuitem']:has-text('Rename')"
SEL_DELETE_MENU_ITEM = "[role='menuitem']:has-text('ソースを削除'), [role='menuitem']:has-text('Delete')"
SEL_DIALOG = "[role='dialog']"
SEL_DIALOG_SAVE_BUTTON = "button:has-text('保存'), button:has-text('Save')"
SEL_DIALOG_DELETE_BUTTON = "button:has-text('削除'), button:has-text('Delete')"


class SessionExpiredError(Exception):
    """NotebookLMがGoogleログインページにリダイレクトされた場合に送出する。"""


class NotebookLMClient:
    """Playwrightセッションを管理し、ノートブックへのソース追加を担う。"""

    def __init__(
        self,
        cdp_endpoint: str = "http://localhost:9222",
        user_data_dir: str = "",
        headless: bool = True,
        navigation_timeout_ms: int = 60000,
        source_add_timeout_ms: int = 30000,
        notebooklm_url: str = "https://notebooklm.google.com",
    ) -> None:
        self._cdp_endpoint = cdp_endpoint
        self._user_data_dir = Path(user_data_dir) if user_data_dir else None
        self._headless = headless
        self._nav_timeout = navigation_timeout_ms
        self._add_timeout = source_add_timeout_ms
        self._base_url = notebooklm_url
        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None
        self._owns_page = False

    def _start(self) -> None:
        """常駐している素の実Chrome(remote-debugging)へCDP接続する。
        Playwrightが自前でChromeを起動するとheadless/自動化フラグによりGoogleに
        bot判定されセッションが弾かれるため、別途常駐させた通常Chromeにattachする。
        操作は専用の新規ページで行い、終了時もそのページのみ閉じる（Chrome本体は維持）。"""
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.connect_over_cdp(self._cdp_endpoint)
        contexts = self._browser.contexts
        self._context = contexts[0] if contexts else self._browser.new_context()
        self._context.set_default_navigation_timeout(self._nav_timeout)
        self._context.set_default_timeout(self._add_timeout)
        self._page = self._context.new_page()
        # NotebookLMはレスポンシブで、狭いビューポートだとソースパネルが畳まれ
        # 「ソースを追加」やソース一覧のセレクタが出現しない。広い幅を強制する。
        try:
            self._page.set_viewport_size({"width": 1600, "height": 1000})
        except Exception:
            pass
        self._owns_page = True

    def _stop(self) -> None:
        # CDP接続では自分が開いたページのみ閉じる。Chrome本体・既存タブ・
        # コンテキストは閉じない（context.close()/browser.close()は常駐Chromeを巻き込むため禁止）。
        try:
            if self._page and self._owns_page:
                self._page.close()
        except Exception:
            pass
        try:
            if self._playwright:
                self._playwright.stop()  # remote Chromeは終了させずdisconnectのみ
        except Exception:
            pass

    def __enter__(self) -> "NotebookLMClient":
        self._start()
        return self

    def __exit__(self, *_) -> None:
        self._stop()

    def _notebook_url(self, notebook_id: str) -> str:
        return f"{self._base_url}/notebook/{notebook_id}"

    def _check_login_redirect(self, page: Page) -> None:
        """ログインページへのリダイレクトを検出した堚 SessionExpiredError を投げる。"""
        url = page.url
        if "accounts.google.com" in url or "google.com/signin" in url:
            raise SessionExpiredError(
                f"Google login redirect detected. Current URL: {url}"
            )
        # ログインフォーム要素が存在する場合も検出
        try:
            if page.locator(SEL_LOGIN_INDICATOR).count() > 0:
                raise SessionExpiredError(
                    f"Login form detected on page. Current URL: {url}"
                )
        except SessionExpiredError:
            raise
        except Exception:
            pass

    def navigate_to_notebook(self, notebook_id: str) -> None:
        """ノートブックページへ遷移し、ログアウト状態を検出する。
        NotebookLMはストリーミング接続を保持するためnetworkidleに到達しない。
        domcontentloadedで判定する。"""
        url = self._notebook_url(notebook_id)
        logger.info("notebook_id=%s navigating to %s", notebook_id, url)
        self._page.goto(url, wait_until="domcontentloaded", timeout=self._nav_timeout)
        self._check_login_redirect(self._page)

    def add_youtube_source(self, notebook_id: str, video_url: str) -> bool:
        """
        指定ノートブックにYouTube動画URLをソースとして追加する。
        成功時 True、UI操作失敗・タイムアウト等は False を返しログに記録する。
        Googleセッション切れは SessionExpiredError を再送出する。
        """
        try:
            self.navigate_to_notebook(notebook_id)

            # ノートブックロード完了を待つ（「ソースを追加」が可視 or 自動ダイアログ表示）
            web_btn = self._page.locator(SEL_URL_INPUT_OPTION).first
            dialog_open = False
            try:
                web_btn.wait_for(state="visible", timeout=5000)
                dialog_open = True
                logger.debug("notebook_id=%s source dialog auto-opened", notebook_id)
            except PlaywrightTimeoutError:
                dialog_open = False

            if not dialog_open:
                # 「ソースを追加」ボタンをクリックしてダイアログを開く
                add_btn = self._page.locator(SEL_ADD_SOURCE_BUTTON).first
                add_btn.wait_for(state="visible", timeout=self._add_timeout)
                add_btn.click()
                logger.debug("notebook_id=%s clicked add source button", notebook_id)
                web_btn.wait_for(state="visible", timeout=self._add_timeout)

            # 「ウェブサイト」ボタンをクリック
            web_btn.click()
            logger.debug("notebook_id=%s clicked website option", notebook_id)

            # URL入力フィールドに動画URLを入力
            url_input = self._page.locator(SEL_URL_TEXT_INPUT).first
            url_input.wait_for(state="visible", timeout=self._add_timeout)
            url_input.fill(video_url)
            logger.debug("notebook_id=%s filled URL: %s", notebook_id, video_url)

            # 挿入ボタンをクリックして確定
            insert_btn = self._page.locator(SEL_INSERT_CONFIRM).first
            insert_btn.wait_for(state="visible", timeout=self._add_timeout)
            insert_btn.click()

            # ソース追加の完了待機。挿入ボタン消失または短時間待機で完了とみなす。
            try:
                insert_btn.wait_for(state="hidden", timeout=self._add_timeout)
            except PlaywrightTimeoutError:
                pass
            self._check_login_redirect(self._page)

            logger.info(
                "notebook_id=%s video_url=%s result=success",
                notebook_id, video_url,
            )
            return True

        except SessionExpiredError:
            raise

        except PlaywrightTimeoutError as exc:
            logger.error(
                "notebook_id=%s video_url=%s result=error reason=timeout detail=%s",
                notebook_id, video_url, exc,
            )
            return False

        except Exception as exc:
            logger.error(
                "notebook_id=%s video_url=%s result=error reason=%s detail=%s",
                notebook_id, video_url, type(exc).__name__, exc,
            )
            return False

    def fetch_youtube_upload_date(self, video_id: str) -> str:
        """ログイン済みPlaywrightコンテキストでYouTube動画ページを開き、
        HTML内の uploadDate (YYYY-MM-DD) を抽出して返す。
        VPS IPが直接HTTP取得でbot判定される回避策。失敗時は空文字を返す。"""
        import re
        url = f"https://www.youtube.com/watch?v={video_id}"
        page = self._context.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=20000)
            html = page.content()
            m = re.search(r'"uploadDate":"([\d\-T:+Z]{10,})"', html)
            if not m:
                return ""
            raw = m.group(1)
            if len(raw) >= 10 and raw[4] == "-" and raw[7] == "-":
                return raw[:10]
            return ""
        except Exception as exc:
            logger.warning("fetch_youtube_upload_date failed for %s: %s", video_id, exc)
            return ""
        finally:
            try:
                page.close()
            except Exception:
                pass

    def _rename_in_open_notebook(self, match_value: str, new_title: str) -> bool:
        """現在開いているノートブックに対してリネームを実行（navigateしない）。
        成功時 True、対象未検出・UIエラーは False。"""
        try:
            target = self._page.locator(
                f'{SEL_SOURCE_BUTTON}[aria-label="{_css_escape_attr(match_value)}"]'
            ).first
            try:
                target.wait_for(state="visible", timeout=3000)
            except PlaywrightTimeoutError:
                return False

            target.scroll_into_view_if_needed(timeout=3000)
            target.hover()
            parent = target.locator("xpath=./..")
            more_btn = parent.locator(SEL_MORE_BUTTON_IN_SOURCE).first
            more_btn.wait_for(state="visible", timeout=self._add_timeout)
            more_btn.click()

            rename_item = self._page.locator(SEL_RENAME_MENU_ITEM).first
            rename_item.wait_for(state="visible", timeout=self._add_timeout)
            rename_item.click()

            dialog = self._page.locator(SEL_DIALOG).last
            dialog.wait_for(state="visible", timeout=self._add_timeout)
            title_input = dialog.locator("textarea, input[type='text'], input:not([type])").first
            title_input.wait_for(state="visible", timeout=self._add_timeout)
            title_input.fill(new_title)

            save_btn = dialog.locator(SEL_DIALOG_SAVE_BUTTON).first
            save_btn.click()
            try:
                dialog.wait_for(state="hidden", timeout=self._add_timeout)
            except PlaywrightTimeoutError:
                pass
            return True

        except PlaywrightTimeoutError:
            # メニューが閉じてない可能性 → Escapeで閉じる
            try:
                self._page.keyboard.press("Escape")
            except Exception:
                pass
            return False
        except Exception:
            try:
                self._page.keyboard.press("Escape")
            except Exception:
                pass
            return False

    def rename_source(self, notebook_id: str, match_value: str, new_title: str) -> bool:
        """単発リネーユ（navigateあり）。互換用に残す。"""
        try:
            self.navigate_to_notebook(notebook_id)
            self._page.locator(SEL_SOURCE_BUTTON).first.wait_for(
                state="visible", timeout=self._add_timeout
            )
            ok = self._rename_in_open_notebook(match_value, new_title)
            self._check_login_redirect(self._page)
            if ok:
                logger.info(
                    "notebook_id=%s match=%s new_title=%s result=success",
                    notebook_id, match_value[:40], new_title[:40],
                )
            else:
                logger.warning(
                    "notebook_id=%s match=%s result=skip reason=not_found_or_error",
                    notebook_id, match_value[:40],
                )
            return ok
        except SessionExpiredError:
            raise
        except Exception as exc:
            logger.error(
                "notebook_id=%s match=%s result=error reason=%s detail=%s",
                notebook_id, match_value, type(exc).__name__, exc,
            )
            return False

    def delete_source(self, notebook_id: str, match_value: str) -> bool:
        """指定ソースを削除する。失敗時はFalseを返す。"""
        try:
            self.navigate_to_notebook(notebook_id)
            self._page.locator(SEL_SOURCE_BUTTON).first.wait_for(
                state="visible", timeout=self._add_timeout
            )

            target = self._page.locator(
                f'{SEL_SOURCE_BUTTON}[aria-label="{_css_escape_attr(match_value)}"]'
            ).first
            try:
                target.wait_for(state="visible", timeout=5000)
            except PlaywrightTimeoutError:
                return False

            target.scroll_into_view_if_needed(timeout=3000)
            target.hover()
            parent = target.locator("xpath=./..")
            more_btn = parent.locator(SEL_MORE_BUTTON_IN_SOURCE).first
            more_btn.wait_for(state="visible", timeout=self._add_timeout)
            more_btn.click()

            delete_item = self._page.locator(SEL_DELETE_MENU_ITEM).first
            delete_item.wait_for(state="visible", timeout=self._add_timeout)
            delete_item.click()

            # 確認ダイアログの削除ボタン
            dialog = self._page.locator(SEL_DIALOG).last
            dialog.wait_for(state="visible", timeout=self._add_timeout)
            confirm_btn = dialog.locator(SEL_DIALOG_DELETE_BUTTON).first
            confirm_btn.click()

            try:
                dialog.wait_for(state="hidden", timeout=self._add_timeout)
            except PlaywrightTimeoutError:
                pass

            self._check_login_redirect(self._page)
            logger.info(
                "notebook_id=%s match=%s result=deleted",
                notebook_id, match_value[:60],
            )
            return True
        except SessionExpiredError:
            raise
        except Exception as exc:
            logger.error(
                "notebook_id=%s match=%s delete result=error reason=%s detail=%s",
                notebook_id, match_value, type(exc).__name__, exc,
            )
            try:
                self._page.keyboard.press("Escape")
            except Exception:
                pass
            return False

    def list_sources(self, notebook_id: str) -> list:
        """ノートブック内の全ソースの aria-label をリストで返す。"""
        self.navigate_to_notebook(notebook_id)
        self._page.locator(SEL_SOURCE_BUTTON).first.wait_for(
            state="visible", timeout=self._add_timeout
        )
        labels = []
        btns = self._page.locator(SEL_SOURCE_BUTTON).all()
        for b in btns:
            try:
                a = b.get_attribute("aria-label") or ""
                labels.append(a)
            except Exception:
                pass
        return labels

    def bulk_rename(self, notebook_id: str, pairs: list) -> list:
        """同じノートブックに対して複数リネームを連続実行する。
        pairs: [(match_value, new_title), ...]
        戻り値: [(match_value, success_bool), ...]"""
        self.navigate_to_notebook(notebook_id)
        self._page.locator(SEL_SOURCE_BUTTON).first.wait_for(
            state="visible", timeout=self._add_timeout
        )
        results = []
        for i, (mv, nt) in enumerate(pairs):
            ok = self._rename_in_open_notebook(mv, nt)
            results.append((mv, ok))
            logger.info(
                "bulk_rename notebook_id=%s [%d/%d] match=%s result=%s",
                notebook_id, i + 1, len(pairs), mv[:40], "ok" if ok else "fail",
            )
            self._check_login_redirect(self._page)
        return results
