"""
FX戦略グリッドサーチ + Walk-Forward最適化エンジン

概要:
    工程4: パラメータ最適化（グリッドサーチ + Walk-Forward Analysis）

    - 各戦略のPARAM_GRIDを全探索（最大500組合せに間引き）
    - Walk-Forward Analysis: 前半75%をtrain、後半25%をtestとして過学習チェック
    - multiprocessing.Poolで並列実行
    - 結果はインクリメンタルに保存（メモリ効率）

評価関数（要件定義書 承認済み）:
    score = win_rate × 0.4 + PF × 0.3 + 月利 × 0.2 + (1 - DD/10) × 0.1
    PFは min(PF, 5.0) でクリップ、DDが10%超は失格（score=0）

使い方:
    from src.backtest.fx_optimizer import FXOptimizer

    opt = FXOptimizer(
        strategy_id="bb_reversion",
        symbol="USDJPY",
        timeframe="1h",
        data_path="data/fx/ohlcv/USDJPY_1h.csv",
        output_base="results/optimization",
    )
    result = opt.run()
"""

from __future__ import annotations

import csv
import itertools
import json
import logging
import math
import os
import random
import sys
import time
from datetime import datetime
from multiprocessing import Pool, cpu_count
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

# プロジェクトルートをパスに追加
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))


class _JsonEncoder(json.JSONEncoder):
    """numpy / Python型を安全にJSON変換するカスタムエンコーダー。"""

    def default(self, obj: Any) -> Any:
        if isinstance(obj, (np.integer,)):
            return int(obj)
        if isinstance(obj, (np.floating,)):
            return float(obj)
        if isinstance(obj, (np.bool_,)):
            return bool(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
            return None
        return super().default(obj)


def _dump_json(obj: Any, path: str) -> None:
    """JSONファイルに安全に書き込む。"""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2, cls=_JsonEncoder)


if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.backtest.fx_runner import FXRunner
from src.backtest.strategies import get_param_grid, load_strategy

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 定数
# ---------------------------------------------------------------------------

MAX_GRID_SIZE = 500          # 1戦略×1TF×1pairあたりの最大組合せ数
WALK_FORWARD_TRAIN_RATIO = 0.75  # trainデータの割合
MIN_TRADES_THRESHOLD = 5     # Walk-Forward testで最低必要トレード数
OVERFITTING_RATIO_WARN = 2.0 # train/testスコア比がこれ超で過学習警告


# ---------------------------------------------------------------------------
# 評価関数
# ---------------------------------------------------------------------------


def calc_score(stats: Dict[str, Any]) -> float:
    """
    要件定義書の評価関数でスコアを計算する。

    score = win_rate × 0.4 + PF × 0.3 + 月利 × 0.2 + (1 - DD/10) × 0.1
    PFは min(PF, 5.0) でクリップ
    DDが10%超は失格（score=0）

    Args:
        stats: FXRunner._calc_stats() の返値

    Returns:
        float: スコア（0.0〜1.0+α 相当）
    """
    total_trades = stats.get("total_trades", 0)
    if total_trades == 0:
        return 0.0

    win_rate = stats.get("win_rate_pct", 0.0) / 100.0  # 0.0〜1.0
    pf = min(stats.get("profit_factor", 0.0), 5.0)      # クリップ
    monthly_return = stats.get("monthly_return_pct", 0.0)  # 例: 2.5
    max_dd = stats.get("max_drawdown_pct", 0.0)             # 例: 4.5

    # DDが10%超は失格
    if max_dd > 10.0:
        return 0.0

    # PFを0〜1にスケール（5.0が最大）
    pf_score = pf / 5.0

    # 月利を0〜1にスケール（5%を基準）
    monthly_score = max(0.0, min(monthly_return / 5.0, 1.0))

    # DDペナルティ（10%が満点0点、0%が満点0.1点）
    dd_score = 1.0 - (max_dd / 10.0)

    score = (
        win_rate * 0.4
        + pf_score * 0.3
        + monthly_score * 0.2
        + dd_score * 0.1
    )
    return round(score, 6)


# ---------------------------------------------------------------------------
# グリッドサンプリング
# ---------------------------------------------------------------------------


