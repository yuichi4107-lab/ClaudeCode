#!/usr/bin/env bash
# TikTok初回ログイン用（可視ChromeをTikTok専用プロファイルで開く）。
# 手順:
#   1. launchctl unload ~/Library/LaunchAgents/com.ynfactory.shorts-tiktok-chrome.plist 2>/dev/null
#   2. ./login_tiktok.sh   ← Chromeが開くので TikTok ログイン
#   3. Chromeを閉じて launchctl load ~/Library/LaunchAgents/com.ynfactory.shorts-tiktok-chrome.plist
set -euo pipefail
export SHORTS_HEADLESS=0
export SHORTS_ENABLE_CDP=0
export SHORTS_AUTH_DIR="${SHORTS_AUTH_DIR:-$HOME/shorts-factory/.auth/tiktok-chrome}"
export SHORTS_CDP_PORT="${SHORTS_CDP_PORT:-9224}"
DIR="$(cd "$(dirname "$0")" && pwd)"
echo "CDPなしのTikTok専用Chromeが開きます。TikTokにログインし、アップロード画面が見えれば完了です。"
echo "ログイン後はChromeを閉じ、com.ynfactory.shorts-tiktok-chrome を再起動してください。"
exec "$DIR/start_chrome_shorts.sh" "https://www.tiktok.com/tiktokstudio/upload?from=upload"
