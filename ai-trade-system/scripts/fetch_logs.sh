#!/bin/bash
# VPS から forward テストのログをローカルに scp で取得するスクリプト
#
# 使い方:
#   ./scripts/fetch_logs.sh           # 本日分のログを取得
#   ./scripts/fetch_logs.sh 20260413  # 指定日付 (YYYYMMDD) のログを取得
#   ./scripts/fetch_logs.sh all       # logs/forward/ 配下を全件取得

set -e

# ─── VPS 接続情報 ───
VPS_HOST="tools.ynfactory.online"
VPS_USER="root"
REMOTE_LOG_DIR="/opt/ai-trade-system/logs/forward"

# ─── ローカル保存先 ───
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOCAL_LOG_DIR="${SCRIPT_DIR}/../logs/forward"

mkdir -p "${LOCAL_LOG_DIR}"

# ─── 引数処理 ───
DATE_ARG="${1:-}"

if [ -z "${DATE_ARG}" ]; then
    # 引数なし: 本日の日付 (YYYYMMDD)
    TARGET_DATE="$(date +%Y%m%d)"
elif [ "${DATE_ARG}" = "all" ]; then
    # 全件取得
    TARGET_DATE="all"
else
    TARGET_DATE="${DATE_ARG}"
fi

echo "=== fetch_logs.sh ==="
echo "  VPS:   ${VPS_USER}@${VPS_HOST}"
echo "  リモート: ${REMOTE_LOG_DIR}"
echo "  ローカル: ${LOCAL_LOG_DIR}"

if [ "${TARGET_DATE}" = "all" ]; then
    echo "  対象: 全ファイル"
    echo ""
    scp -r "${VPS_USER}@${VPS_HOST}:${REMOTE_LOG_DIR}/." "${LOCAL_LOG_DIR}/"
    echo "  完了: 全ログを取得しました"
else
    echo "  対象日付: ${TARGET_DATE}"
    echo ""

    # signals_{DATE}.jsonl
    SIGNALS_FILE="signals_${TARGET_DATE}.jsonl"
    echo "  取得: ${SIGNALS_FILE}"
    scp "${VPS_USER}@${VPS_HOST}:${REMOTE_LOG_DIR}/${SIGNALS_FILE}" \
        "${LOCAL_LOG_DIR}/${SIGNALS_FILE}" 2>/dev/null \
        && echo "    -> 保存: ${LOCAL_LOG_DIR}/${SIGNALS_FILE}" \
        || echo "    -> SKIP: ${SIGNALS_FILE} が VPS に存在しません"

    # alert.log (常時取得)
    echo "  取得: alert.log"
    scp "${VPS_USER}@${VPS_HOST}:${REMOTE_LOG_DIR}/alert.log" \
        "${LOCAL_LOG_DIR}/alert.log" 2>/dev/null \
        && echo "    -> 保存: ${LOCAL_LOG_DIR}/alert.log" \
        || echo "    -> SKIP: alert.log が VPS に存在しません"
fi

echo ""
echo "=== 完了 ==="
