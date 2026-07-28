#!/usr/bin/env bash
# NotebookLM用 常駐Chrome起動（専用プロファイル + remote-debugging）。
# launchd(com.ynfactory.notebooklm-chrome) から KeepAlive で常時起動される。
# sync.py はこのChromeへ http://localhost:<port> でCDP接続する。
#
# 環境変数:
#   NOTEBOOKLM_AUTH_DIR  プロファイルディレクトリ（既定: ~/notebooklm-sync/.auth/chromium）
#   NOTEBOOKLM_CDP_PORT  remote-debuggingポート（既定: 9222）
#   NOTEBOOKLM_HEADLESS  1ならheadless(--headless=new) / 0なら通常ウィンドウ（既定: 0）
set -euo pipefail

PROFILE="${NOTEBOOKLM_AUTH_DIR:-$HOME/notebooklm-sync/.auth/chromium}"
PORT="${NOTEBOOKLM_CDP_PORT:-9222}"
HEADLESS="${NOTEBOOKLM_HEADLESS:-0}"
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

mkdir -p "$PROFILE"

ARGS=(
  --user-data-dir="$PROFILE"
  --remote-debugging-port="$PORT"
  --no-first-run
  --no-default-browser-check
  --window-size=1600,1000
  --disable-features=Translate
  --disable-background-timer-throttling
  --disable-backgrounding-occluded-windows
)
if [ "$HEADLESS" = "1" ]; then
  ARGS+=(--headless=new)
fi

# launchdが直接Chromeプロセスを監視できるよう exec で起動（終了するとKeepAliveで再起動）
exec "$CHROME" "${ARGS[@]}" "https://notebooklm.google.com"
