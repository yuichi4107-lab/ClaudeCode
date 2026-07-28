#!/usr/bin/env bash
set -euo pipefail

resolve_repo_root() {
  local script_dir
  script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
  local candidates=()
  [ -n "${RAKUTEN_ROOM_REPO_ROOT:-}" ] && candidates+=("$RAKUTEN_ROOM_REPO_ROOT")
  [ -n "${YNFACTORY_ROOT:-}" ] && candidates+=("$YNFACTORY_ROOT")
  candidates+=(
    "$script_dir/../.."
    "$(pwd)"
    "$HOME/Library/CloudStorage/GoogleDrive-yuichi4107@gmail.com/マイドライブ/YNFactory-cc"
    "$HOME/Library/CloudStorage/GoogleDrive-yuichi4107@gmail.com/マイドライブ/YNFactory-cc"
    "$HOME/YNFactory-cc"
  )
  local candidate
  for candidate in "${candidates[@]}"; do
    [ -n "$candidate" ] || continue
    if [ -d "$candidate/rakuten-room-auto/src/rakuten_room_auto" ]; then
      (cd "$candidate" && pwd -P)
      return 0
    fi
  done
  return 1
}

REPO_ROOT="$(resolve_repo_root)"
APP_ROOT="${RAKUTEN_ROOM_RUNTIME_ROOT:-$HOME/rakuten-room-auto}"
VENV="${RAKUTEN_ROOM_VENV:-$APP_ROOT/.venv}"
LOG_DIR="$APP_ROOT/logs"
CDP_PORT="${RAKUTEN_ROOM_CDP_PORT:-9225}"
mkdir -p "$LOG_DIR"

if ! lsof -nP -iTCP:"$CDP_PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  nohup "$REPO_ROOT/rakuten-room-auto/scripts/start_chrome_room.sh" \
    > "$LOG_DIR/chrome.log" 2>&1 &
  for _ in $(seq 1 20); do
    if lsof -nP -iTCP:"$CDP_PORT" -sTCP:LISTEN >/dev/null 2>&1; then
      break
    fi
    sleep 1
  done
fi

if [ ! -x "$VENV/bin/python" ]; then
  python3 -m venv "$VENV"
  "$VENV/bin/python" -m pip install -U pip
  "$VENV/bin/python" -m pip install -r "$REPO_ROOT/rakuten-room-auto/requirements.txt"
fi

export PYTHONPATH="$REPO_ROOT/rakuten-room-auto/src"
export RAKUTEN_ROOM_CONFIG="${RAKUTEN_ROOM_CONFIG:-$APP_ROOT/config.yaml}"

# シートを読み取り専用で1回確認し、認証・API障害時は変更処理の前に終了する。
"$VENV/bin/python" -m rakuten_room_auto preview --limit 1 >/dev/null

# 自動承認モード（既定ON）: 未投稿→承認征ち→承認済 まで自動で進めてから投稿する。
# 手動承認に戻すときは RAKUTEN_ROOM_AUTO_APPROVE=0 を設定する。
AUTO_APPROVE="${RAKUTEN_ROOM_AUTO_APPROVE:-1}"
PREPARE_LIMIT="${RAKUTEN_ROOM_PREPARE_LIMIT:-10}"
if [ "$AUTO_APPROVE" = "1" ]; then
  # 要確認行が混ざっていても投稿は続行するため、終了コードは無視する
  # replenish: 残りネタが閾値以下ならランキングから自動補充（config.yamlのreplenishで調整）
  "$VENV/bin/python" -m rakuten_room_auto replenish || true
  "$VENV/bin/python" -m rakuten_room_auto prepare --limit "$PREPARE_LIMIT" || true
  "$VENV/bin/python" -m rakuten_room_auto approve --limit "$PREPARE_LIMIT" || true
fi

exec "$VENV/bin/python" -m rakuten_room_auto run --limit "${RAKUTEN_ROOM_LIMIT:-1}"
