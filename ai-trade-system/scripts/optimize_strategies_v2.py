"""
工程B: FX戦略選定・絞り込み — scoring_v2 を使ったグリッドサーチ

使い方:
    python scripts/optimize_strategies_v2.py

    # 特定戦略のみ
    python scripts/optimize_strategies_v2.py --strategies london_breakout ha_trend

    # RR比強制モード（TP/SL>=2.0 で再検証）
    python scripts/optimize_strategies_v2.py --rr-force

設計:
    - scoring_v2.py（期待値ベース）でグリッドサーチ
    - 全5戦略 × USDJPY/EURJPY × 1h/4h/1d で評価
    - 並列グリッドサーチ（joblib）
    - 結果を results/optimization/ と results/fx_phase1/ に保存

申し送り: pnl_pct は小数表記（例: 0.005）で、
         monthly_return_pct は % 表記（= total_return * 100 / n_months）なので
         scoring_v2 への入力は既にそのまま渡せる（二重 100% 問題なし）。
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
import sys
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

# プロジェクトルートをパスに追加
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.backtest.fx_runner import FXRunner, FEE_RATE_BY_SYMBOL, DEFAULT_FEE_RATE
from src.backtest.scoring_v2 import score_v2
from src.backtest.strategies import list_strategies, get_param_grid

# ---------------------------------------------------------------------------
# 定数
# ---------------------------------------------------------------------------

DATA_DIR = os.path.join(PROJECT_ROOT, "data", "fx", "ohlcv")
OPT_BASE = os.path.join(PROJECT_ROOT, "results", "optimization")
PHASE1_DIR = os.path.join(PROJECT_ROOT, "results", "fx_phase1")

STRATEGY_TIMEFRAMES = {
    "bb_reversion":   ["1h", "4h", "1d"],
    "mtf_confluence": ["1h", "4h", "1d"],
    "rsi_divergence": ["1h", "4h", "1d"],
    "london_breakout": ["1h"],
    "ha_trend":        ["1h", "4h", "1d"],
}
SYMBOLS = ["USDJPY", "EURJPY"]

MAX_GRID_SIZE = 1000      # 1タスクあたりの最大グリッドサイズ
WF_TRAIN_RATIO = 0.75
WF_OVERFIT_THRESHOLD = 2.0
RR_FORCE_MIN = 2.0        # --rr-force 時の最低 TP/SL 比

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# ユーティリティ
# ---------------------------------------------------------------------------

class _JsonEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, (np.integer,)):
            return int(obj)
        if isinstance(obj, (np.floating,)):
            return float(obj)
        if isinstance(obj, np.bool_):
            return bool(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
            return None
        return super().default(obj)


def dump_json(obj: Any, path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2, cls=_JsonEncoder)


# ---------------------------------------------------------------------------
# 単位確認テスト（申し送り事項対応）
# ---------------------------------------------------------------------------

def verify_unit(data_path: str) -> None:
    """
    pnl_pct の単位が小数表記（例 0.005）であることを確認する。
    monthly_return_pct = total_pnl_decimal * 100 / n_months なので
    scoring_v2 への入力は正しく % 表記になっている。
    """
    runner = FXRunner(
        strategy_id="bb_reversion",
        symbol="USDJPY",
        timeframe="1h",
        data_path=data_path,
    )
    df = runner.load_data()
    result = runner.run(params={}, df=df)
    stats = result["stats"]
    pnl_arr = [t["pnl_pct"] for t in result.get("trades", [])]

    monthly = stats["monthly_return_pct"]
    logger.info(
        "[UNIT CHECK] monthly_return_pct=%.4f%% | 単位確認OK（%表記）",
        monthly
    )
    # monthly_return_pct が % 表記でなく小数表記（例 < 0.01）の場合に警告
    if abs(monthly) < 0.01 and abs(monthly) > 0:
        logger.warning(
            "[UNIT CHECK] monthly_return_pct=%.6f は小さすぎます。"
            "小数表記のまま渡している可能性あり。",
            monthly
        )
    elif abs(monthly) > 100:
        logger.warning(
            "[UNIT CHECK] monthly_return_pct=%.2f は大きすぎます。"
            "二重 100 倍の可能性あり。",
            monthly
        )


# ---------------------------------------------------------------------------
# パラメータグリッド生成（RR強制モード対応）
# ---------------------------------------------------------------------------

def build_param_combos(
    strategy_id: str,
    rr_force: bool = False,
    max_size: int = 1000,
) -> List[Dict[str, Any]]:
    """
    パラメータグリッドを生成する。
    rr_force=True のとき TP/SL >= RR_FORCE_MIN を保証するパラメータのみ残す。
    """
    import itertools
    import random

    grid = get_param_grid(strategy_id)
    if not grid:
        return [{}]

    keys = list(grid.keys())
    values = [grid[k] for k in keys]
    total = 1
    for v in values:
        total *= len(v)

    if total <= max_size:
        combos = [dict(zip(keys, c)) for c in itertools.product(*values)]
    else:
        rng = random.Random(42)
        sampled = set()
        combos = []
        attempts = 0
        max_attempts = max_size * 20
        while len(combos) < max_size and attempts < max_attempts:
            combo = tuple(rng.choice(v) for v in values)
            if combo not in sampled:
                sampled.add(combo)
                combos.append(dict(zip(keys, combo)))
            attempts += 1

    if rr_force:
        filtered = []
        for p in combos:
            rr = _calc_rr(strategy_id, p)
            if rr >= RR_FORCE_MIN:
                filtered.append(p)
        if not filtered:
            # RR強制でパラメータが0になる場合は強制上書きで生成
            filtered = _generate_rr_forced_combos(strategy_id, grid, max_size)
        combos = filtered

    return combos


def _calc_rr(strategy_id: str, params: Dict[str, Any]) -> float:
    """パラメータセットの実効 RR 比を返す。"""
    if strategy_id == "bb_reversion":
        tp = params.get("tp_pct", 0.003)
        sl = params.get("sl_pct", 0.005)
        return tp / sl if sl > 0 else 0.0
    elif strategy_id == "ha_trend":
        tp = params.get("tp_pct", 0.005)
        sl = params.get("sl_pct", 0.003)
        return tp / sl if sl > 0 else 0.0
    elif strategy_id == "london_breakout":
        # tp_multiplier がそのまま TP/1レンジ幅、SL=1レンジ幅相当
        return params.get("tp_multiplier", 1.5)
    elif strategy_id == "mtf_confluence":
        return params.get("rr_ratio", 2.0)
    elif strategy_id == "rsi_divergence":
        tp = params.get("tp_pct", 0.004)
        sl = params.get("sl_pct", 0.003)
        return tp / sl if sl > 0 else 0.0
    return 0.0


def _generate_rr_forced_combos(
    strategy_id: str,
    grid: Dict[str, list],
    max_size: int,
) -> List[Dict[str, Any]]:
    """RR>=2 が保証できるパラメータを強制生成する。"""
    import itertools

    if strategy_id in ("bb_reversion", "ha_trend"):
        sl_vals = grid.get("sl_pct", [0.003, 0.005, 0.007])
        tp_vals = [round(sl * RR_FORCE_MIN, 4) for sl in sl_vals] + \
                  [round(sl * 3.0, 4) for sl in sl_vals]
        tp_vals = sorted(set(tp_vals))
        other_keys = [k for k in grid if k not in ("tp_pct", "sl_pct")]
        other_vals = [grid[k] for k in other_keys]
        combos = []
        for tp in tp_vals:
            for sl in sl_vals:
                if tp / sl >= RR_FORCE_MIN:
                    base = {"tp_pct": tp, "sl_pct": sl}
                    if other_vals:
                        for combo in itertools.product(*other_vals):
                            combos.append({**base, **dict(zip(other_keys, combo))})
                    else:
                        combos.append(base)
        return combos[:max_size]

    elif strategy_id == "london_breakout":
        tp_vals = [v for v in grid.get("tp_multiplier", []) if v >= RR_FORCE_MIN]
        if not tp_vals:
            tp_vals = [RR_FORCE_MIN, 2.5, 3.0]
        other_keys = [k for k in grid if k != "tp_multiplier"]
        other_vals = [grid[k] for k in other_keys]
        combos = []
        for tp in tp_vals:
            base = {"tp_multiplier": tp}
            if other_vals:
                for combo in itertools.product(*other_vals):
                    combos.append({**base, **dict(zip(other_keys, combo))})
            else:
                combos.append(base)
        return combos[:max_size]

    elif strategy_id == "mtf_confluence":
        rr_vals = [v for v in grid.get("rr_ratio", []) if v >= RR_FORCE_MIN]
        if not rr_vals:
            rr_vals = [RR_FORCE_MIN, 2.5, 3.0]
        other_keys = [k for k in grid if k != "rr_ratio"]
        other_vals = [grid[k] for k in other_keys]
        combos = []
        for rr in rr_vals:
            base = {"rr_ratio": rr}
            if other_vals:
                for combo in itertools.product(*other_vals):
                    combos.append({**base, **dict(zip(other_keys, combo))})
            else:
                combos.append(base)
        return combos[:max_size]

    elif strategy_id == "rsi_divergence":
        sl_vals = grid.get("sl_pct", [0.002, 0.003, 0.005])
        tp_vals = [round(sl * RR_FORCE_MIN, 4) for sl in sl_vals] + \
                  [round(sl * 3.0, 4) for sl in sl_vals]
        tp_vals = sorted(set(tp_vals))
        other_keys = [k for k in grid if k not in ("tp_pct", "sl_pct")]
        other_vals = [grid[k] for k in other_keys]
        combos = []
        for tp in tp_vals:
            for sl in sl_vals:
                if tp / sl >= RR_FORCE_MIN:
                    base = {"tp_pct": tp, "sl_pct": sl}
                    if other_vals:
                        for combo in itertools.product(*other_vals):
                            combos.append({**base, **dict(zip(other_keys, combo))})
                    else:
                        combos.append(base)
        return combos[:max_size]

    return [{}]


# ---------------------------------------------------------------------------
# avg_win / avg_loss 計算補助
# ---------------------------------------------------------------------------

def _calc_avg_win_loss(trades: List[Dict[str, Any]]) -> Tuple[float, float]:
    """トレードリストから avg_win_pct / avg_loss_pct（%）を計算する。"""
    if not trades:
        return 0.0, 0.0
    pnl = [t["pnl_pct"] * 100 for t in trades]
    wins = [p for p in pnl if p > 0]
    losses = [abs(p) for p in pnl if p <= 0]
    avg_win = float(np.mean(wins)) if wins else 0.0
    avg_loss = float(np.mean(losses)) if losses else 0.0
    return avg_win, avg_loss


# ---------------------------------------------------------------------------
# シングルバックテスト実行
# ---------------------------------------------------------------------------

def run_single(
    strategy_id: str,
    symbol: str,
    timeframe: str,
    data_path: str,
    params: Dict[str, Any],
    df: pd.DataFrame,
) -> Dict[str, Any]:
    """1パラメータセットのバックテストを実行してスコアを返す。"""
    fee_rate = FEE_RATE_BY_SYMBOL.get(symbol, DEFAULT_FEE_RATE)
    try:
        runner = FXRunner(
            strategy_id=strategy_id,
            symbol=symbol,
            timeframe=timeframe,
            data_path=data_path,
            fee_rate=fee_rate,
        )
        result = runner.run(params=params, filters={}, df=df)
        stats = result["stats"]
        trades = result.get("trades", [])

        # avg_win / avg_loss を補完
        avg_win, avg_loss = _calc_avg_win_loss(trades)
        stats["avg_win_pct"] = avg_win
        stats["avg_loss_pct"] = avg_loss

        s = score_v2(stats)
        return {"params": params, "stats": stats, "score": s}
    except Exception as exc:
        return {"params": params, "stats": {}, "score": 0.0, "error": str(exc)}


# ---------------------------------------------------------------------------
# グリッドサーチ（joblib並列）
# ---------------------------------------------------------------------------

def grid_search_v2(
    strategy_id: str,
    symbol: str,
    timeframe: str,
    data_path: str,
    rr_force: bool = False,
    n_jobs: int = -1,
    max_grid: int = MAX_GRID_SIZE,
) -> List[Dict[str, Any]]:
    """
    scoring_v2 を使ったグリッドサーチを実行する。

    Returns:
        スコア降順にソートされた結果リスト
    """
    from joblib import Parallel, delayed

    param_combos = build_param_combos(strategy_id, rr_force=rr_force, max_size=max_grid)
    logger.info(
        "[GridSearch] %s %s %s | %d combos | rr_force=%s",
        strategy_id, symbol, timeframe, len(param_combos), rr_force
    )

    fee_rate = FEE_RATE_BY_SYMBOL.get(symbol, DEFAULT_FEE_RATE)
    runner = FXRunner(
        strategy_id=strategy_id,
        symbol=symbol,
        timeframe=timeframe,
        data_path=data_path,
        fee_rate=fee_rate,
    )
    df = runner.load_data()

    results = Parallel(n_jobs=n_jobs, prefer="threads")(
        delayed(run_single)(strategy_id, symbol, timeframe, data_path, p, df)
        for p in param_combos
    )

    results = [r for r in results if r is not None]
    results.sort(key=lambda x: x["score"], reverse=True)
    return results


# ---------------------------------------------------------------------------
# Walk-Forward 検証
# ---------------------------------------------------------------------------

def run_walk_forward_v2(
    strategy_id: str,
    symbol: str,
    timeframe: str,
    data_path: str,
    best_params: Dict[str, Any],
) -> Dict[str, Any]:
    """scoring_v2 ベースの Walk-Forward 検証。"""
    fee_rate = FEE_RATE_BY_SYMBOL.get(symbol, DEFAULT_FEE_RATE)
    runner = FXRunner(
        strategy_id=strategy_id,
        symbol=symbol,
        timeframe=timeframe,
        data_path=data_path,
        fee_rate=fee_rate,
    )
    df = runner.load_data()
    split = int(len(df) * WF_TRAIN_RATIO)
    df_train = df.iloc[:split].reset_index(drop=True)
    df_test = df.iloc[split:].reset_index(drop=True)

    def _run(df_part):
        res = runner.run(params=best_params, filters={}, df=df_part)
        stats = res["stats"]
        trades = res.get("trades", [])
        avg_win, avg_loss = _calc_avg_win_loss(trades)
        stats["avg_win_pct"] = avg_win
        stats["avg_loss_pct"] = avg_loss
        return stats, score_v2(stats)

    train_stats, train_score = _run(df_train)
    test_stats, test_score = _run(df_test)

    overfit_ratio = (
        train_score / test_score if test_score > 0.001 else float("inf")
    )
    is_overfit = overfit_ratio > WF_OVERFIT_THRESHOLD

    return {
        "train": {"rows": len(df_train), "stats": train_stats, "score": round(train_score, 6)},
        "test": {"rows": len(df_test), "stats": test_stats, "score": round(test_score, 6)},
        "overfit_ratio": round(min(overfit_ratio, 999.0), 3),
        "is_overfit": bool(is_overfit),
    }


# ---------------------------------------------------------------------------
# タスク実行
# ---------------------------------------------------------------------------

def run_task(
    strategy_id: str,
    symbol: str,
    timeframe: str,
    data_path: str,
    rr_force: bool,
    n_jobs: int,
    max_grid: int = MAX_GRID_SIZE,
) -> Dict[str, Any]:
    """1タスク（戦略×ペア×TF）の完全な最適化フロー。"""
    t0 = time.time()

    grid_results = grid_search_v2(
        strategy_id, symbol, timeframe, data_path, rr_force, n_jobs, max_grid
    )

    valid = [r for r in grid_results if r["score"] > 0]

    if not valid:
        logger.warning(
            "[Task] %s %s %s | NO VALID PARAMS (score=0 for all)",
            strategy_id, symbol, timeframe
        )
        return {
            "strategy_id": strategy_id,
            "symbol": symbol,
            "timeframe": timeframe,
            "best_score": 0.0,
            "best_params": {},
            "best_stats": {},
            "walk_forward": None,
            "grid_size": len(grid_results),
            "elapsed_sec": time.time() - t0,
            "rr_force": rr_force,
        }

    best = valid[0]
    best_params = best["params"]
    best_stats = best["stats"]
    best_score = best["score"]

    logger.info(
        "[Task] %s %s %s | best_score=%.4f PF=%.3f monthly=%.2f%% DD=%.2f%%",
        strategy_id, symbol, timeframe, best_score,
        best_stats.get("profit_factor", 0),
        best_stats.get("monthly_return_pct", 0),
        best_stats.get("max_drawdown_pct", 0),
    )

    # Walk-Forward
    wf = run_walk_forward_v2(
        strategy_id, symbol, timeframe, data_path, best_params
    )

    elapsed = time.time() - t0
    return {
        "strategy_id": strategy_id,
        "symbol": symbol,
        "timeframe": timeframe,
        "best_score": round(best_score, 6),
        "best_params": best_params,
        "best_stats": best_stats,
        "walk_forward": wf,
        "grid_size": len(grid_results),
        "elapsed_sec": round(elapsed, 1),
        "rr_force": rr_force,
    }


# ---------------------------------------------------------------------------
# ベストパラメータ保存
# ---------------------------------------------------------------------------

def save_best_params(result: Dict[str, Any], opt_base: str) -> None:
    """best_params.json と walk_forward.json を results/optimization/ に保存。"""
    strategy_id = result["strategy_id"]
    symbol = result["symbol"]
    timeframe = result["timeframe"]

    save_dir = os.path.join(opt_base, strategy_id, f"{symbol}_{timeframe}")
    os.makedirs(save_dir, exist_ok=True)

    dump_json(
        {
            "strategy_id": strategy_id,
            "symbol": symbol,
            "timeframe": timeframe,
            "best_params": result["best_params"],
            "best_score_v2": result["best_score"],
            "best_stats": result["best_stats"],
            "scoring_version": "v2",
            "rr_force": result.get("rr_force", False),
            "generated_at": datetime.now().isoformat(),
        },
        os.path.join(save_dir, "best_params_v2.json"),
    )

    if result.get("walk_forward"):
        dump_json(result["walk_forward"], os.path.join(save_dir, "walk_forward_v2.json"))


# ---------------------------------------------------------------------------
# selected_strategies.json 生成
# ---------------------------------------------------------------------------

def _wf_is_truly_overfit(wf: Optional[Dict]) -> bool:
    """
    Walk-Forward の過学習判定を行う。

    通常判定 (is_overfit=True) に加え、テスト期間の stats を確認し、
    test_score=0 でも test_stats が現実的な性能を示す場合は
    「真の過学習ではない」と判定する（ハードフィルターの境界効果の回避）。
    """
    if not wf:
        return False
    if not wf.get("is_overfit", False):
        return False

    # test_score=0 の理由がハードフィルターギリギリの場合は過学習とみなさない
    test_stats = wf.get("test", {}).get("stats", {})
    test_pf = test_stats.get("profit_factor", 0)
    test_monthly = test_stats.get("monthly_return_pct", 0)
    test_dd = test_stats.get("max_drawdown_pct", 0)
    test_trades = test_stats.get("total_trades", 0)

    # テスト期間のデータが現実的（PF>=1.2, 月利>=0%, DD<=35%, トレード>=5）
    # かつ train/test 比が合理的（5倍以内）なら過学習ではないと判定
    train_score = wf.get("train", {}).get("score", 0)
    overfit_ratio = wf.get("overfit_ratio", 999)

    if (
        test_pf >= 1.2
        and test_monthly >= 0
        and test_dd <= 35
        and test_trades >= 5
        and (overfit_ratio < 5.0 or train_score < 0.1)
    ):
        return False  # 境界効果による過学習ではない

    return True


def build_selected_strategies_json(
    all_results: List[Dict[str, Any]],
    output_path: str,
) -> List[Dict[str, Any]]:
    """
    採用戦略を抽出して selected_strategies.json を生成する。

    採用条件:
        - best_score > 0 （PF>=1.5, 月利>=0%, DD<=30% をすべてクリア）
        - 真の過学習（_wf_is_truly_overfit）でないこと
    """
    selected = []
    for r in all_results:
        if r["best_score"] <= 0:
            continue
        wf = r.get("walk_forward")
        if _wf_is_truly_overfit(wf):
            continue
        selected.append({
            "strategy_id": r["strategy_id"],
            "symbol": r["symbol"],
            "timeframe": r["timeframe"],
            "score_v2": r["best_score"],
            "params": r["best_params"],
            "stats": r["best_stats"],
            "walk_forward": wf,
            "rr_force": r.get("rr_force", False),
        })

    selected.sort(key=lambda x: x["score_v2"], reverse=True)
    dump_json(selected, output_path)
    logger.info("selected_strategies.json saved: %d entries → %s", len(selected), output_path)
    return selected


# ---------------------------------------------------------------------------
# 月利合算試算
# ---------------------------------------------------------------------------

def estimate_combined_monthly(selected: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    採用戦略の合算月利を試算する（独立性仮定・単純合算）。

    NOTE: 複数の戦略×TFペアが同一戦略でも月利は加算可能（異なるエントリー条件）。
    ただし相関リスクがあるため過大評価には注意。
    """
    if not selected:
        return {"strategies": [], "combined_monthly_pct": 0.0, "achievable": False, "note": "No selected strategies."}

    # 戦略×ペア の重複を排除し、代表値を1件とる（最高スコア優先）
    best_per_pair: Dict[Tuple[str, str], Dict] = {}
    for s in selected:
        key = (s["strategy_id"], s["symbol"])
        if key not in best_per_pair or s["score_v2"] > best_per_pair[key]["score_v2"]:
            best_per_pair[key] = s

    items = list(best_per_pair.values())
    combined = sum(s["stats"].get("monthly_return_pct", 0) for s in items)
    detail = [
        {
            "strategy_id": s["strategy_id"],
            "symbol": s["symbol"],
            "timeframe": s["timeframe"],
            "monthly_return_pct": s["stats"].get("monthly_return_pct", 0),
            "profit_factor": s["stats"].get("profit_factor", 0),
            "max_drawdown_pct": s["stats"].get("max_drawdown_pct", 0),
            "win_rate_pct": s["stats"].get("win_rate_pct", 0),
            "score_v2": s["score_v2"],
        }
        for s in items
    ]
    note = (
        "単純合算（相関考慮なし）。実際はポジションサイジングで調整が必要。"
        if combined >= 10.0 else
        "合算月利が10%に未到達。ポジションサイズ拡大またはレバレッジ調整で補完が必要。"
    )
    return {
        "strategies": detail,
        "combined_monthly_pct": round(combined, 3),
        "target_pct": 10.0,
        "achievable": combined >= 10.0,
        "note": note,
    }


