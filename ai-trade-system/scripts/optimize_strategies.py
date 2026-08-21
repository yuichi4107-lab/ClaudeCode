"""
FX戦略 パラメータ最適化 実行スクリプト（工程4）

使い方:
    # 全戦略・全組合せを最適化（デフォルト）
    python scripts/optimize_strategies.py

    # 特定の戦略のみ
    python scripts/optimize_strategies.py --strategies bb_reversion ha_trend

    # 特定の通貨ペア・時間足
    python scripts/optimize_strategies.py --symbols USDJPY --timeframes 1h 4h

    # グリッドサイズ上限を変更
    python scripts/optimize_strategies.py --max-grid 300

    # ワーカー数指定
    python scripts/optimize_strategies.py --workers 4

設計:
    - 最大60分以内に全組合せを完了させる
    - エラーが発生しても他の組合せは継続
    - 進捗ログをコンソールとファイル両方に出力
    - 結果はインクリメンタルに保存（途中で止まっても再開可能）

完了条件（工程4要件定義）:
    1. 5戦略すべてで best_params.json が生成される
    2. Walk-Forward 検証が実施される
    3. results/optimization/summary.md にサマリーが生成される
    4. ヒートマップが主要2パラメータで生成される
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

# プロジェクトルートをパスに追加
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.backtest.fx_optimizer import FXOptimizer, generate_heatmap
from src.backtest.strategies import list_strategies

# ---------------------------------------------------------------------------
# 定数
# ---------------------------------------------------------------------------

DATA_DIR = os.path.join(PROJECT_ROOT, "data", "fx", "ohlcv")
OUTPUT_BASE = os.path.join(PROJECT_ROOT, "results", "optimization")

# 戦略ごとの対応時間足（london_breakoutは1h専用）
STRATEGY_TIMEFRAMES = {
    "bb_reversion":    ["1h", "4h", "1d"],
    "mtf_confluence":  ["1h", "4h", "1d"],
    "rsi_divergence":  ["1h", "4h", "1d"],
    "london_breakout": ["1h"],
    "ha_trend":        ["1h", "4h", "1d"],
}

SYMBOLS = ["USDJPY", "EURJPY"]

# ヒートマップ対象パラメータ（戦略ごとに主要2つ）
HEATMAP_PARAMS = {
    "bb_reversion":   ("tp_pct", "sl_pct"),
    "mtf_confluence": ("sl_pct", "rr_ratio"),
    "rsi_divergence": ("rsi_oversold", "tp_pct"),
    "london_breakout": ("tp_multiplier", "hold_bars"),
    "ha_trend":       ("tp_pct", "sl_pct"),
}


# ---------------------------------------------------------------------------
# ロギング設定
# ---------------------------------------------------------------------------


def setup_logging(log_path: str, log_level: str = "INFO") -> None:
    """
    ログをコンソールとファイル両方に出力するよう設定する。

    Args:
        log_path: ログファイルパス
        log_level: ログレベル文字列
    """
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    level = getattr(logging, log_level.upper(), logging.INFO)

    handlers = [
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(log_path, mode="a", encoding="utf-8"),
    ]
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=handlers,
    )
    logger = logging.getLogger(__name__)
    logger.info("Logging initialized: %s", log_path)


# ---------------------------------------------------------------------------
# 組合せ生成
# ---------------------------------------------------------------------------


def build_task_list(
    strategies: List[str],
    symbols: List[str],
    timeframes: Optional[List[str]] = None,
) -> List[Dict[str, str]]:
    """
    最適化タスクのリストを生成する。

    Args:
        strategies: 最適化対象の戦略IDリスト
        symbols: 通貨ペアリスト
        timeframes: 時間足リスト（Noneなら戦略デフォルト）

    Returns:
        List[Dict]: {"strategy_id": ..., "symbol": ..., "timeframe": ...}
    """
    tasks = []
    for strategy_id in strategies:
        allowed_tfs = STRATEGY_TIMEFRAMES.get(strategy_id, ["1h", "4h", "1d"])
        target_tfs = timeframes if timeframes else allowed_tfs
        # 戦略の対応時間足のみ実行
        for tf in target_tfs:
            if tf not in allowed_tfs:
                continue
            for symbol in symbols:
                data_path = os.path.join(DATA_DIR, f"{symbol}_{tf}.csv")
                if not os.path.exists(data_path):
                    continue
                tasks.append({
                    "strategy_id": strategy_id,
                    "symbol": symbol,
                    "timeframe": tf,
                    "data_path": data_path,
                })
    return tasks


# ---------------------------------------------------------------------------
# サマリーレポート生成
# ---------------------------------------------------------------------------


def generate_summary(
    all_results: List[Dict[str, Any]],
    output_path: str,
    elapsed_total: float,
) -> None:
    """
    全戦略の最適化サマリーレポートをMarkdownで生成する。

    Args:
        all_results: 全タスクの最適化結果
        output_path: 保存先MDパス
        elapsed_total: 総実行時間（秒）
    """
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [
        "# FX戦略 パラメータ最適化 サマリーレポート",
        "",
        f"**実行日時**: {ts}",
        f"**総実行時間**: {elapsed_total/60:.1f}分",
        f"**総タスク数**: {len(all_results)}",
        "",
        "---",
        "",
        "## 全結果一覧",
        "",
        "| 戦略 | ペア | TF | スコア | 勝率 | PF | 月利% | MaxDD% | トレード数 | WF比率 | 過学習 | ベストスコアパラメータ (抜粋) |",
        "|------|------|----|----|------|-----|-------|--------|----------|--------|--------|------|",
    ]

    # スコア降順でソート
    sorted_results = sorted(
        [r for r in all_results if r.get("best_score", 0) > 0],
        key=lambda x: x.get("best_score", 0),
        reverse=True,
    )

    for r in sorted_results:
        stats = r.get("best_stats", {})
        wf = r.get("walk_forward", {}) or {}
        overfit_ratio = wf.get("overfit_ratio", "-")
        is_overfit = "YES" if wf.get("is_overfit", False) else "no"

        # ベストパラメータの主要項目を抜粋
        params = r.get("best_params", {})
        param_str = ", ".join(
            f"{k}={v}" for k, v in list(params.items())[:3]
        )

        lines.append(
            f"| {r.get('strategy_id','')} "
            f"| {r.get('symbol','')} "
            f"| {r.get('timeframe','')} "
            f"| {r.get('best_score', 0):.4f} "
            f"| {stats.get('win_rate_pct', 0):.1f}% "
            f"| {stats.get('profit_factor', 0):.2f} "
            f"| {stats.get('monthly_return_pct', 0):.2f} "
            f"| {stats.get('max_drawdown_pct', 0):.2f} "
            f"| {stats.get('total_trades', 0)} "
            f"| {overfit_ratio} "
            f"| {is_overfit} "
            f"| {param_str} |"
        )

    # エラー結果
    error_results = [r for r in all_results if r.get("error") or r.get("best_score", 0) == 0]
    if error_results:
        lines += [
            "",
            "### エラー・シグナルなし",
            "",
        ]
        for r in error_results:
            lines.append(
                f"- {r.get('strategy_id','')} {r.get('symbol','')} {r.get('timeframe','')}: "
                f"{r.get('error', 'No signals or zero score')}"
            )

    # 過学習サマリー
    overfit_list = [
        r for r in sorted_results
        if r.get("walk_forward", {}) and r["walk_forward"].get("is_overfit", False)
    ]
    lines += [
        "",
        "---",
        "",
        "## Walk-Forward 過学習チェック",
        "",
    ]
    if overfit_list:
        lines.append("**以下の組合せで過学習の疑いあり（train/testスコア比 > 2.0）:**")
        lines.append("")
        for r in overfit_list:
            wf = r["walk_forward"]
            lines.append(
                f"- **{r['strategy_id']} {r['symbol']} {r['timeframe']}**: "
                f"train_score={wf['train']['score']:.4f}, "
                f"test_score={wf['test']['score']:.4f}, "
                f"ratio={wf['overfit_ratio']:.2f}"
            )
    else:
        lines.append("過学習の疑いのある組合せはありません（全て ratio <= 2.0）。")

    # 戦略別ベストパラメータ（トップ3）
    lines += [
        "",
        "---",
        "",
        "## 戦略別ベストパラメータ（トップ3）",
        "",
    ]

    # 戦略ごとにグルーピング
    strategy_results: Dict[str, List[Dict]] = {}
    for r in sorted_results:
        sid = r.get("strategy_id", "unknown")
        strategy_results.setdefault(sid, []).append(r)

    for strategy_id, results in strategy_results.items():
        lines.append(f"### {strategy_id}")
        lines.append("")
        top3 = results[:3]
        for i, r in enumerate(top3, 1):
            stats = r.get("best_stats", {})
            wf = r.get("walk_forward", {}) or {}
            lines.append(
                f"**#{i}** - {r['symbol']} {r['timeframe']} "
                f"(score={r.get('best_score',0):.4f})"
            )
            lines.append(f"- 勝率: {stats.get('win_rate_pct',0):.1f}%")
            lines.append(f"- PF: {stats.get('profit_factor',0):.3f}")
            lines.append(f"- 月利: {stats.get('monthly_return_pct',0):.2f}%")
            lines.append(f"- MaxDD: {stats.get('max_drawdown_pct',0):.2f}%")
            lines.append(f"- トレード数: {stats.get('total_trades',0)}")
            lines.append(f"- WF train_score: {wf.get('train',{}).get('score','-')}")
            lines.append(f"- WF test_score: {wf.get('test',{}).get('score','-')}")
            lines.append(f"- パラメータ: `{r.get('best_params', {})}`")
            lines.append("")

    # 工程5への引き継ぎ
    lines += [
        "",
        "---",
        "",
        "## 工程5への引き継ぎ事項",
        "",
        "### ベストパラメータ（全戦略×全TF×全Pair）",
        "",
        "各戦略の `best_params.json` は以下のパスに保存されています:",
        "```",
        "results/optimization/{strategy_id}/{symbol}_{timeframe}/best_params.json",
        "```",
        "",
        "### Walk-Forward通過確認",
        "",
    ]

    pass_count = len([r for r in sorted_results if not r.get("walk_forward", {}).get("is_overfit", True)])
    total_count = len(sorted_results)
    lines.append(f"- 通過: {pass_count}/{total_count} 組合せ")
    lines.append("")
    lines.append("### 工程5で注意すべき点")
    lines.append("")
    lines.append("- rsi_divergenceは月間シグナル数が少ない傾向あり → 4h/1d足での確認推奨")
    lines.append("- london_breakoutは1h足専用であることに注意")
    lines.append("- 過学習疑い組合せは工程5のバックテストで再確認が必要")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append(f"*このレポートは工程4パラメータ最適化スクリプトにより自動生成されました。*")

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"\nSummary saved: {output_path}")


# ---------------------------------------------------------------------------
# optimization_summary.json 生成
# ---------------------------------------------------------------------------


def generate_optimization_summary_json(
    all_results: List[Dict[str, Any]],
    output_path: str,
) -> None:
    """
    全戦略のベストパラメータをまとめたJSONを生成する。

    Args:
        all_results: 全最適化結果
        output_path: 保存先JSONパス
    """
    summary = {}
    for r in all_results:
        if r.get("best_score", 0) <= 0:
            continue
        key = f"{r['strategy_id']}_{r['symbol']}_{r['timeframe']}"
        summary[key] = {
            "strategy_id": r["strategy_id"],
            "symbol": r["symbol"],
            "timeframe": r["timeframe"],
            "best_params": r.get("best_params", {}),
            "best_score": r.get("best_score", 0),
            "best_stats": r.get("best_stats", {}),
            "walk_forward": {
                "train_score": r.get("walk_forward", {}).get("train", {}).get("score", 0) if r.get("walk_forward") else 0,
                "test_score": r.get("walk_forward", {}).get("test", {}).get("score", 0) if r.get("walk_forward") else 0,
                "overfit_ratio": r.get("walk_forward", {}).get("overfit_ratio", 0) if r.get("walk_forward") else 0,
                "is_overfit": r.get("walk_forward", {}).get("is_overfit", False) if r.get("walk_forward") else False,
            },
        }

    from src.backtest.fx_optimizer import _dump_json
    _dump_json(summary, output_path)

    print(f"Optimization summary JSON saved: {output_path}")


# ---------------------------------------------------------------------------
# メイン実行
# ---------------------------------------------------------------------------


def main() -> None:
    """メインエントリーポイント。"""
    parser = argparse.ArgumentParser(
        description="FX戦略パラメータ最適化（グリッドサーチ + Walk-Forward）"
    )
    parser.add_argument(
        "--strategies",
        nargs="+",
        default=list_strategies(),
        help=f"最適化する戦略IDのリスト（デフォルト: 全戦略）",
    )
    parser.add_argument(
        "--symbols",
        nargs="+",
        default=SYMBOLS,
        help="通貨ペアのリスト（デフォルト: USDJPY EURJPY）",
    )
    parser.add_argument(
        "--timeframes",
        nargs="+",
        default=None,
        help="時間足のリスト（デフォルト: 戦略ごとの対応TF）",
    )
    parser.add_argument(
        "--max-grid",
        type=int,
        default=500,
        help="1組合せあたりの最大グリッドサイズ（デフォルト: 500）",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=None,
        help="並列ワーカー数（デフォルト: min(cpu_count, 8)）",
    )
    parser.add_argument(
        "--output-dir",
        default=OUTPUT_BASE,
        help=f"出力ベースディレクトリ（デフォルト: {OUTPUT_BASE}）",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING"],
    )
    args = parser.parse_args()

    # ロギング初期化
    log_path = os.path.join(args.output_dir, "run.log")
    setup_logging(log_path, args.log_level)
    logger = logging.getLogger(__name__)

    total_start = time.time()

    logger.info("=" * 60)
    logger.info("FX Strategy Optimization - Phase 1, Step 4")
    logger.info("Start: %s", datetime.now().isoformat())
    logger.info("Strategies: %s", args.strategies)
    logger.info("Symbols: %s", args.symbols)
    logger.info("Timeframes: %s", args.timeframes or "strategy defaults")
    logger.info("Max grid size: %d", args.max_grid)
    logger.info("=" * 60)

    # タスクリスト生成
    tasks = build_task_list(
        strategies=args.strategies,
        symbols=args.symbols,
        timeframes=args.timeframes,
    )

    logger.info("Total tasks: %d", len(tasks))

    if not tasks:
        logger.error("No tasks found. Check data files in %s", DATA_DIR)
        sys.exit(1)

    # 各タスクを順次実行（戦略間は逐次、戦略内のグリッドは並列）
    all_results = []
    completed = 0
    failed = 0

    for i, task in enumerate(tasks):
        strategy_id = task["strategy_id"]
        symbol = task["symbol"]
        timeframe = task["timeframe"]
        data_path = task["data_path"]

        elapsed_total = time.time() - total_start
        remaining_tasks = len(tasks) - i
        logger.info(
            "[%d/%d] Starting: %s %s %s (elapsed=%.1fm, remaining=%d tasks)",
            i + 1, len(tasks), strategy_id, symbol, timeframe,
            elapsed_total / 60, remaining_tasks
        )

        try:
            opt = FXOptimizer(
                strategy_id=strategy_id,
                symbol=symbol,
                timeframe=timeframe,
                data_path=data_path,
                output_base=args.output_dir,
                max_workers=args.workers,
                max_grid_size=args.max_grid,
            )
            result = opt.run()
            result["strategy_id"] = strategy_id
            result["symbol"] = symbol
            result["timeframe"] = timeframe
            all_results.append(result)

            if result.get("best_score", 0) > 0:
                completed += 1
                logger.info(
                    "[%d/%d] DONE: %s %s %s | score=%.4f | %.1fs",
                    i + 1, len(tasks), strategy_id, symbol, timeframe,
                    result["best_score"], result.get("elapsed_sec", 0)
                )

                # ヒートマップ生成
                heatmap_params = HEATMAP_PARAMS.get(strategy_id)
                if heatmap_params:
                    grid_csv = os.path.join(
                        args.output_dir,
                        strategy_id,
                        f"{symbol}_{timeframe}",
                        "grid_results.csv"
                    )
                    if os.path.exists(grid_csv):
                        heatmap_path = os.path.join(
                            args.output_dir,
                            strategy_id,
                            f"heatmap_{symbol}_{timeframe}_{heatmap_params[0]}_{heatmap_params[1]}.png"
                        )
                        generate_heatmap(
                            grid_csv_path=grid_csv,
                            param1=heatmap_params[0],
                            param2=heatmap_params[1],
                            output_path=heatmap_path,
                            strategy_id=f"{strategy_id} {symbol} {timeframe}",
                        )
            else:
                failed += 1
                logger.warning(
                    "[%d/%d] NO RESULT: %s %s %s",
                    i + 1, len(tasks), strategy_id, symbol, timeframe
                )
                all_results.append({
                    "strategy_id": strategy_id,
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "best_score": 0,
                    "best_params": {},
                    "best_stats": {},
                    "walk_forward": None,
                    "error": "No valid results",
                })

        except Exception as exc:
            failed += 1
            logger.error(
                "[%d/%d] ERROR: %s %s %s | %s",
                i + 1, len(tasks), strategy_id, symbol, timeframe, exc,
                exc_info=True
            )
            all_results.append({
                "strategy_id": strategy_id,
                "symbol": symbol,
                "timeframe": timeframe,
                "best_score": 0,
                "best_params": {},
                "best_stats": {},
                "walk_forward": None,
                "error": str(exc),
            })

        # 中間保存
        interim_path = os.path.join(args.output_dir, "optimization_summary.json")
        generate_optimization_summary_json(all_results, interim_path)

    # 総実行時間
    elapsed_total = time.time() - total_start

    logger.info("=" * 60)
    logger.info("All tasks completed!")
    logger.info("Total elapsed: %.1f min", elapsed_total / 60)
    logger.info("Completed: %d, Failed: %d, Total: %d", completed, failed, len(tasks))
    logger.info("=" * 60)

    # サマリーレポート生成
    summary_path = os.path.join(args.output_dir, "summary.md")
    generate_summary(all_results, summary_path, elapsed_total)

    # optimization_summary.json 最終版
    summary_json_path = os.path.join(args.output_dir, "optimization_summary.json")
    generate_optimization_summary_json(all_results, summary_json_path)

    # コンソールに最終サマリーを出力
    print("\n" + "=" * 60)
    print("OPTIMIZATION COMPLETE")
    print("=" * 60)
    print(f"Total time: {elapsed_total/60:.1f} min")
    print(f"Tasks: {completed} succeeded, {failed} failed, {len(tasks)} total")
    print("")

    # ベストスコアTOP5
    valid = [r for r in all_results if r.get("best_score", 0) > 0]
    valid.sort(key=lambda x: x["best_score"], reverse=True)
    print("TOP 5 Results:")
    for i, r in enumerate(valid[:5], 1):
        stats = r.get("best_stats", {})
        print(
            f"  #{i}: {r['strategy_id']} {r['symbol']} {r['timeframe']} "
            f"score={r['best_score']:.4f} "
            f"WR={stats.get('win_rate_pct',0):.1f}% "
            f"PF={stats.get('profit_factor',0):.2f} "
            f"monthly={stats.get('monthly_return_pct',0):.2f}% "
            f"DD={stats.get('max_drawdown_pct',0):.2f}%"
        )

    print(f"\nSummary: {summary_path}")
    print(f"JSON: {summary_json_path}")
    print(f"Log: {log_path}")


if __name__ == "__main__":
    # Windowsでのmultiprocessingサポート
    import multiprocessing
    multiprocessing.freeze_support()
    main()
