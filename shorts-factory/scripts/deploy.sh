#!/usr/bin/env bash
# shorts-factory のセットアップ/デプロイ。
#   ./deploy.sh          コードを ~/shorts-factory/app へ同期
#   ./deploy.sh install  launchd 4ジョブの登録まで実行
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
source "$SCRIPT_DIR/shorts_env.sh"

DRIVE_ROOT="$(shorts_resolve_repo_root)"
SRC="$DRIVE_ROOT/shorts-factory"
APP_DIR="$HOME/shorts-factory/app"
LA_DIR="$HOME/Library/LaunchAgents"

mkdir -p "$APP_DIR"
shorts_sync_app_from_repo "$DRIVE_ROOT" "$APP_DIR"
echo "✅ コード同期: $APP_DIR (repo=$DRIVE_ROOT)"

if [ "${1:-}" = "install" ]; then
  VENV_PY="$HOME/shorts-factory/.venv/bin/python"
  SHORTS_RUNTIME_DIR="$HOME/shorts-factory" \
    SHORTS_FACTORY_ROOT="$APP_DIR" \
    "$VENV_PY" "$APP_DIR/scripts/migrate_runtime_state.py" \
      --source-marketing "$DRIVE_ROOT/.company/marketing/shorts-factory"
  SHORTS_RUNTIME_DIR="$HOME/shorts-factory" \
    SHORTS_FACTORY_ROOT="$APP_DIR" \
    "$VENV_PY" "$APP_DIR/scripts/sync_runtime_credentials.py" \
      --source "$DRIVE_ROOT/.company/engineering/sns-credentials/.env"

  for p in shorts-generate shorts-approval shorts-chrome shorts-tiktok-chrome shorts-drive-mirror; do
    cp "$SRC/launchd/com.ynfactory.$p.plist" "$LA_DIR/"
    launchctl bootout "gui/$(id -u)/com.ynfactory.$p" 2>/dev/null || true
    launchctl bootstrap "gui/$(id -u)" "$LA_DIR/com.ynfactory.$p.plist"
    echo "✅ launchd登録: com.ynfactory.$p"
  done
  echo "確認: launchctl list | grep ynfactory.shorts"
fi
