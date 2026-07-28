#!/bin/bash
# Saxo Sim PAT (Personal Access Token) を VPS の .env に反映してコンテナを再作成する。
# Saxo PAT は 24h 失効のため毎日実行する想定。
#
# 使い方:
#   bash scripts/update_saxo_token.sh <NEW_TOKEN>
#
# 動作:
#   1) /opt/ai-trade-system/.env の SAXO_SIM_TOKEN= 行のみ sed で置換
#   2) 置換後の行数とトークン文字数を表示（値そのものは出力しない）
#   3) docker compose up -d --force-recreate ai-trade-forward
#   4) 起動後 30 秒ログを観察し 401/200 を判定

set -euo pipefail

TOKEN="${1:-}"
if [[ -z "$TOKEN" ]]; then
  echo "ERROR: token argument required" >&2
  echo "usage: bash scripts/update_saxo_token.sh <token>" >&2
  exit 2
fi

# トークン形式の最低限チェック（JWT-like: 3 parts separated by .）
if ! [[ "$TOKEN" =~ ^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$ ]]; then
  echo "ERROR: token does not look like a JWT (3 dot-separated parts)" >&2
  exit 2
fi

echo "[1/4] Updating SAXO_SIM_TOKEN in /opt/ai-trade-system/.env ..."
ssh conoha "cd /opt/ai-trade-system && sed -i 's|^SAXO_SIM_TOKEN=.*|SAXO_SIM_TOKEN=${TOKEN}|' .env"

echo "[2/4] Verifying line count + token length (value not displayed) ..."
ssh conoha "cd /opt/ai-trade-system && grep -c '^SAXO_SIM_TOKEN=' .env && awk -F= '/^SAXO_SIM_TOKEN=/{print \"token_chars:\"length(\$2)}' .env"

echo "[3/4] Recreating container ai-trade-forward ..."
ssh conoha "cd /opt/ai-trade-system && docker compose up -d --force-recreate ai-trade-forward"

echo "[4/4] Waiting 30s then checking last 20 log lines for 401/200 ..."
sleep 30
ssh conoha "docker logs ai-trade-forward --tail 30 2>&1 | grep -E 'HTTP/1.1 (200|401)|Insufficient|シグナル' | tail -20"

echo "DONE."