def sample_param_grid(
    param_grid: Dict[str, List[Any]],
    max_size: int = MAX_GRID_SIZE,
    seed: int = 42,
) -> List[Dict[str, Any]]:
    """
    PARAM_GRIDから最大 max_size 組合せをサンプリングして返す。

    全組合せが max_size 以下なら全探索。
    超える場合は重要パラメータ（tp_pct, sl_pct, hold_bars）をフル探索し、
    残りをランダムサンプリングする。

    Args:
        param_grid: 戦略のパラメータグリッド
        max_size: 最大組合せ数
        seed: ランダムシード

    Returns:
        List[Dict]: パラメータ辞書のリスト
    """
    # 全組合せを計算
    keys = list(param_grid.keys())
    values = [param_grid[k] for k in keys]
    total = 1
    for v in values:
        total *= len(v)

    if total <= max_size:
        # 全探索
        combos = list(itertools.product(*values))
        return [dict(zip(keys, c)) for c in combos]

    # 間引き: ランダムサンプリング
    rng = random.Random(seed)
    sampled = set()
    result = []
    max_attempts = max_size * 20

    attempts = 0
    while len(result) < max_size and attempts < max_attempts:
        combo = tuple(rng.choice(v) for v in values)
        if combo not in sampled:
            sampled.add(combo)
            result.append(dict(zip(keys, combo)))
        attempts += 1

    logger.info(
        "Grid sampling: total=%d → sampled=%d (max=%d)",
        total, len(result), max_size
    )
    return result


# ---------------------------------------------------------------------------
# 並列実行用ワーカー関数（モジュールトップレベルに配置が必須）
# ---------------------------------------------------------------------------


def _run_single_backtest(args: Tuple) -> Dict[str, Any]:
    """
    並列実行ワーカー: 1パラメータセットのバックテストを実行する。

    Args:
        args: (strategy_id, symbol, timeframe, data_path, fee_rate, params, df_data)

    Returns:
        Dict: {"params": ..., "stats": ..., "score": ...}
    """
    strategy_id, symbol, timeframe, data_path, fee_rate, params, df_bytes = args

    try:
        # DataFrameをデシリアライズ
        import io
        df = pd.read_parquet(io.BytesIO(df_bytes))

        runner = FXRunner(
            strategy_id=strategy_id,
            symbol=symbol,
            timeframe=timeframe,
            data_path=data_path,
            fee_rate=fee_rate,
        )
        result = runner.run(params=params, filters={}, df=df)
        stats = result["stats"]
        score = calc_score(stats)

        return {
            "params": params,
            "stats": stats,
            "score": score,
        }
    except Exception as exc:
        # エラーでも他の組合せは継続
        return {
            "params": params,
            "stats": {},
            "score": 0.0,
            "error": str(exc),
        }


# ---------------------------------------------------------------------------
# Walk-Forward分析
# ---------------------------------------------------------------------------


def run_walk_forward(
    strategy_id: str,
    symbol: str,
    timeframe: str,
    data_path: str,
    best_params: Dict[str, Any],
    fee_rate: float,
) -> Dict[str, Any]:
    """
    Walk-Forward Analysis を実行する。

    前半75%でbest_paramsを確認し、後半25%で検証する。
    train/testのスコア乖離で過学習を検出する。

    Args:
        strategy_id: 戦略ID
        symbol: 通貨ペア
        timeframe: 時間足
        data_path: データパス
        best_params: グリッドサーチで選ばれたベストパラメータ
        fee_rate: スプレッドコスト

    Returns:
        Dict: Walk-Forward結果
    """
    runner = FXRunner(
        strategy_id=strategy_id,
        symbol=symbol,
        timeframe=timeframe,
        data_path=data_path,
        fee_rate=fee_rate,
    )
    df = runner.load_data()
    split_idx = int(len(df) * WALK_FORWARD_TRAIN_RATIO)

    df_train = df.iloc[:split_idx].reset_index(drop=True)
    df_test = df.iloc[split_idx:].reset_index(drop=True)

    logger.info(
        "Walk-Forward: train=%d rows, test=%d rows",
        len(df_train), len(df_test)
    )

    # Trainでバックテスト
    train_result = runner.run(params=best_params, filters={}, df=df_train)
    train_stats = train_result["stats"]
    train_score = calc_score(train_stats)

    # Testでバックテスト
    test_result = runner.run(params=best_params, filters={}, df=df_test)
    test_stats = test_result["stats"]
    test_score = calc_score(test_stats)

    # 過学習チェック
    overfit_ratio = (
        train_score / test_score if test_score > 0.001 else float("inf")
    )
    is_overfit = overfit_ratio > OVERFITTING_RATIO_WARN

    wf_result = {
        "strategy_id": strategy_id,
        "symbol": symbol,
        "timeframe": timeframe,
        "best_params": best_params,
        "train": {
            "rows": len(df_train),
            "stats": train_stats,
            "score": round(train_score, 6),
        },
        "test": {
            "rows": len(df_test),
            "stats": test_stats,
            "score": round(test_score, 6),
        },
        "overfit_ratio": round(overfit_ratio, 3) if not math.isinf(overfit_ratio) else 999.0,
        "is_overfit": bool(is_overfit),
        "overfit_warning": (
            f"過学習の疑い: train_score/test_score = {overfit_ratio:.2f} > {OVERFITTING_RATIO_WARN}"
            if is_overfit else None
        ),
    }

    if is_overfit:
        logger.warning(
            "OVERFIT WARNING: %s %s %s | train_score=%.4f, test_score=%.4f, ratio=%.2f",
            strategy_id, symbol, timeframe, train_score, test_score, overfit_ratio
        )
    else:
        logger.info(
            "Walk-Forward OK: %s %s %s | train=%.4f, test=%.4f, ratio=%.2f",
            strategy_id, symbol, timeframe, train_score, test_score, overfit_ratio
        )

    return wf_result


