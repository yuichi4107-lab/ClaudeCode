#!/usr/bin/env bash
# Shared environment helpers for shorts-factory shell entrypoints.

shorts_resolve_repo_root() {
  local script_dir
  script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"

  local candidates=()
  if [ -n "${SHORTS_REPO_ROOT:-}" ]; then
    candidates+=("$SHORTS_REPO_ROOT")
  fi
  if [ -n "${YNFACTORY_ROOT:-}" ]; then
    candidates+=("$YNFACTORY_ROOT")
  fi
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
    if [ -d "$candidate/shorts-factory/src" ]; then
      (cd "$candidate" && pwd -P)
      return 0
    fi
  done

  return 1
}

shorts_sync_app_from_repo() {
  local repo_root="$1"
  local app_dir="$2"
  local src="$repo_root/shorts-factory"
  local names=(src prompts assets scripts)

  mkdir -p "$app_dir"

  local rsync_err
  rsync_err="$(mktemp)"
  if rsync -a --delete \
      --exclude '.venv' --exclude 'work' --exclude 'logs' --exclude 'voicevox*' \
      "$src/src" "$src/prompts" "$src/assets" "$src/scripts" \
      "$app_dir/" 2>"$rsync_err"; then
    rm -f "$rsync_err"
    chmod +x "$app_dir"/scripts/*.sh 2>/dev/null || true
    return 0
  fi

  echo "[warn] rsync失敗。cpフォールバックで同期します: $(tail -2 "$rsync_err" | tr '\n' ' ')"
  rm -f "$rsync_err"

  local stage
  stage="$(mktemp -d "$app_dir/.sync.XXXXXX")"
  local name
  for name in "${names[@]}"; do
    if ! cp -R "$src/$name" "$stage/"; then
      rm -rf "$stage"
      return 1
    fi
  done
  for name in "${names[@]}"; do
    if ! rm -rf "$app_dir/$name"; then
      rm -rf "$stage"
      return 1
    fi
    if ! mv "$stage/$name" "$app_dir/$name"; then
      rm -rf "$stage"
      return 1
    fi
  done
  rmdir "$stage" 2>/dev/null || true
  chmod +x "$app_dir"/scripts/*.sh 2>/dev/null || true
}
