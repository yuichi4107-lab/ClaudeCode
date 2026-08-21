#!/bin/bash
# /opt/keiba-unified/keiba-ai-system/scripts/run_banei.sh
# 使い方: run_banei.sh <first|second|collect> <expected_race_type>
#   first         = 前半（1R〜5R）予想
#   second        = 後半（6R〜12R）予想
#   collect       = 結果収集
#   expected_race_type = nighter / semi_nighter / twilight（省略時はチェックしない）

set -e
cd /opt/keiba-unified/keiba-ai-system
export PYTHONPATH=.

HALF="${1:-first}"
EXPECTED_TYPE="${2:-}"
TODAY=$(date +%Y-%m-%d)
LOGPREFIX="[$(date '+%Y-%m-%d %H:%M:%S')]"

echo "$LOGPREFIX run_banei.sh HALF=$HALF EXPECTED_TYPE=$EXPECTED_TYPE DATE=$TODAY"

# --- 開催日・race_type確認 ---
ACTUAL_TYPE=$(./venv/bin/python - <<'PYEOF'
import sys
sys.path.insert(0, '.')
from scripts.check_race_day import get_race_type
from datetime import date
import os
t = get_race_type(date.today())
print(t or '')
PYEOF
)

if [ -z "$ACTUAL_TYPE" ]; then
    echo "$LOGPREFIX $TODAY 非開催日のためスキップ"
    exit 0
fi

echo "$LOGPREFIX 開催種別: $ACTUAL_TYPE"

# expected_race_typeが指定されている場合は一致確認
if [ -n "$EXPECTED_TYPE" ] && [ "$ACTUAL_TYPE" != "$EXPECTED_TYPE" ]; then
    echo "$LOGPREFIX $TODAY は $ACTUAL_TYPE、期待=$EXPECTED_TYPE のためスキップ"
    exit 0
fi

# --- 実行 ---
case "$HALF" in
    first)
        echo "$LOGPREFIX 前半予想（1R〜5R）開始"
        ./venv/bin/python scripts/daily_predict.py --date "$TODAY" --race-from 1 --race-to 5
        ;;
    second)
        echo "$LOGPREFIX 後半予想（6R〜12R）開始"
        ./venv/bin/python scripts/daily_predict.py --date "$TODAY" --race-from 6 --race-to 12
        ;;
    collect)
        echo "$LOGPREFIX 結果収集開始"
        ./venv/bin/python scripts/collect_results.py --date "$TODAY"
        ;;
    *)
        echo "$LOGPREFIX エラー: 不明なhalf指定: $HALF"
        exit 1
        ;;
esac

echo "$LOGPREFIX $HALF 完了"
