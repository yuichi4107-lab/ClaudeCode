#!/usr/bin/env bash
# launchdテンプレートをユーザーLaunchAgentsへ配置する補助スクリプト。
# 実行すると定期実行が有効になるため、公開投稿の明示承認後だけ使う。
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd -P)"
APP_PROJECT_DIR="$HOME/rakuten-room-auto/app/rakuten-room-auto"
LAUNCH_DIR="$HOME/Library/LaunchAgents"

mkdir -p "$LAUNCH_DIR"
mkdir -p "$(dirname "$APP_PROJECT_DIR")"
rsync -a --delete \
  --exclude '.venv' --exclude '__pycache__' --exclude '.pytest_cache' \
  "$PROJECT_DIR/" "$APP_PROJECT_DIR/"

names=(com.ynfactory.rakuten-room-post.plist)
if [ "${RAKUTEN_ROOM_INSTALL_CHROME_KEEPALIVE:-0}" = "1" ]; then
  names=(com.ynfactory.rakuten-room-chrome.plist com.ynfactory.rakuten-room-post.plist)
fi

for name in "${names[@]}"; do
  sed \
    -e "s#__HOME__#$HOME#g" \
    -e "s#__PROJECT_DIR__#$APP_PROJECT_DIR#g" \
    "$PROJECT_DIR/launchd/$name" > "$LAUNCH_DIR/$name"
  plutil -lint "$LAUNCH_DIR/$name"
  launchctl unload "$LAUNCH_DIR/$name" >/dev/null 2>&1 || true
  launchctl load "$LAUNCH_DIR/$name"
done

echo "[OK] Rakuten ROOM launchd jobs installed."
