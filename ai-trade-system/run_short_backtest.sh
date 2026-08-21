#!/bin/bash
# ショートバックテスト一括実行スクリプト
# 作業ディレクトリ: ai-trade-system/
set -a
source "$(dirname "$0")/.env"
set +a

BASE_DIR="$(dirname "$0")"
RESULT_LOG="$BASE_DIR/short_backtest_results.log"
SUMMARY_FILE="$BASE_DIR/short_backtest_summary.json"

echo "=== ショートバックテスト開始: $(date) ===" | tee "$RESULT_LOG"
echo "" | tee -a "$RESULT_LOG"

# 結果を格納する配列
declare -a CASE_RESULTS

run_case() {
    local case_num="$1"
    local currency="$2"
    local pattern="$3"
    local data_file="$4"

    echo "=== Case $case_num: $currency $pattern ===" | tee -a "$RESULT_LOG"
    echo "開始時刻: $(date)" | tee -a "$RESULT_LOG"

    # runner.py実行
    output=$(python -u "$BASE_DIR/src/backtest/runner.py" "$BASE_DIR/$data_file" \
        --pattern "$pattern" \
        --direction short \
        --window 50 \
        --step 5 \
        --hold 20 \
        --delay 1.0 2>&1)

    echo "$output" | tee -a "$RESULT_LOG"

    # result.jsonのパスを抽出
    result_json=$(echo "$output" | grep -o 'results/backtest_[0-9_]*/result\.json' | tail -1)
    if [ -z "$result_json" ]; then
        # 別のパターンで探す
        result_dir=$(echo "$output" | grep -o 'backtest_[0-9_]*' | tail -1)
        if [ -n "$result_dir" ]; then
            result_json="$BASE_DIR/results/$result_dir/result.json"
        fi
    else
        result_json="$BASE_DIR/$result_json"
    fi

    echo "result.json: $result_json" | tee -a "$RESULT_LOG"

    # シグナル数を抽出
    signal_count=$(echo "$output" | grep -o '[0-9]* signals detected' | grep -o '[0-9]*' | head -1)
    if [ -z "$signal_count" ]; then
        signal_count=$(echo "$output" | grep "Detected:" | grep -o '[0-9]*' | head -1)
    fi

    echo "シグナル数: $signal_count" | tee -a "$RESULT_LOG"
    echo "Case $case_num 完了: $(date)" | tee -a "$RESULT_LOG"
    echo "---" | tee -a "$RESULT_LOG"

    # result.jsonのパスを返す（グローバル変数に格納）
    eval "RESULT_JSON_${case_num}='$result_json'"
}

run_optimizer() {
    local case_num="$1"
    local currency="$2"
    local pattern="$3"
    local result_json="$4"

    echo "=== Optimizer Case $case_num: $currency $pattern ===" | tee -a "$RESULT_LOG"

    if [ ! -f "$result_json" ]; then
        echo "ERROR: result.json not found: $result_json" | tee -a "$RESULT_LOG"
        return 1
    fi

    output=$(python -u "$BASE_DIR/src/backtest/optimizer.py" "$result_json" \
        --extended --max-dd 30 2>&1)

    echo "$output" | tee -a "$RESULT_LOG"
    echo "Optimizer Case $case_num 完了: $(date)" | tee -a "$RESULT_LOG"
    echo "---" | tee -a "$RESULT_LOG"
}

# Phase A: 全12ケースのrunner.py実行
echo "========================================" | tee -a "$RESULT_LOG"
echo "Phase A: Gemini判定バックテスト" | tee -a "$RESULT_LOG"
echo "========================================" | tee -a "$RESULT_LOG"

run_case 1 "BTC-USDT" "double_top" "data/ohlcv/BTC-USDT_1d_1000.json"
run_case 2 "BTC-USDT" "rsi_overbought_reversal" "data/ohlcv/BTC-USDT_1d_1000.json"
run_case 3 "BTC-USDT" "rally_top" "data/ohlcv/BTC-USDT_1d_1000.json"
run_case 4 "ETH-USDT" "double_top" "data/ohlcv/ETH-USDT_1d_1000.json"
run_case 5 "ETH-USDT" "rsi_overbought_reversal" "data/ohlcv/ETH-USDT_1d_1000.json"
run_case 6 "ETH-USDT" "rally_top" "data/ohlcv/ETH-USDT_1d_1000.json"
run_case 7 "SOL-USDT" "double_top" "data/ohlcv/SOL-USDT_1d_1000.json"
run_case 8 "SOL-USDT" "rsi_overbought_reversal" "data/ohlcv/SOL-USDT_1d_1000.json"
run_case 9 "SOL-USDT" "rally_top" "data/ohlcv/SOL-USDT_1d_1000.json"
run_case 10 "XRP-USDT" "double_top" "data/ohlcv/XRP-USDT_1d_1000.json"
run_case 11 "XRP-USDT" "rsi_overbought_reversal" "data/ohlcv/XRP-USDT_1d_1000.json"
run_case 12 "XRP-USDT" "rally_top" "data/ohlcv/XRP-USDT_1d_1000.json"

echo "Phase A 完了: $(date)" | tee -a "$RESULT_LOG"
echo "" | tee -a "$RESULT_LOG"

# Phase B: オプティマイザー実行
echo "========================================" | tee -a "$RESULT_LOG"
echo "Phase B: TP/SL最適化" | tee -a "$RESULT_LOG"
echo "========================================" | tee -a "$RESULT_LOG"

# 各ケースのresult.jsonを収集して最適化
for case_num in 1 2 3 4 5 6 7 8 9 10 11 12; do
    varname="RESULT_JSON_${case_num}"
    result_json="${!varname}"
    echo "Case $case_num result.json: $result_json"

    case $case_num in
        1) run_optimizer $case_num "BTC-USDT" "double_top" "$result_json" ;;
        2) run_optimizer $case_num "BTC-USDT" "rsi_overbought_reversal" "$result_json" ;;
        3) run_optimizer $case_num "BTC-USDT" "rally_top" "$result_json" ;;
        4) run_optimizer $case_num "ETH-USDT" "double_top" "$result_json" ;;
        5) run_optimizer $case_num "ETH-USDT" "rsi_overbought_reversal" "$result_json" ;;
        6) run_optimizer $case_num "ETH-USDT" "rally_top" "$result_json" ;;
        7) run_optimizer $case_num "SOL-USDT" "double_top" "$result_json" ;;
        8) run_optimizer $case_num "SOL-USDT" "rsi_overbought_reversal" "$result_json" ;;
        9) run_optimizer $case_num "SOL-USDT" "rally_top" "$result_json" ;;
        10) run_optimizer $case_num "XRP-USDT" "double_top" "$result_json" ;;
        11) run_optimizer $case_num "XRP-USDT" "rsi_overbought_reversal" "$result_json" ;;
        12) run_optimizer $case_num "XRP-USDT" "rally_top" "$result_json" ;;
    esac
done

echo "========================================" | tee -a "$RESULT_LOG"
echo "全12ケース完了: $(date)" | tee -a "$RESULT_LOG"
echo "========================================" | tee -a "$RESULT_LOG"
