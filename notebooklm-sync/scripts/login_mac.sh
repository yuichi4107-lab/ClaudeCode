#!/usr/bin/env bash
# NotebookLM 初回ログイン（Mac・実Chrome・専用プロファイル）
#
# このスクリプトは sync.py が使う専用Chromeプロファイルで Google にログインするためのもの。
# ここでログインしておくと、以降 sync.py(launch_persistent_context, channel="chrome") が
# 同じプロファイルを再利用し、Cookie が自動更新されてセッションが長持ちする。
#
# 使い方:
#   1. 普段使いのChromeは開いたままでOK（このスクリプトは別プロファイルで起動する）
#   2. bash scripts/login_mac.sh
#   3. 開いたChromeで Google にログインし、NotebookLM が表示されることを確認
#   4. そのChromeウィンドウを閉じる（=ログイン情報がプロファイルに保存される）
set -euo pipefail

PROFILE="${NOTEBOOKLM_AUTH_DIR:-$HOME/notebooklm-sync/.auth/chromium}"
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

if [ ! -x "$CHROME" ]; then
  echo "ERROR: Google Chrome が見つかりません: $CHROME" >&2
  exit 1
fi

mkdir -p "$PROFILE"
echo "専用プロファイル: $PROFILE"
echo "Chrome を起動します。Google にログイン→NotebookLM 表示を確認→ウィンドウを閉じてください。"
"$CHROME" \
  --user-data-dir="$PROFILE" \
  --no-first-run \
  --no-default-browser-check \
  "https://notebooklm.google.com"
echo "ログインウィンドウが閉じられました。プロファイルを保存しました。"
