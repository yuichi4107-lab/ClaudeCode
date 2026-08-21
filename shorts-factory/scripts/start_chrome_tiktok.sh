#!/usr/bin/env bash
# TikTok投稿用 常駐Chrome起動（TikTok専用プロファイル + remote-debugging port 9224）。
set -euo pipefail

export SHORTS_AUTH_DIR="${SHORTS_AUTH_DIR:-$HOME/shorts-factory/.auth/tiktok-chrome}"
export SHORTS_CDP_PORT="${SHORTS_CDP_PORT:-9224}"

DIR="$(cd "$(dirname "$0")" && pwd)"
exec "$DIR/start_chrome_shorts.sh" "$@"