# ---------------------------------------------------------------------------
# メインオプティマイザークラス
# ---------------------------------------------------------------------------


class FXOptimizer:
    """
    FX戦略グリッドサーチ + Walk-Forward最適化クラス。

    Attributes:
        strategy_id: 戦略ID
        symbol: 通貨ペア
        timeframe: 時間足
        data_path: OHLCVデータパス
        output_base: 結果保存ベースディレクトリ
        max_workers: 並列ワーカー数
        max_grid_size: グリッドサイズ上限
    """

    def __init__(
        self,
        strategy_id: str,
        symbol: str,
        timeframe: str,
        data_path: str,
        output_base: str = "results/optimization",
        max_workers: Optional[int] = None,
        max_grid_size: int = MAX_GRID_SIZE,
    ) -> None:
        """
        FXOptimizerを初期化する。

        Args:
            strategy_id: 戦略ID
            symbol: 通貨ペア（例: "USDJPY"）
            timeframe: 時間足（例: "1h"）
            data_path: OHLCVデータのCSVパス
            output_base: 結果保存のベースディレクトリ
            max_workers: 並列ワーカー数（Noneなら自動設定）
            max_grid_size: 最大グリッドサイズ
        """
        self.strategy_id = strategy_id
        self.symbol = symbol.upper()
        self.timeframe = timeframe
        self.data_path = data_path
        self.output_base = output_base
        self.max_workers = max_workers or min(cpu_count(), 8)
        self.max_grid_size = max_grid_size

        # 通貨ペアごとのfee_rate
        from src.backtest.fx_runner import FEE_RATE_BY_SYMBOL, DEFAULT_FEE_RATE
        self.fee_rate = FEE_RATE_BY_SYMBOL.get(self.symbol, DEFAULT_FEE_RATE)

        # 出力ディレクトリ
        self.output_dir = os.path.join(
            output_base, strategy_id, f"{self.symbol}_{timeframe}"
        )
        os.makedirs(self.output_dir, exist_ok=True)

        logger.info(
            "FXOptimizer: strategy=%s, %s %s, workers=%d",
            strategy_id, symbol, timeframe, self.max_workers
        )

    def run(self) -> Dict[str, Any]:
        """
        グリッドサーチ → Walk-Forward の完全最適化フローを実行する。

        Returns:
            Dict: {
                "best_params": {...},
                "best_score": float,
                "best_stats": {...},
                "walk_forward": {...},
                "grid_size": int,
                "elapsed_sec": float,
            }
        """
        start_time = time.time()

        logger.info(
            "=== Grid Search Start: %s %s %s ===",
            self.strategy_id, self.symbol, self.timeframe
        )

        # パラメータグリッドを取得・サンプリング
        param_grid = get_param_grid(self.strategy_id)
        if not param_grid:
            logger.warning("Empty param_grid for %s", self.strategy_id)
            return {}

        param_combos = sample_param_grid(
            param_grid, max_size=self.max_grid_size
        )
        grid_size = len(param_combos)
        logger.info("Grid size: %d combinations", grid_size)

        # データを読み込みシリアライズ（ワーカー間で共有）
        runner = FXRunner(
            strategy_id=self.strategy_id,
            symbol=self.symbol,
            timeframe=self.timeframe,
            data_path=self.data_path,
            fee_rate=self.fee_rate,
        )
        df = runner.load_data()
        # Parquet形式でシリアライズ（高速）
        import io
        buf = io.BytesIO()
        df.to_parquet(buf, index=True)
        df_bytes = buf.getvalue()

        # 並列引数リスト
        args_list = [
            (
                self.strategy_id,
                self.symbol,
                self.timeframe,
                self.data_path,
                self.fee_rate,
                params,
                df_bytes,
            )
            for params in param_combos
        ]

        # 逐次実行（Windowsのmultiprocessingスポーンオーバーヘッドを回避）
        logger.info("Starting sequential grid search (%d combos)...", grid_size)
        all_results: List[Dict[str, Any]] = []

        for i, args in enumerate(args_list):
            result = _run_single_backtest(args)
            all_results.append(result)
            if (i + 1) % 10 == 0 or (i + 1) == grid_size:
                elapsed = time.time() - start_time
                best_so_far = max(
                    (r.get("score", 0) for r in all_results), default=0
                )
                logger.info(
                    "Progress: %d/%d | %.1fs elapsed | best_score_so_far=%.4f",
                    i + 1, grid_size, elapsed, best_so_far
                )

        # 結果をCSVに保存（インクリメンタル）
        grid_csv_path = os.path.join(self.output_dir, "grid_results.csv")
        self._save_grid_csv(all_results, grid_csv_path)

        # ベストパラメータ選定
        valid_results = [r for r in all_results if r.get("score", 0) > 0 and r.get("stats")]
        if not valid_results:
            logger.warning("No valid results found for %s %s %s",
                          self.strategy_id, self.symbol, self.timeframe)
            return self._empty_result(grid_size, time.time() - start_time)

        best = max(valid_results, key=lambda r: r["score"])
        best_params = best["params"]
        best_score = best["score"]
        best_stats = best["stats"]

        logger.info(
            "Best: score=%.4f, trades=%d, win_rate=%.1f%%, PF=%.2f, monthly=%.2f%%, DD=%.2f%%",
            best_score,
            best_stats.get("total_trades", 0),
            best_stats.get("win_rate_pct", 0),
            best_stats.get("profit_factor", 0),
            best_stats.get("monthly_return_pct", 0),
            best_stats.get("max_drawdown_pct", 0),
        )

        # best_params.json 保存
        train_score = best_score
        best_params_data = {
            "strategy_id": self.strategy_id,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "best_params": best_params,
            "best_score": round(best_score, 6),
            "best_stats": best_stats,
            "grid_size": grid_size,
            "optimized_at": datetime.now().isoformat(),
        }
        best_params_path = os.path.join(self.output_dir, "best_params.json")
        _dump_json(best_params_data, best_params_path)
        logger.info("Saved best_params: %s", best_params_path)

        # Walk-Forward Analysis
        logger.info("=== Walk-Forward Analysis: %s %s %s ===",
                   self.strategy_id, self.symbol, self.timeframe)
        wf_result = run_walk_forward(
            strategy_id=self.strategy_id,
            symbol=self.symbol,
            timeframe=self.timeframe,
            data_path=self.data_path,
            best_params=best_params,
            fee_rate=self.fee_rate,
        )

        # best_params.jsonにWF結果を追加
        best_params_data["walk_forward"] = {
            "train_score": wf_result["train"]["score"],
            "test_score": wf_result["test"]["score"],
            "overfit_ratio": wf_result["overfit_ratio"],
            "is_overfit": wf_result["is_overfit"],
        }
        _dump_json(best_params_data, best_params_path)

        # walk_forward.json 保存
        wf_path = os.path.join(self.output_dir, "walk_forward.json")
        _dump_json(wf_result, wf_path)
        logger.info("Saved walk_forward: %s", wf_path)

        elapsed = time.time() - start_time
        logger.info(
            "=== Grid Search Done: %s %s %s | %.1fs ===",
            self.strategy_id, self.symbol, self.timeframe, elapsed
        )

        return {
            "strategy_id": self.strategy_id,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "best_params": best_params,
            "best_score": best_score,
            "best_stats": best_stats,
            "walk_forward": wf_result,
            "grid_size": grid_size,
            "elapsed_sec": round(elapsed, 1),
            "output_dir": self.output_dir,
        }

    def _save_grid_csv(
        self,
        results: List[Dict[str, Any]],
        path: str,
    ) -> None:
        """
        グリッドサーチ結果をCSVに保存する。

        Args:
            results: 全組合せの結果リスト
            path: 保存先CSVパス
        """
        if not results:
            return

        rows = []
        for r in results:
            row = {"score": r.get("score", 0.0)}
            row.update(r.get("params", {}))
            stats = r.get("stats", {})
            row["total_trades"] = stats.get("total_trades", 0)
            row["win_rate_pct"] = stats.get("win_rate_pct", 0.0)
            row["profit_factor"] = stats.get("profit_factor", 0.0)
            row["monthly_return_pct"] = stats.get("monthly_return_pct", 0.0)
            row["max_drawdown_pct"] = stats.get("max_drawdown_pct", 0.0)
            if "error" in r:
                row["error"] = r["error"]
            rows.append(row)

        if not rows:
            return

        # スコア降順でソート
        rows.sort(key=lambda x: x.get("score", 0), reverse=True)

        fieldnames = list(rows[0].keys())
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)

        logger.info("Grid results saved: %s (%d rows)", path, len(rows))

    def _empty_result(self, grid_size: int, elapsed: float) -> Dict[str, Any]:
        """
        結果が空の場合のデフォルトを返す。

        Args:
            grid_size: グリッドサイズ
            elapsed: 経過時間

        Returns:
            Dict: 空の結果
        """
        return {
            "strategy_id": self.strategy_id,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "best_params": {},
            "best_score": 0.0,
            "best_stats": {},
            "walk_forward": None,
            "grid_size": grid_size,
            "elapsed_sec": round(elapsed, 1),
            "output_dir": self.output_dir,
            "error": "No valid results",
        }


