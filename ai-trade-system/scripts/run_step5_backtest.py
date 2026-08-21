"""
工程5 メインスクリプト: OHLCV 取得 → バックテスト実行 → レポート出力

実行方法:
    python scripts/run_step5_backtest.py

成功条件:
    1. USD/JPY 過去1年分 OHLCV が Saxo API 経由で取得できる
    2. データが data/fx/ohlcv/ 配下に保存されている
    3. バックテストが完走する（エラーで途中停止しない）
    4. 結果レポートが出力され、主要指標（勝率、PnL、DD）が含まれている
    5. 既存 BTC/JPY システムへの影響なし
"""

import json
import logging
import os
import sys
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "src"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


def check_existing_btc_system():
    """既存 BTC/JPY システムへの影響確認（ファイル存在チェック）。"""
    btc_files = [
        os.path.join(PROJECT_ROOT, "data", "ohlcv", "BTC-USDT_1d_1000.json"),
        os.path.join(PROJECT_ROOT, "src", "backtest", "strategy_config.json"),
        os.path.join(PROJECT_ROOT, "src", "trading", "trader.py"),
    ]
    print("\n既存 BTC/JPY システム 影響確認:")
    all_ok = True
    for fp in btc_files:
        exists = os.path.exists(fp)
        status = "OK" if exists else "MISSING"
        print(f"  [{status}] {os.path.relpath(fp, PROJECT_ROOT)}")
        if not exists:
            all_ok = False
    return all_ok


def main():
    print("=" * 60)
    print("  工程5: FX バックテスト動作確認")
    print(f"  実行時刻: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    # Step 0: 既存システム影響確認
    btc_ok = check_existing_btc_system()
    if not btc_ok:
        print("[WARN] 既存ファイルの一部が見つかりません（処理は続行）")

    # Step 1: OHLCV 取得
    print("\n" + "─" * 60)
    print("  Step 1: USD/JPY OHLCV データ取得")
    print("─" * 60)

    import subprocess
    result1 = subprocess.run(
        [sys.executable, os.path.join(SCRIPT_DIR, "fetch_fx_ohlcv.py"),
         "--symbol", "USD/JPY", "--timeframe", "1d", "--limit", "400",
         "--exchange", "saxo_sim"],
        capture_output=False,
        text=True,
    )

    if result1.returncode != 0:
        print(f"\n[FATAL] OHLCV 取得が失敗しました（終了コード: {result1.returncode}）")
        print("原因: Token 失効またはネットワークエラーの可能性があります。")
        print("対処: .env の SAXO_SIM_TOKEN を再取得して更新してください。")
        sys.exit(1)

    # データ存在確認
    ohlcv_path = os.path.join(PROJECT_ROOT, "data", "fx", "ohlcv", "USDJPY_1d.json")
    if not os.path.exists(ohlcv_path):
        print(f"\n[FATAL] OHLCVファイルが生成されていません: {ohlcv_path}")
        sys.exit(1)

    with open(ohlcv_path, "r", encoding="utf-8") as f:
        candles = json.load(f)
    print(f"\nStep 1 完了: {len(candles)}本取得")

    # Step 2: バックテスト実行
    print("\n" + "─" * 60)
    print("  Step 2: バックテスト実行")
    print("─" * 60)

    result2 = subprocess.run(
        [sys.executable, os.path.join(SCRIPT_DIR, "run_fx_backtest.py"),
         "--symbol", "USD-JPY", "--strategy", "all",
         "--exchange", "saxo_sim"],
        capture_output=False,
        text=True,
    )

    if result2.returncode != 0:
        print(f"\n[FATAL] バックテストが失敗しました（終了コード: {result2.returncode}）")
        sys.exit(1)

    # レポート存在確認
    report_path = os.path.join(PROJECT_ROOT, "data", "fx", "backtest_report_USDJPY_1year.md")
    if os.path.exists(report_path):
        print(f"\nStep 2 完了: レポート出力 → {report_path}")
    else:
        print(f"\n[WARN] レポートファイルが見つかりません: {report_path}")

    # Step 3: 最終確認サマリー
    print("\n" + "=" * 60)
    print("  工程5 完了サマリー")
    print("=" * 60)

    checks = [
        ("OHLCV 取得", os.path.exists(ohlcv_path)),
        ("レポート出力", os.path.exists(report_path)),
        ("既存 BTC/JPY 影響なし", btc_ok),
    ]

    all_pass = True
    for name, ok in checks:
        status = "PASS" if ok else "FAIL"
        print(f"  [{status}] {name}")
        if not ok:
            all_pass = False

    if all_pass:
        print("\n  全チェック PASS - 工程5 完了")
    else:
        print("\n  一部チェック FAIL - 要確認")
        sys.exit(1)


if __name__ == "__main__":
    main()
