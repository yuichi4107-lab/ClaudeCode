#!/usr/bin/env bash
# shorts-factory用 常駐Chrome起動（専用プロファイル + remote-debugging port 9223）。
# launchd(com.ynfactory.shorts-chrome) から KeepAlive で常時起動される。
# youtube_cdp.py はこのChromeへCDP接続して投稿する。
# TikTokは start_chrome_tiktok.sh で別プロファイル・別ポートを使う。
#
# notebooklm-sync の start_chrome_mac.sh と同パターン（ポートとプロファイルのみ別）。
#
# 環境変数:
#   SHORTS_AUTH_DIR   プロファイル（既定: ~/shorts-factory/.auth/chrome）
#   SHORTS_CDP_PORT   remote-debuggingポート（既定: 9223）
#   SHORTS_ENABLE_CDP 1ならremote-debuggingを有効化 / 0なら無効化（ログイン用）
#   SHORTS_HEADLESS   1ならheadless(--headless=new) / 0なら通常ウィンドウ（既定: 0）
set -euo pipefail

PROFILE="${SHORTS_AUTH_DIR:-$HOME/shorts-factory/.auth/chrome}"
PORT="${SHORTS_CDP_PORT:-9223}"
ENABLE_CDP="${SHORTS_ENABLE_CDP:-1}"
HEADLESS="${SHORTS_HEADLESS:-0}"
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

mkdir -p "$PROFILE"

ARGS=(
  --user-data-dir="$PROFILE"
  --no-first-run
  --no-default-browser-check
  --window-size=1400,1000
  --disable-features=Translate
  --disable-background-timer-throttling
  --disable-backgrounding-occluded-windows
)
if [ "$ENABLE_CDP" != "0" ]; then
  ARGS+=(--remote-debugging-port="$PORT")
fi
if [ "$HEADLESS" = "1" ]; then
  ARGS+=(--headless=new)
fi

TARGETS=("$@")
if [ "${#TARGETS[@]}" -eq 0 ]; then
  TARGETS=(about:blank)
fi

exec "$CHROME" "${ARGS[@]}" "${TARGETS[@]}"
