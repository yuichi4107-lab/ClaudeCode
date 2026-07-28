"""
簡易動作確認スクリプト — 5戦略全てでサンプルデータのシグナル生成確認

実行方法:
    python scripts/verify_strategies.py

確認内容:
    1. 各戦略がインポートできること
    2. 実データ（USDJPY_1h.csv）でシグナルが生成できること
    3. フィルターON/OFFで動作すること
    4. DEFAULT_PARAMSで動作すること
"""

from __future__ import annotations

import logging
import os
import sys
import time

import pandas as pd

# プロジェクトルートをパスに追加
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, PROJECT_ROOT)

from src.backtest.strategies import (
    list_strategies,
    load_strategy,
    generate_signals,
    get_default_params,
)

logging.basicConfig(
    level=logging.WARNING,  # verifyスクリプトはINFO以上を表示
    format="%(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)


DATA_DIR = os.path.join(PROJECT_ROOT, "data", "fx", "ohlcv")
SAMPLE_FILE = os.path.join(DATA_DIR, "USDJPY_1h.csv")


def load_sample_data() -> pd.DataFrame:
    """USDJPY_1h.csvからサンプルデータを読み込む。"""
    if not os.path.exists(SAMPLE_FILE):
        print(f"[WARN] Sample file not found: {SAMPLE_FILE}")
        print("       Generating synthetic data instead...")
        return _make_synthetic_data()

    df = pd.read_csv(SAMPLE_FILE)
    df["datetime"] = pd.to_datetime(df["datetime"])
    print(f"[INFO] Loaded real data: {SAMPLE_FILE} ({len(df)} rows)")
    return df


def _make_synthetic_data(n: int = 1000) -> pd.DataFrame:
    """実データが存在しない場合の合成データ生成。"""
    import numpy as np

    rng = np.random.default_rng(42)
    dt = pd.date_range("2024-01-01", periods=n, freq="1h")
    close = 150.0 + np.cumsum(rng.normal(0, 0.3, n))
    noise = rng.uniform(0, 0.2, n)
    open_ = close - rng.uniform(-0.1, 0.1, n)
    high = np.maximum(close, open_) + noise
    low = np.minimum(close, open_) - noise
    high = np.maximum(high, np.maximum(close, open_))
    low = np.minimum(low, np.minimum(close, open_))

    return pd.DataFrame({
        "timestamp": (dt.astype("int64") // 10**6),
        "datetime": dt,
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": [0] * n,
    })


def verify_strategy(
    strategy_id: str,
    df: pd.DataFrame,
    verbose: bool = True,
) -> dict:
    """
    単一戦略の動作確認を実施する。

    Args:
        strategy_id: 戦略ID
        df: OHLCVデータ
        verbose: 詳細出力フラグ

    Returns:
        dict: 確認結果
    """
    result = {
        "strategy_id": strategy_id,
        "load_ok": False,
        "baseline_signals": 0,
        "filtered_signals": 0,
        "error": None,
        "elapsed_sec": 0.0,
    }

    try:
        t0 = time.time()

        # 戦略ロード確認
        strategy = load_strategy(strategy_id)
        result["load_ok"] = True

        params = get_default_params(strategy_id)

        # ベースライン（フィルターなし）
        baseline_df = generate_signals(strategy_id, df, params=params, filters={})
        baseline_count = int((baseline_df["signal"] != 0).sum())
        long_count = int((baseline_df["signal"] == 1).sum())
        short_count = int((baseline_df["signal"] == -1).sum())
        result["baseline_signals"] = baseline_count

        # フィルター強化版
        all_filters = {
            "use_sma200": True,
            "use_atr": True,
            "use_session": True,
            "use_event": True,
            "use_ema": True,
        }
        filtered_df = generate_signals(strategy_id, df, params=params, filters=all_filters)
        filtered_count = int((filtered_df["signal"] != 0).sum())
        result["filtered_signals"] = filtered_count

        elapsed = time.time() - t0
        result["elapsed_sec"] = round(elapsed, 2)

        if verbose:
            print(f"\n  [{strategy_id}]")
            print(f"    Strategy loaded  : OK")
            print(f"    Baseline signals : {baseline_count} (long={long_count}, short={short_count})")
            print(f"    Filtered signals : {filtered_count}")
            print(f"    Elapsed          : {elapsed:.2f}s")

            # signalが0のみの場合は警告
            if baseline_count == 0:
                print(f"    [WARN] No signals generated in baseline mode!")
            else:
                print(f"    [OK]  Signals generated successfully")

    except Exception as exc:
        result["error"] = str(exc)
        if verbose:
            print(f"  [{strategy_id}] ERROR: {exc}")

    return result


def run_verification() -> None:
    """全5戦略の動作確認を実行する。"""
    print("=" * 60)
    print("  FX Strategy Verification")
    print("=" * 60)

    # データ読み込み
    df = load_sample_data()
    print(f"[INFO] Data range: {df['datetime'].min()} ~ {df['datetime'].max()}")
    print(f"[INFO] Total rows: {len(df)}")

    strategies = list_strategies()
    print(f"\n[INFO] Strategies to verify: {strategies}")
    print("-" * 60)

    results = []
    for sid in strategies:
        r = verify_strategy(sid, df)
        results.append(r)

    # サマリー
    print("\n" + "=" * 60)
    print("  Summary")
    print("=" * 60)
    print(f"{'Strategy':<25} {'Load':>6} {'Baseline':>10} {'Filtered':>10} {'Time':>8} {'Status':>8}")
    print("-" * 70)

    all_ok = True
    for r in results:
        status = "OK" if r["load_ok"] and r["error"] is None else "FAIL"
        if status == "FAIL":
            all_ok = False
        print(
            f"  {r['strategy_id']:<23} {'OK' if r['load_ok'] else 'FAIL':>6}"
            f"  {r['baseline_signals']:>8}  {r['filtered_signals']:>8}"
            f"  {r['elapsed_sec']:>6.2f}s  {status:>6}"
        )
        if r["error"]:
            print(f"    -> Error: {r['error']}")

    print("-" * 70)
    print(f"\n[{'PASS' if all_ok else 'FAIL'}] All strategies verified: {'OK' if all_ok else 'SOME FAILURES'}")

    if all_ok:
        print("\n工程4（パラメータ最適化）に進む準備が完了しました。")
        print("次のステップ: python scripts/run_optimization.py")
    else:
        print("\nエラーが発生した戦略があります。ログを確認してください。")

    return results


if __name__ == "__main__":
    run_verification()
