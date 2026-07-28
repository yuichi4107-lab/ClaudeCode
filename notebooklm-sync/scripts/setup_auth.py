"""ローカル実行用: ユーザーが普通に起動した Chrome に CDP 接続し、storage_state.json を取得する。

【背景】
Playwright が起動する Chromium は Google から自動化ブラウザとして検出され、
ログインがブロックされる（「ログインできませんでした」）。
そのため、ユーザーが Chrome を `--remote-debugging-port=9222` 付きで起動し、
そのChromeで普通にGoogleログイン → このスクリプトでCDP接続して storage_state を抜き出す方式にする。

【手順】
1. すべてのChromeウィンドウを閉じる
2. PowerShellで scripts/start_chrome_for_auth.ps1 を実行（専用プロファイルでChrome起動）
3. 開いたChromeで普通にGoogleにログインしてNotebookLMを開く
4. ノートブックを2冊作成（手順案内参照）
5. 別のターミナルで本スクリプトを実行 → storage_state.json が保存される
"""

import json
import sys
import urllib.request
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
SRC_DIR = THIS_DIR.parent / "src"
sys.path.insert(0, str(SRC_DIR))

from config import load_config

from playwright.sync_api import sync_playwright

CDP_URL = "http://127.0.0.1:9222"


def cdp_alive() -> bool:
    try:
        with urllib.request.urlopen(f"{CDP_URL}/json/version", timeout=2) as r:
            return r.status == 200
    except Exception:
        return False


def main() -> int:
    cfg_path = THIS_DIR.parent / "config.yaml"
    cfg = load_config(str(cfg_path))

    auth_dir = Path(cfg.playwright.user_data_dir)
    if not auth_dir.is_absolute():
        auth_dir = THIS_DIR.parent / auth_dir
    auth_dir.mkdir(parents=True, exist_ok=True)
    storage_state_path = auth_dir / "storage_state.json"

    if not cdp_alive():
        print(f"[ERROR] No Chrome with CDP on {CDP_URL}.")
        print("[ACTION] First, run scripts/start_chrome_for_auth.ps1, then sign in to Google in that Chrome.")
        return 1

    print(f"[INFO] Connecting to Chrome via CDP at {CDP_URL}")
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(CDP_URL)
        if not browser.contexts:
            print("[ERROR] Chrome has no browser contexts. Open a tab in Chrome and retry.")
            return 1
        context = browser.contexts[0]
        pages_info = []
        for page in context.pages:
            try:
                pages_info.append(page.url)
            except Exception:
                pass
        print(f"[INFO] Open pages in Chrome: {pages_info}")
        if not any("notebooklm.google.com" in u for u in pages_info):
            print("[WARN] No NotebookLM tab found. Make sure you are signed in and have NotebookLM open in Chrome.")
        storage_state = context.storage_state()
        cookies = storage_state.get("cookies", [])
        origins = storage_state.get("origins", [])
        print(f"[INFO] Captured {len(cookies)} cookies across {len(origins)} origins")
        storage_state_path.write_text(json.dumps(storage_state, ensure_ascii=False, indent=2))

    print(f"[OK] storage_state saved: {storage_state_path}")
    print("[NEXT] Tell the assistant 'ログイン完了' so it transfers storage_state to the VPS.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
