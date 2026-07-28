#!/usr/bin/env bash
# 日次の動画生成エントリポイント（launchd com.ynfactory.shorts-generate から呼ばれる）。
# デプロイ済みのローカルappを実行する。Drive同期は実行ホットパスに入れない。
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
if [ -d "$HOME/.nvm/versions/node" ]; then
  NODE_BIN="$(find "$HOME/.nvm/versions/node" -maxdepth 2 -type d -name bin 2>/dev/null | sort -V | tail -1)"
  if [ -n "$NODE_BIN" ]; then
    export PATH="$NODE_BIN:$PATH"
  fi
fi

APP_DIR="$HOME/shorts-factory/app"
VENV_PY="$HOME/shorts-factory/.venv/bin/python"

if [ ! -f "$APP_DIR/src/pipeline.py" ]; then
  echo "[error] runtime appがありません。先に shorts-factory/scripts/deploy.sh を実行してください" >&2
  exit 1
fi

cd "$APP_DIR"
export SHORTS_FACTORY_ROOT="$APP_DIR"
export PYTHONDONTWRITEBYTECODE=1
exec "$VENV_PY" -m src.pipeline "$@"
