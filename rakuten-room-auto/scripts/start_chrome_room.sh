#!/usr/bin/env bash
# Rakuten ROOM用 常駐Chrome起動（専用プロファイル + remote-debugging）。
set -euo pipefail

PROFILE="${RAKUTEN_ROOM_AUTH_DIR:-$HOME/rakuten-room-auto/.auth/chrome}"
PORT="${RAKUTEN_ROOM_CDP_PORT:-9225}"
HEADLESS="${RAKUTEN_ROOM_HEADLESS:-0}"
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
USE_OPEN="${RAKUTEN_ROOM_USE_OPEN:-1}"

mkdir -p "$PROFILE"

ARGS=(
  --user-data-dir="$PROFILE"
  --remote-debugging-port="$PORT"
  --no-first-run
  --no-default-browser-check
  --window-size=1400,1000
  --disable-features=Translate
  --disable-background-timer-throttling
  --disable-backgrounding-occluded-windows
)
if [ "$HEADLESS" = "1" ]; then
  ARGS+=(--headless=new)
fi

TARGETS=("$@")
if [ "${#TARGETS[@]}" -eq 0 ]; then
  TARGETS=("https://room.rakuten.co.jp/")
fi

if [ "$USE_OPEN" = "1" ]; then
  exec /usr/bin/open -W -na "Google Chrome" --args "${ARGS[@]}" "${TARGETS[@]}"
fi

exec "$CHROME" "${ARGS[@]}" "${TARGETS[@]}"
