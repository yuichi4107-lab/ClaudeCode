"""
セッション有効性チェック（永続プロファイル方式の健全性確認）。

cwd=notebooklm-sync ルートで実行すること:
  .venv/bin/python scripts/check_session.py

config.yaml の先頭チャンネルのノートブックを headless で開き、
- SessionExpiredError が出ない（=ログイン維持）
- ソース一覧が取得できる（=ノートブック内容にアクセスできている）
ことを確認する。終了コード: 0=OK / 2=セッション切れ / 3=その他エラー
"""
from __future__ import annotations

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC))

from config import load_config  # noqa: E402
from notebooklm import NotebookLMClient, SessionExpiredError  # noqa: E402


def main() -> None:
    cfg = load_config(config_path="config.yaml", secrets_path="secrets.yaml")
    if not cfg.channels:
        print("ERROR: config.yaml に channels がありません")
        sys.exit(3)
    nb = cfg.channels[0]
    print(f"[check] notebook: {nb.name} ({nb.notebook_id}) headless={cfg.playwright.headless}")
    try:
        with NotebookLMClient(
            cdp_endpoint=cfg.playwright.cdp_endpoint,
            user_data_dir=cfg.playwright.user_data_dir,
            headless=cfg.playwright.headless,
            navigation_timeout_ms=cfg.playwright.navigation_timeout_ms,
            source_add_timeout_ms=cfg.playwright.source_add_timeout_ms,
            notebooklm_url=cfg.playwright.notebooklm_url,
        ) as c:
            sources = c.list_sources(nb.notebook_id)
        print(f"SESSION OK: navigated & read notebook. sources={len(sources)}")
        sys.exit(0)
    except SessionExpiredError as e:
        print(f"SESSION EXPIRED: {e}")
        sys.exit(2)
    except Exception as e:
        print(f"ERROR: {type(e).__name__}: {str(e)[:300]}")
        sys.exit(3)


if __name__ == "__main__":
    main()
