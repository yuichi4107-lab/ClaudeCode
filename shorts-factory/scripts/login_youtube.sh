#!/usr/bin/env bash
# YouTube初回ログイン用（可視Chromeを専用プロファイルで開く）。
# 手順:
#   1. launchctl unload ~/Library/LaunchAgents/com.ynfactory.shorts-chrome.plist 2>/dev/null
#   2. ./login_youtube.sh   ← Chromeが開くので Google ログイン → YouTube Studio が見えればOK
#   3. Chromeを閉じて launchctl load ~/Library/LaunchAgents/com.ynfactory.shorts-chrome.plist
set -euo pipefail
export SHORTS_HEADLESS=0
DIR="$(cd "$(dirname "$0")" && pwd)"
echo "Chromeが開きます。Googleアカウントにログインし、https://studio.youtube.com が開ければ完了です。"
echo "TikTokは scripts/login_tiktok.sh の別プロファイルでログインしてください。"
exec "$DIR/start_chrome_shorts.sh" "https://studio.youtube.com"