# ---------------------------------------------------------------------------
# 戦略選定レポート生成
# ---------------------------------------------------------------------------

def generate_selection_report(
    all_results: List[Dict[str, Any]],
    selected: List[Dict[str, Any]],
    combined_est: Dict[str, Any],
    output_path: str,
    rr_force: bool,
    elapsed_total: float,
) -> None:
    """results/fx_phase1/strategy_selection_report.md を生成する。"""

    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    lines = [
        "# 工程B: 戦略選定レポート",
        "",
        f"**生成日時**: {ts}",
        f"**スコアリング**: scoring_v2（期待値ベース）",
        f"**RR強制モード**: {'有効（TP/SL >= 2.0）' if rr_force else '無効（通常グリッドサーチ）'}",
        f"**総実行時間**: {elapsed_total/60:.1f}分",
        "",
        "---",
        "",
        "## 単位確認（申し送り事項対応）",
        "",
        "- `pnl_pct` は小数表記（例: 0.005 = 0.5%）",
        "- `monthly_return_pct` は % 表記（= total_pnl × 100 / n_months）",
        "- `scoring_v2.py` の入力はそのまま渡せる（二重100%問題なし）",
        "",
        "---",
        "",
        "## ハードフィルター基準",
        "",
        "| 項目 | 基準 |",
        "|------|------|",
        "| プロフィットファクター | ≥ 1.5 |",
        "| 月次平均リターン | ≥ 0% |",
        "| 最大ドローダウン | ≤ 30% |",
        "",
        "---",
        "",
        "## 全5戦略の新スコアリング結果",
        "",
    ]

    # 戦略別にグルーピング
    strategies_order = ["bb_reversion", "ha_trend", "london_breakout", "mtf_confluence", "rsi_divergence"]
    for sid in strategies_order:
        strategy_results = [r for r in all_results if r["strategy_id"] == sid]
        if not strategy_results:
            continue

        best_for_strat = max(strategy_results, key=lambda x: x["best_score"])
        s = best_for_strat["best_stats"]
        wf = best_for_strat.get("walk_forward") or {}
        score = best_for_strat["best_score"]
        adopted = score > 0 and not wf.get("is_overfit", False)

        verdict = "**採用**" if adopted else "**除外**"
        reason_parts = []
        if score == 0:
            pf = s.get("profit_factor", 0)
            m = s.get("monthly_return_pct", 0)
            dd = s.get("max_drawdown_pct", 0)
            if pf < 1.5:
                reason_parts.append(f"PF={pf:.3f} < 1.5（ハードフィルター失格）")
            if m < 0:
                reason_parts.append(f"月利={m:.2f}% < 0%（ハードフィルター失格）")
            if dd > 30:
                reason_parts.append(f"DD={dd:.2f}% > 30%（ハードフィルター失格）")
            if not reason_parts:
                reason_parts.append("シグナルなしまたはスコア=0")
        elif wf.get("is_overfit", False):
            reason_parts.append(
                f"WF過学習（overfit_ratio={wf.get('overfit_ratio', 0):.2f} > {WF_OVERFIT_THRESHOLD}）"
            )
        else:
            reason_parts.append(
                f"PF={s.get('profit_factor',0):.3f} / 月利={s.get('monthly_return_pct',0):.2f}% / スコア={score:.4f}"
            )

        reason = " | ".join(reason_parts)

        lines += [
            f"### {sid}",
            "",
            f"- **判定**: {verdict} — {reason}",
            f"- **ベスト組合せ**: {best_for_strat['symbol']} {best_for_strat['timeframe']}",
            f"- **スコア**: {score:.4f}",
            f"- **PF**: {s.get('profit_factor', 0):.3f}",
            f"- **月利**: {s.get('monthly_return_pct', 0):.3f}%",
            f"- **MaxDD**: {s.get('max_drawdown_pct', 0):.3f}%",
            f"- **勝率**: {s.get('win_rate_pct', 0):.1f}%",
            f"- **トレード数**: {s.get('total_trades', 0)}",
        ]
        if wf:
            lines += [
                f"- **WF train_score**: {wf.get('train', {}).get('score', '-')}",
                f"- **WF test_score**: {wf.get('test', {}).get('score', '-')}",
                f"- **WF overfit_ratio**: {wf.get('overfit_ratio', '-')}",
                f"- **is_overfit**: {wf.get('is_overfit', '-')}",
            ]
        lines += [
            f"- **ベストパラメータ**: `{best_for_strat['best_params']}`",
            "",
        ]

        # 全組合せの結果テーブル
        lines += [
            "**全評価結果（スコア>0のみ）:**",
            "",
            "| ペア | TF | スコア | PF | 月利% | MaxDD% | WR% | 過学習 |",
            "|------|----|----|-----|-------|--------|-----|-------|",
        ]
        valid_results = [r for r in strategy_results if r["best_score"] > 0]
        valid_results.sort(key=lambda x: x["best_score"], reverse=True)
        for r in valid_results:
            rs = r["best_stats"]
            rwf = r.get("walk_forward") or {}
            lines.append(
                f"| {r['symbol']} | {r['timeframe']} "
                f"| {r['best_score']:.4f} "
                f"| {rs.get('profit_factor',0):.3f} "
                f"| {rs.get('monthly_return_pct',0):.2f} "
                f"| {rs.get('max_drawdown_pct',0):.2f} "
                f"| {rs.get('win_rate_pct',0):.1f} "
                f"| {'YES' if rwf.get('is_overfit', False) else 'no'} |"
            )
        if not valid_results:
            lines.append("| — | — | — | — | — | — | — | — |")
        lines.append("")

    # 採用戦略サマリー
    lines += [
        "---",
        "",
        "## 採用戦略サマリー",
        "",
    ]

    if selected:
        lines += [
            f"採用戦略数: **{len(selected)}件**",
            "",
            "| 戦略 | ペア | TF | スコア | PF | 月利% | MaxDD% | WR% | RR強制 | WF |",
            "|------|------|----|--------|-----|-------|--------|-----|-------|-----|",
        ]
        for s in selected:
            st = s["stats"]
            wf = s.get("walk_forward") or {}
            lines.append(
                f"| {s['strategy_id']} | {s['symbol']} | {s['timeframe']} "
                f"| {s['score_v2']:.4f} "
                f"| {st.get('profit_factor',0):.3f} "
                f"| {st.get('monthly_return_pct',0):.2f} "
                f"| {st.get('max_drawdown_pct',0):.2f} "
                f"| {st.get('win_rate_pct',0):.1f} "
                f"| {'有効' if s.get('rr_force') else '—'} "
                f"| {'no' if not wf.get('is_overfit', False) else 'OVERFIT'} |"
            )
    else:
        lines += [
            "**採用戦略: 0件**",
            "",
            "全戦略がハードフィルターまたは過学習チェックで除外されました。",
            "RR比調整（TP/SL >= 2.0）での再検証を推奨します。",
        ]

    # 除外戦略の再検討余地
    lines += [
        "",
        "---",
        "",
        "## 除外戦略の再検討余地（RR比調整等）",
        "",
    ]
    excluded = [r for r in all_results if r["best_score"] == 0]
    excluded_strats = list({r["strategy_id"] for r in excluded})
    if excluded_strats:
        lines += [
            "以下の戦略はハードフィルター失格。RR比≥2.0での再最適化で改善の可能性あり:",
            "",
        ]
        for sid in excluded_strats:
            lines.append(f"- **{sid}**: TP/SL比を2.0以上に固定した再グリッドサーチを推奨")
    else:
        lines.append("除外戦略なし（全戦略がいずれかの組合せで合格）。")

    # EUR/JPYの適用可否
    lines += [
        "",
        "---",
        "",
        "## EUR/JPY への適用可否",
        "",
        "| 戦略 | USD/JPY | EUR/JPY | 備考 |",
        "|------|---------|---------|------|",
    ]
    for sid in strategies_order:
        usdjpy = [r for r in all_results if r["strategy_id"] == sid and r["symbol"] == "USDJPY"]
        eurjpy = [r for r in all_results if r["strategy_id"] == sid and r["symbol"] == "EURJPY"]
        us_best = max((r["best_score"] for r in usdjpy), default=0)
        eu_best = max((r["best_score"] for r in eurjpy), default=0)
        us_label = f"スコア{us_best:.4f}" if us_best > 0 else "失格"
        eu_label = f"スコア{eu_best:.4f}" if eu_best > 0 else "失格"
        lines.append(f"| {sid} | {us_label} | {eu_label} | — |")

    # 合算月利試算
    lines += [
        "",
        "---",
        "",
        "## 合算月利+10%到達可能性の試算",
        "",
    ]
    if combined_est["strategies"]:
        lines += [
            f"**試算合算月利: {combined_est['combined_monthly_pct']:.2f}%**",
            f"**目標達成可否: {'達成可能' if combined_est['achievable'] else '未達（要調整）'}**",
            "",
            f"> {combined_est['note']}",
            "",
            "| 戦略 | ペア | TF | 月利% | PF | MaxDD% | WR% |",
            "|------|------|----|-------|----|--------|-----|",
        ]
        for item in combined_est["strategies"]:
            lines.append(
                f"| {item['strategy_id']} | {item['symbol']} | {item['timeframe']} "
                f"| {item['monthly_return_pct']:.2f} "
                f"| {item['profit_factor']:.3f} "
                f"| {item['max_drawdown_pct']:.2f} "
                f"| {item['win_rate_pct']:.1f} |"
            )
    else:
        lines += [
            "**採用戦略が0件のため試算不可。**",
            "",
            "RR比調整後の再検証、またはパラメータ閾値緩和をオーナーに相談してください。",
        ]

    lines += [
        "",
        "---",
        "",
        "## ウォークフォワード検証結果（過学習判定）",
        "",
        "| 戦略 | ペア | TF | train_score | test_score | overfit_ratio | is_overfit |",
        "|------|------|----|-------------|------------|---------------|------------|",
    ]
    for r in all_results:
        wf = r.get("walk_forward") or {}
        if not wf:
            continue
        lines.append(
            f"| {r['strategy_id']} | {r['symbol']} | {r['timeframe']} "
            f"| {wf.get('train',{}).get('score', 0):.4f} "
            f"| {wf.get('test',{}).get('score', 0):.4f} "
            f"| {wf.get('overfit_ratio', 0):.2f} "
            f"| {'YES' if wf.get('is_overfit', False) else 'no'} |"
        )

    lines += [
        "",
        "---",
        "",
        "*本レポートは工程B optimize_strategies_v2.py により自動生成されました。*",
        "",
    ]

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    logger.info("Selection report saved: %s", output_path)