# ---------------------------------------------------------------------------
# ヒートマップ生成（matplotlibが利用可能な場合のみ）
# ---------------------------------------------------------------------------


def generate_heatmap(
    grid_csv_path: str,
    param1: str,
    param2: str,
    output_path: str,
    strategy_id: str = "",
) -> bool:
    """
    2パラメータのヒートマップを生成する。

    Args:
        grid_csv_path: グリッドサーチ結果CSVのパス
        param1: X軸パラメータ名
        param2: Y軸パラメータ名
        output_path: 出力PNG파スPath
        strategy_id: 戦略ID（タイトル用）

    Returns:
        bool: 生成成功なら True
    """
    try:
        import matplotlib
        matplotlib.use("Agg")  # GUIなし
        import matplotlib.pyplot as plt

        df = pd.read_csv(grid_csv_path)

        if param1 not in df.columns or param2 not in df.columns:
            logger.warning("Heatmap: params not found: %s, %s", param1, param2)
            return False

        pivot = df.pivot_table(
            values="score",
            index=param2,
            columns=param1,
            aggfunc="mean",
        )

        fig, ax = plt.subplots(figsize=(10, 8))
        im = ax.imshow(pivot.values, cmap="RdYlGn", aspect="auto")
        plt.colorbar(im, ax=ax, label="Score")

        ax.set_xticks(range(len(pivot.columns)))
        ax.set_xticklabels([f"{v:.4g}" for v in pivot.columns], rotation=45)
        ax.set_yticks(range(len(pivot.index)))
        ax.set_yticklabels([f"{v:.4g}" for v in pivot.index])

        ax.set_xlabel(param1)
        ax.set_ylabel(param2)
        ax.set_title(f"{strategy_id}: Score Heatmap ({param1} vs {param2})")

        plt.tight_layout()
        plt.savefig(output_path, dpi=100, bbox_inches="tight")
        plt.close()

        logger.info("Heatmap saved: %s", output_path)
        return True

    except ImportError:
        logger.warning("matplotlib not available, skipping heatmap")
        return False
    except Exception as exc:
        logger.warning("Heatmap generation failed: %s", exc)
        return False