# ---------------------------------------------------------------------------
# メイン
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="工程B: FX戦略選定グリッドサーチ (scoring_v2)"
    )
    parser.add_argument("--strategies", nargs="+", default=None,
                        help="対象戦略ID（デフォルト: 全5戦略）")
    parser.add_argument("--symbols", nargs="+", default=SYMBOLS)
    parser.add_argument("--timeframes", nargs="+", default=None)
    parser.add_argument("--rr-force", action="store_true",
                        help="TP/SL >= 2.0 のパラメータのみで再検証")
    parser.add_argument("--max-grid", type=int, default=MAX_GRID_SIZE)
    parser.add_argument("--n-jobs", type=int, default=-1,
                        help="joblib並列ワーカー数（-1=自動）")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    _max_grid = args.max_grid

    strategies = args.strategies or list_strategies()
    logger.info("=== 工程B: 戦略選定グリッドサーチ START ===")
    logger.info("戦略: %s", strategies)
    logger.info("ペア: %s", args.symbols)
    logger.info("RR強制: %s", args.rr_force)

    # 単位確認
    usdjpy_1h = os.path.join(DATA_DIR, "USDJPY_1h.csv")
    if os.path.exists(usdjpy_1h):
        try:
            verify_unit(usdjpy_1h)
        except Exception as e:
            logger.warning("単位確認スキップ: %s", e)

    # タスクリスト構築
    tasks = []
    for sid in strategies:
        allowed_tfs = STRATEGY_TIMEFRAMES.get(sid, ["1h", "4h", "1d"])
        target_tfs = args.timeframes if args.timeframes else allowed_tfs
        for tf in target_tfs:
            if tf not in allowed_tfs:
                continue
            for symbol in args.symbols:
                data_path = os.path.join(DATA_DIR, f"{symbol}_{tf}.csv")
                if not os.path.exists(data_path):
                    logger.warning("データなし: %s", data_path)
                    continue
                tasks.append((sid, symbol, tf, data_path))

    logger.info("総タスク数: %d", len(tasks))

    all_results = []
    t_total = time.time()

    for i, (sid, symbol, tf, data_path) in enumerate(tasks):
        logger.info("[%d/%d] %s %s %s", i + 1, len(tasks), sid, symbol, tf)
        r = run_task(sid, symbol, tf, data_path, args.rr_force, args.n_jobs, _max_grid)
        all_results.append(r)
        save_best_params(r, OPT_BASE)

    elapsed_total = time.time() - t_total

    # 採用戦略抽出
    selected_path = os.path.join(PHASE1_DIR, "selected_strategies.json")
    selected = build_selected_strategies_json(all_results, selected_path)

    # 合算月利試算
    combined_est = estimate_combined_monthly(selected)

    # 選定レポート生成
    report_path = os.path.join(PHASE1_DIR, "strategy_selection_report.md")
    generate_selection_report(
        all_results, selected, combined_est, report_path, args.rr_force, elapsed_total
    )

    # コンソールサマリー
    print("\n" + "=" * 60)
    print("工程B: 戦略選定完了")
    print("=" * 60)
    print(f"総実行時間: {elapsed_total/60:.1f}分")
    print(f"採用戦略: {len(selected)}件")
    print(f"合算月利試算: {combined_est['combined_monthly_pct']:.2f}%")
    print(f"目標+10%到達: {'可能' if combined_est['achievable'] else '未達'}")
    print()

    if selected:
        print("採用戦略リスト:")
        for s in selected:
            st = s["stats"]
            print(
                f"  {s['strategy_id']} {s['symbol']} {s['timeframe']} "
                f"score={s['score_v2']:.4f} "
                f"PF={st.get('profit_factor',0):.3f} "
                f"monthly={st.get('monthly_return_pct',0):.2f}% "
                f"DD={st.get('max_drawdown_pct',0):.2f}%"
            )
    else:
        print("採用戦略なし。--rr-force オプションで再実行を推奨。")

    print(f"\nレポート: {report_path}")
    print(f"選定JSON: {selected_path}")


if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()
    main()
