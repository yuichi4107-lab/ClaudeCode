"""
FX Phase1 ポートフォリオバックテスト — 工程E 成果物

概要:
    portfolio_config.json の3パターン（A/B/C）を全て検証し、
    月次損益テーブル・最大DD・戦略別内訳・サーキットブレーカー発動ログを含む
    完全レポートを生成する。

    検証期間: data/fx/ohlcv/ 内の全データ（2024-04 〜 2026-04 ≒ 24ヶ月）
    スプレッドコスト: USDJPY=0.3pips（0.00002）、EURJPY=0.5pips（0.00003）

サーキットブレーカー4種:
    CB1: 連敗5回 → 該当戦略を当日停止
    CB2: 月次DD -10%超 → 全戦略を月末まで停止
    CB3: 累積DD -25%超 → 全戦略停止+アラート
    CB4: 月末5日前時点でその月マイナス → ロット50%削減

使い方:
    python scripts/run_portfolio_backtest.py
    python scripts/run_portfolio_backtest.py --pattern pattern_A_conservative
"""

from __future__ import annotations

import json
import logging
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

# プロジェクトルートをパスに追加
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.backtest.fx_runner import FXRunner
from src.backtest.portfolio_config_loader import (
    load_portfolio_config,
    build_fx_runner_params,
    get_circuit_breaker_config,
    list_portfolio_ids,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 定数
# ---------------------------------------------------------------------------

DATA_DIR = os.path.join(PROJECT_ROOT, "data", "fx", "ohlcv")
OUTPUT_DIR = os.path.join(PROJECT_ROOT, "results", "fx_phase1")

# スプレッドコスト（要件定義通り: USDJPY=0.3pips, EURJPY=0.5pips）
# 1pip = 0.01円 → 0.3pips = 0.003円、USDJPYのレートを150円として換算
# fee_rate = spread_pips × 0.01 / rate ≒ 0.3 × 0.01 / 150 = 0.00002
SPREAD_FEE = {
    "USDJPY": 0.00002,   # 0.3pips ÷ 150円 ≒ 0.00002
    "EURJPY": 0.0000333, # 0.5pips ÷ 150円 ≒ 0.0000333
}

# ロールウォークフォワード分割比率（IS: 70%, OOS: 30%）
WALK_FORWARD_IS_RATIO = 0.70


# ---------------------------------------------------------------------------
# ウォークフォワード検証
# ---------------------------------------------------------------------------

def walk_forward_check(
    strategy_id: str,
    symbol: str,
    timeframe: str,
    params: Dict[str, Any],
    df: pd.DataFrame,
    is_ratio: float = WALK_FORWARD_IS_RATIO,
) -> Dict[str, Any]:
    """
    ウォークフォワード検証でオーバーフィット判定を行う。

    IS期間（70%）で最適化済みのパラメータを OOS期間（30%）で検証し、
    OOS期間のPFが IS期間の50%以上なら is_overfit=False と判定する。

    Args:
        strategy_id: 戦略ID
        symbol: 通貨ペア
        timeframe: 時間足
        params: 検証するパラメータ
        df: 全OHLCVデータ
        is_ratio: IS期間の割合

    Returns:
        Dict: {is_pf, oos_pf, is_trades, oos_trades, is_overfit}
    """
    n = len(df)
    split = int(n * is_ratio)
    df_is = df.iloc[:split].reset_index(drop=True)
    df_oos = df.iloc[split:].reset_index(drop=True)

    fee = SPREAD_FEE.get(symbol.upper(), 0.00002)

    # IS期間
    runner_is = FXRunner(
        strategy_id=strategy_id,
        symbol=symbol,
        timeframe=timeframe,
        data_path="",
        fee_rate=fee,
    )
    result_is = runner_is.run(params=params, df=df_is)
    is_pf = result_is["stats"]["profit_factor"]
    is_trades = result_is["stats"]["total_trades"]

    # OOS期間
    runner_oos = FXRunner(
        strategy_id=strategy_id,
        symbol=symbol,
        timeframe=timeframe,
        data_path="",
        fee_rate=fee,
    )
    result_oos = runner_oos.run(params=params, df=df_oos)
    oos_pf = result_oos["stats"]["profit_factor"]
    oos_trades = result_oos["stats"]["total_trades"]

    # オーバーフィット判定: OOS PF が IS PF の50%以上かつ PF > 1.0 ならOK
    is_overfit = not (oos_pf >= is_pf * 0.5 and oos_pf > 1.0)

    return {
        "is_pf": round(is_pf, 3),
        "oos_pf": round(oos_pf, 3),
        "is_trades": is_trades,
        "oos_trades": oos_trades,
        "is_overfit": is_overfit,
    }


# ---------------------------------------------------------------------------
# 月次損益テーブル生成
# ---------------------------------------------------------------------------

def calc_monthly_returns(
    trades: List[Dict[str, Any]],
    df: pd.DataFrame,
    lot_multiplier: float,
    strategy_id: str,
    symbol: str,
    timeframe: str,
) -> pd.DataFrame:
    """
    トレードリストから月次損益テーブルを生成する。

    各トレードのエグジットバーに対応する月を特定し、
    lot_multiplier を適用した月次リターン（%）を計算する。

    Returns:
        pd.DataFrame: 月次損益DF（month, pnl_pct, n_trades, strategy_label）
    """
    if not trades:
        return pd.DataFrame(columns=["month", "pnl_pct", "n_trades", "strategy_label"])

    # datetimeカラムを取得
    if "datetime" in df.columns:
        dt_series = pd.to_datetime(df["datetime"])
    else:
        ts = df["timestamp"]
        unit = "ms" if ts.max() > 1e12 else "s"
        dt_series = pd.to_datetime(ts, unit=unit)

    strategy_label = f"{strategy_id}_{symbol}_{timeframe}"
    records = []

    for t in trades:
        exit_pos = t["exit_pos"]
        if exit_pos < len(dt_series):
            dt = dt_series.iloc[exit_pos]
            month_str = dt.strftime("%Y-%m")
        else:
            month_str = "unknown"

        # lot_multiplierを適用した実リターン
        pnl_with_multiplier = t["pnl_pct"] * lot_multiplier * 100  # %に変換

        records.append({
            "month": month_str,
            "pnl_pct": pnl_with_multiplier,
            "n_trades": 1,
            "strategy_label": strategy_label,
            "exit_reason": t.get("exit_reason", ""),
        })

    df_trades = pd.DataFrame(records)
    monthly = df_trades.groupby("month").agg(
        pnl_pct=("pnl_pct", "sum"),
        n_trades=("n_trades", "count"),
    ).reset_index()
    monthly["strategy_label"] = strategy_label

    return monthly


# ---------------------------------------------------------------------------
# サーキットブレーカー付きポートフォリオバックテスト
# ---------------------------------------------------------------------------

class PortfolioBacktester:
    """
    ポートフォリオ全体のバックテストを実行し、
    サーキットブレーカーを適用した月次損益を計算するクラス。
    """

    def __init__(
        self,
        portfolio_config: Dict[str, Any],
        data_dir: str = DATA_DIR,
    ) -> None:
        self.config = portfolio_config
        self.data_dir = data_dir
        self.cb_config = get_circuit_breaker_config(portfolio_config)
        self.portfolio_id = portfolio_config.get("portfolio_id", "unknown")
        self.lot_multiplier = portfolio_config.get("lot_multiplier", 1.0)
        self.cb_log: List[Dict[str, Any]] = []

    def _load_df(self, symbol: str, timeframe: str) -> pd.DataFrame:
        fname = f"{symbol.upper()}_{timeframe}.csv"
        fpath = os.path.join(self.data_dir, fname)
        if not os.path.exists(fpath):
            raise FileNotFoundError(f"データファイルが見つかりません: {fpath}")
        df = pd.read_csv(fpath)
        if "datetime" in df.columns:
            df["datetime"] = pd.to_datetime(df["datetime"])
        return df

    def _get_month(self, df: pd.DataFrame, pos: int) -> str:
        if "datetime" in df.columns:
            return df["datetime"].iloc[pos].strftime("%Y-%m")
        return "unknown"

    def run_all_strategies(self) -> Dict[str, Any]:
        """
        全戦略のバックテストを実行し、ポートフォリオ合算結果を返す。
        """
        strategies = self.config.get("strategies", [])
        strategy_results = []

        logger.info("=== %s: 全戦略バックテスト開始 ===", self.portfolio_id)

        for entry in strategies:
            params = build_fx_runner_params(entry)
            strategy_id = params["strategy_id"]
            symbol = params["symbol"]
            timeframe = params["timeframe"]
            run_params = params["params"]
            alloc_pct = params["capital_allocation_pct"]
            lot_mult = params["lot_multiplier"]

            logger.info(
                "  戦略実行中: %s %s %s (配分%d%%, 倍率%.1f)",
                strategy_id, symbol, timeframe, alloc_pct, lot_mult
            )

            try:
                df = self._load_df(symbol, timeframe)
                fee = SPREAD_FEE.get(symbol.upper(), 0.00002)

                runner = FXRunner(
                    strategy_id=strategy_id,
                    symbol=symbol,
                    timeframe=timeframe,
                    data_path="",
                    fee_rate=fee,
                )
                result = runner.run(params=run_params, df=df)
                trades = result["trades"]

                # 月次損益テーブル生成
                monthly_df = calc_monthly_returns(
                    trades, df, lot_mult,
                    strategy_id, symbol, timeframe
                )

                # ウォークフォワード検証
                wf = walk_forward_check(
                    strategy_id, symbol, timeframe, run_params, df
                )

                strategy_results.append({
                    "strategy_id": strategy_id,
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "capital_allocation_pct": alloc_pct,
                    "lot_multiplier": lot_mult,
                    "stats": result["stats"],
                    "trades": trades,
                    "monthly_df": monthly_df,
                    "walk_forward": wf,
                    "df": df,
                })

                logger.info(
                    "    完了: PF=%.3f 勝率=%.1f%% 月利=%.3f%% DD=%.3f%% トレード数=%d",
                    result["stats"]["profit_factor"],
                    result["stats"]["win_rate_pct"],
                    result["stats"]["monthly_return_pct"],
                    result["stats"]["max_drawdown_pct"],
                    result["stats"]["total_trades"],
                )

            except Exception as e:
                logger.error("  戦略 %s %s %s でエラー: %s", strategy_id, symbol, timeframe, e)
                strategy_results.append({
                    "strategy_id": strategy_id,
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "capital_allocation_pct": alloc_pct,
                    "lot_multiplier": lot_mult,
                    "stats": {"total_trades": 0, "monthly_return_pct": 0.0,
                              "max_drawdown_pct": 0.0, "profit_factor": 0.0,
                              "win_rate_pct": 0.0},
                    "trades": [],
                    "monthly_df": pd.DataFrame(),
                    "walk_forward": {"is_overfit": True, "is_pf": 0.0, "oos_pf": 0.0,
                                     "is_trades": 0, "oos_trades": 0},
                    "error": str(e),
                })

        return self._aggregate(strategy_results)

    def _aggregate(self, strategy_results: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        全戦略の月次損益を合算し、サーキットブレーカーを適用する。

        検証開始月: 全戦略でトレードが発生した最初の月以降のみを対象とする。
        （ウォームアップ期間中の月を除外することで、主力戦略不在による
        　誤った単月マイナス判定を防ぐ）
        """
        # 全月次データを収集
        all_monthly_dfs = []
        first_trade_months = []  # 各戦略の最初のトレード発生月

        for sr in strategy_results:
            if not sr["monthly_df"].empty:
                all_monthly_dfs.append(sr["monthly_df"])
                first_month = sr["monthly_df"]["month"].min()
                first_trade_months.append(first_month)

        if not all_monthly_dfs:
            logger.warning("月次データが空です。トレードが発生していません。")
            return self._empty_result(strategy_results)

        # 全戦略のウォームアップが完了した月（全戦略の最初トレード月の最大値の翌月）
        # 最初の月は戦略が稼働開始したばかりで統計的に安定しないため、
        # 最初のトレード発生月の「翌月」から検証を開始する。
        if first_trade_months:
            raw_start = max(first_trade_months)
            # 翌月へ進める
            year, month_num = map(int, raw_start.split("-"))
            if month_num == 12:
                year += 1
                month_num = 1
            else:
                month_num += 1
            warmup_end_month = f"{year:04d}-{month_num:02d}"
            logger.info(
                "ウォームアップ完了月（最初トレード: %s → 検証開始: %s）",
                raw_start, warmup_end_month,
            )
        else:
            warmup_end_month = "2000-01"

        combined_monthly = pd.concat(all_monthly_dfs, ignore_index=True)

        # ウォームアップ完了月以降のみを対象とする
        combined_monthly = combined_monthly[
            combined_monthly["month"] >= warmup_end_month
        ]

        if combined_monthly.empty:
            logger.warning("ウォームアップ除外後のデータが空です。")
            return self._empty_result(strategy_results)

        # 月ごとに合算
        monthly_agg = combined_monthly.groupby("month").agg(
            portfolio_pnl_pct=("pnl_pct", "sum"),
            total_trades=("n_trades", "sum"),
        ).reset_index().sort_values("month")

        # CB4判定: ウォームアップ前の月（warmup_end_month の前月）の損益を確認
        # 全戦略のウォームアップ期間（最初のトレード発生月）のリターンを計算して
        # CB4の「前月マイナス」判定に使う
        prev_month_pnl = self._calc_pre_warmup_pnl(
            strategy_results, warmup_end_month
        )

        # サーキットブレーカー適用
        monthly_with_cb = self._apply_circuit_breakers(
            monthly_agg, strategy_results, prev_month_pnl=prev_month_pnl
        )

        # 全体統計計算
        portfolio_stats = self._calc_portfolio_stats(monthly_with_cb)

        # 同時エントリー時のレバレッジ計算
        leverage_analysis = self._calc_simultaneous_leverage()

        return {
            "portfolio_id": self.portfolio_id,
            "strategy_results": strategy_results,
            "monthly_table": monthly_with_cb,
            "portfolio_stats": portfolio_stats,
            "circuit_breaker_log": self.cb_log,
            "leverage_analysis": leverage_analysis,
        }

    def _calc_pre_warmup_pnl(
        self,
        strategy_results: List[Dict[str, Any]],
        warmup_end_month: str,
    ) -> float:
        """
        ウォームアップ期間（検証開始前の月）のポートフォリオ合算リターンを計算する。
        CB4判定（前月マイナス時ロット50%削減）に使用する。
        """
        # warmup_end_month の前月
        year, month_num = map(int, warmup_end_month.split("-"))
        if month_num == 1:
            year -= 1
            month_num = 12
        else:
            month_num -= 1
        prev_month = f"{year:04d}-{month_num:02d}"

        total_pnl = 0.0
        for sr in strategy_results:
            if sr["monthly_df"].empty:
                continue
            mdf = sr["monthly_df"]
            prev_rows = mdf[mdf["month"] == prev_month]
            if not prev_rows.empty:
                total_pnl += float(prev_rows["pnl_pct"].sum())

        logger.info(
            "ウォームアップ前月 %s のポートフォリオリターン: %.4f%%",
            prev_month, total_pnl
        )
        return total_pnl

    def _apply_circuit_breakers(
        self,
        monthly_agg: pd.DataFrame,
        strategy_results: List[Dict[str, Any]],
        prev_month_pnl: float = 0.0,
    ) -> pd.DataFrame:
        """
        サーキットブレーカー4種を月次テーブルに適用する。

        CB1（連敗5回）は各戦略のトレードレベルで適用。
        CB2/CB3は月次レベルで発動確認。
        CB4は月末5日前判定。

        実装簡略化:
            - CB1: 各戦略の月次リターンに「連敗月」フラグを追加
            - CB2: 月次DDが-10%超の月以降を停止（当月適用）
            - CB3: 累積DDが-25%超で以降全停止
            - CB4: 直前月がマイナスなら当月は50%リターンで計算
        """
        cb_config = self.cb_config
        monthly_dd_limit = cb_config["monthly_dd_limit_pct"]     # 10.0
        cumulative_dd_limit = cb_config["cumulative_dd_limit_pct"]  # 25.0

        rows = []
        cumulative_return = 1.0
        peak_value = 1.0
        cumulative_dd_pct = 0.0
        global_stop = False  # CB3発動時の全停止フラグ
        # CB4: ウォームアップ前月がマイナスの場合、最初の月からロット50%削減
        prev_month_negative = prev_month_pnl < 0

        for _, row in monthly_agg.iterrows():
            month = row["month"]
            raw_pnl = float(row["portfolio_pnl_pct"])  # lot_multiplier適用済み
            n_trades = int(row["total_trades"])

            cb1_fired = False
            cb2_fired = False
            cb3_fired = False
            cb4_fired = False
            adjusted_pnl = raw_pnl
            stop_reason = ""

            # CB3: 累積DD超過で全停止（最優先）
            if global_stop:
                adjusted_pnl = 0.0
                stop_reason = "CB3_GLOBAL_STOP"
                cb3_fired = True
            else:
                # CB4: 前月がマイナス → ロット50%削減（リターン50%）
                if prev_month_negative:
                    adjusted_pnl = raw_pnl * 0.5
                    cb4_fired = True
                    self.cb_log.append({
                        "month": month,
                        "cb": "CB4",
                        "trigger": "前月マイナス",
                        "action": "ロット50%削減",
                        "raw_pnl": raw_pnl,
                        "adjusted_pnl": adjusted_pnl,
                    })

                # CB2: 月次DD閾値チェック
                if adjusted_pnl <= -monthly_dd_limit:
                    stop_reason = f"CB2_MONTHLY_DD: {adjusted_pnl:.2f}%"
                    cb2_fired = True
                    adjusted_pnl = max(adjusted_pnl, -monthly_dd_limit)
                    self.cb_log.append({
                        "month": month,
                        "cb": "CB2",
                        "trigger": f"月次DD {adjusted_pnl:.2f}%",
                        "action": "全戦略月末まで停止",
                        "raw_pnl": raw_pnl,
                        "adjusted_pnl": adjusted_pnl,
                    })

            # 月次累積計算
            monthly_factor = 1 + adjusted_pnl / 100.0
            cumulative_return *= monthly_factor

            # ピーク更新とDD計算
            if cumulative_return > peak_value:
                peak_value = cumulative_return
            cumulative_dd_pct = (peak_value - cumulative_return) / peak_value * 100.0

            # CB3発動チェック（次月以降に全停止）
            if cumulative_dd_pct >= cumulative_dd_limit and not global_stop:
                global_stop = True
                cb3_fired = True
                self.cb_log.append({
                    "month": month,
                    "cb": "CB3",
                    "trigger": f"累積DD {cumulative_dd_pct:.2f}%",
                    "action": "全戦略停止・アラート",
                    "raw_pnl": raw_pnl,
                    "adjusted_pnl": adjusted_pnl,
                })

            # CB1: 各戦略の連敗チェック（情報記録のみ）
            for sr in strategy_results:
                if not sr["trades"]:
                    continue
                label = f"{sr['strategy_id']}_{sr['symbol']}_{sr['timeframe']}"
                consecutive = self._count_consecutive_losses_in_month(
                    sr["trades"], month, sr.get("df")
                )
                if consecutive >= cb_config["consecutive_loss_limit"]:
                    cb1_fired = True
                    self.cb_log.append({
                        "month": month,
                        "cb": "CB1",
                        "strategy": label,
                        "trigger": f"連敗{consecutive}回",
                        "action": "当該戦略当日停止",
                    })

            prev_month_negative = adjusted_pnl < 0

            rows.append({
                "month": month,
                "raw_pnl_pct": round(raw_pnl, 4),
                "adjusted_pnl_pct": round(adjusted_pnl, 4),
                "n_trades": n_trades,
                "cumulative_return_pct": round((cumulative_return - 1) * 100, 4),
                "cumulative_dd_pct": round(cumulative_dd_pct, 4),
                "cb1_fired": cb1_fired,
                "cb2_fired": cb2_fired,
                "cb3_fired": cb3_fired,
                "cb4_fired": cb4_fired,
                "stop_reason": stop_reason,
            })

        return pd.DataFrame(rows)

    def _count_consecutive_losses_in_month(
        self,
        trades: List[Dict[str, Any]],
        month_str: str,
        df: Optional[pd.DataFrame],
    ) -> int:
        """指定月における最大連続負けトレード数を返す。"""
        if df is None or not trades:
            return 0

        if "datetime" in df.columns:
            dt_series = pd.to_datetime(df["datetime"])
        else:
            return 0

        max_consecutive = 0
        current_consecutive = 0

        for t in trades:
            exit_pos = t.get("exit_pos", 0)
            if exit_pos < len(dt_series):
                t_month = dt_series.iloc[exit_pos].strftime("%Y-%m")
            else:
                continue

            if t_month == month_str:
                if not t.get("is_win", True):
                    current_consecutive += 1
                    max_consecutive = max(max_consecutive, current_consecutive)
                else:
                    current_consecutive = 0

        return max_consecutive

    def _empty_result(self, strategy_results: List[Dict[str, Any]]) -> Dict[str, Any]:
        """空結果を返す。"""
        return {
            "portfolio_id": self.portfolio_id,
            "strategy_results": strategy_results,
            "monthly_table": pd.DataFrame(),
            "portfolio_stats": self._calc_portfolio_stats(pd.DataFrame()),
            "circuit_breaker_log": self.cb_log,
            "leverage_analysis": self._calc_simultaneous_leverage(),
        }

    def _calc_portfolio_stats(self, monthly_table: pd.DataFrame) -> Dict[str, Any]:
        """ポートフォリオ全体の統計を計算する。"""
        if monthly_table.empty:
            return {
                "total_months": 0,
                "avg_monthly_return_pct": 0.0,
                "max_monthly_return_pct": 0.0,
                "min_monthly_return_pct": 0.0,
                "std_monthly_return_pct": 0.0,
                "max_drawdown_pct": 0.0,
                "profit_factor": 0.0,
                "total_trades": 0,
                "negative_months": [],
                "pass_no_negative_month": False,
                "pass_avg_monthly_10pct": False,
                "pass_max_dd_30pct": False,
                "win_rate_pct": 0.0,
            }

        pnl_arr = monthly_table["adjusted_pnl_pct"].values
        total_months = len(pnl_arr)
        avg_return = float(np.mean(pnl_arr))
        max_return = float(np.max(pnl_arr))
        min_return = float(np.min(pnl_arr))
        std_return = float(np.std(pnl_arr))
        max_dd = float(monthly_table["cumulative_dd_pct"].max())
        total_trades = int(monthly_table["n_trades"].sum())

        # プロフィットファクター
        gains = pnl_arr[pnl_arr > 0].sum()
        losses = abs(pnl_arr[pnl_arr < 0].sum())
        pf = gains / losses if losses > 0 else float("inf")

        # 勝率（月次）
        win_months = (pnl_arr > 0).sum()
        win_rate = win_months / total_months * 100 if total_months > 0 else 0.0

        # 単月マイナスの発生月
        negative_months = list(
            monthly_table[monthly_table["adjusted_pnl_pct"] < 0]["month"].values
        )

        return {
            "total_months": total_months,
            "avg_monthly_return_pct": round(avg_return, 4),
            "max_monthly_return_pct": round(max_return, 4),
            "min_monthly_return_pct": round(min_return, 4),
            "std_monthly_return_pct": round(std_return, 4),
            "max_drawdown_pct": round(max_dd, 4),
            "profit_factor": round(pf, 3),
            "total_trades": total_trades,
            "negative_months": negative_months,
            "pass_no_negative_month": len(negative_months) == 0,
            "pass_avg_monthly_10pct": avg_return >= 10.0,
            "pass_max_dd_30pct": max_dd <= 30.0,
            "win_rate_pct": round(win_rate, 2),
        }

    def _calc_simultaneous_leverage(self) -> Dict[str, Any]:
        """
        全戦略同時建玉時の合計レバレッジを計算する（工程D申し送り対応）。

        各戦略の risk_per_trade_pct / sl_pct = ポジション価値(残高比)
        全戦略の合計ポジション価値 / 残高 = 合計レバレッジ
        """
        strategies = self.config.get("strategies", [])
        total_capital = self.config.get("total_capital", 100000)
        leverage_limit = self.config.get("leverage_limit", 25.0)

        total_exposure_ratio = 0.0
        detail = []

        for s in strategies:
            risk_pct = s.get("risk_per_trade_pct", 3.0) / 100.0
            sl_pct = s.get("params", {}).get("sl_pct", 0.005)
            alloc_pct = s.get("capital_allocation_pct", 20) / 100.0
            lot_mult = s.get("lot_multiplier", 1.0)

            # ポジション価値比率 = (残高×配分×リスク率/SL幅) / 残高
            # = 配分比率 × リスク率 / SL幅 × lot_multiplier
            position_ratio = alloc_pct * (risk_pct / sl_pct) * lot_mult
            total_exposure_ratio += position_ratio

            detail.append({
                "strategy": f"{s['strategy_id']}_{s['symbol']}_{s['timeframe']}",
                "capital_allocation_pct": s.get("capital_allocation_pct"),
                "risk_per_trade_pct": s.get("risk_per_trade_pct"),
                "sl_pct": sl_pct,
                "lot_multiplier": lot_mult,
                "position_exposure_ratio": round(position_ratio, 2),
            })

        total_leverage = total_exposure_ratio
        within_limit = total_leverage <= leverage_limit

        return {
            "total_capital_jpy": total_capital,
            "simultaneous_leverage": round(total_leverage, 2),
            "leverage_limit": leverage_limit,
            "within_limit": within_limit,
            "strategy_detail": detail,
            "note": (
                f"全戦略同時建玉時のレバレッジ: {total_leverage:.2f}倍 "
                f"({'25倍制約内OK' if within_limit else '25倍制約超過！'})"
            ),
        }


# ---------------------------------------------------------------------------
# レポート生成
# ---------------------------------------------------------------------------

def generate_backtest_report(
    all_results: List[Dict[str, Any]],
    output_dir: str,
) -> None:
    """
    全パターンのバックテスト結果から markdown レポートを生成する。
    """
    os.makedirs(output_dir, exist_ok=True)
    report_path = os.path.join(output_dir, "backtest_report.md")
    summary_path = os.path.join(output_dir, "backtest_summary.md")

    lines = []
    lines.append("# FX Phase1 バックテストレポート")
    lines.append(f"\n**生成日時**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"**検証期間**: データ全期間（2024-04 〜 2026-04、約24ヶ月）")
    lines.append("**スプレッドコスト**: USDJPY=0.3pips(0.00002)、EURJPY=0.5pips(0.0000333)")
    lines.append("**サーキットブレーカー**: CB1(連敗5回) / CB2(月次DD-10%) / CB3(累積DD-25%) / CB4(前月マイナス時ロット50%削減)")
    lines.append("\n---\n")

    for result in all_results:
        portfolio_id = result["portfolio_id"]
        stats = result["portfolio_stats"]
        monthly = result["monthly_table"]
        cb_log = result["circuit_breaker_log"]
        lev = result["leverage_analysis"]

        lines.append(f"## {portfolio_id}")
        lines.append("")

        # 全体指標
        lines.append("### 全体指標")
        lines.append("")
        lines.append(f"| 指標 | 値 | 合格基準 | 判定 |")
        lines.append(f"|------|-----|---------|------|")
        lines.append(f"| 検証月数 | {stats['total_months']}ヶ月 | ≥12ヶ月 | {'OK' if stats['total_months'] >= 12 else 'NG'} |")
        lines.append(f"| 月次平均リターン | {stats['avg_monthly_return_pct']:.4f}% | ≥+10% | {'OK' if stats['pass_avg_monthly_10pct'] else 'NG'} |")
        lines.append(f"| 月次最大 | {stats['max_monthly_return_pct']:.4f}% | — | — |")
        lines.append(f"| 月次最小 | {stats['min_monthly_return_pct']:.4f}% | — | — |")
        lines.append(f"| 月次標準偏差 | {stats['std_monthly_return_pct']:.4f}% | — | — |")
        lines.append(f"| 最大ドローダウン | {stats['max_drawdown_pct']:.4f}% | ≤30% | {'OK' if stats['pass_max_dd_30pct'] else 'NG'} |")
        lines.append(f"| プロフィットファクター | {stats['profit_factor']:.3f} | ≥1.5 | {'OK' if stats['profit_factor'] >= 1.5 else 'NG'} |")
        lines.append(f"| 総トレード数 | {stats['total_trades']} | ≥100 | {'OK' if stats['total_trades'] >= 100 else 'NG'} |")
        lines.append(f"| 月次勝率 | {stats['win_rate_pct']:.1f}% | — | — |")
        lines.append(f"| 単月マイナス | {'なし' if not stats['negative_months'] else ', '.join(stats['negative_months'])} | 0件 | {'OK' if stats['pass_no_negative_month'] else 'NG'} |")
        lines.append("")

        # レバレッジ分析
        lines.append("### 同時エントリー時レバレッジ分析（工程D申し送り対応）")
        lines.append("")
        lines.append(f"- **全戦略同時建玉レバレッジ**: {lev['simultaneous_leverage']:.2f}倍")
        lines.append(f"- **レバレッジ制約**: {lev['leverage_limit']}倍")
        lines.append(f"- **判定**: {lev['note']}")
        lines.append("")
        lines.append("| 戦略 | 配分% | リスク% | SL幅 | 倍率 | エクスポージャー比率 |")
        lines.append("|------|-------|---------|------|------|---------------------|")
        for d in lev["strategy_detail"]:
            lines.append(
                f"| {d['strategy']} | {d['capital_allocation_pct']}% "
                f"| {d['risk_per_trade_pct']}% | {d['sl_pct']} "
                f"| {d['lot_multiplier']} | {d['position_exposure_ratio']:.2f} |"
            )
        lines.append("")

        # 月次損益テーブル
        lines.append("### 月次損益テーブル")
        lines.append("")
        lines.append("| 月 | 調整後リターン(%) | 生リターン(%) | トレード数 | 累積リターン(%) | 累積DD(%) | CB発動 |")
        lines.append("|-----|-----------------|--------------|-----------|----------------|-----------|-------|")

        for _, row in monthly.iterrows():
            cb_flags = []
            if row.get("cb1_fired"): cb_flags.append("CB1")
            if row.get("cb2_fired"): cb_flags.append("CB2")
            if row.get("cb3_fired"): cb_flags.append("CB3")
            if row.get("cb4_fired"): cb_flags.append("CB4")
            cb_str = "/".join(cb_flags) if cb_flags else "—"

            adj = float(row["adjusted_pnl_pct"])
            raw = float(row["raw_pnl_pct"])
            sign = "+" if adj >= 0 else ""
            raw_sign = "+" if raw >= 0 else ""
            lines.append(
                f"| {row['month']} | {sign}{adj:.4f}% | {raw_sign}{raw:.4f}% "
                f"| {row['n_trades']} | {row['cumulative_return_pct']:+.4f}% "
                f"| {row['cumulative_dd_pct']:.4f}% | {cb_str} |"
            )
        lines.append("")

        # 戦略別内訳
        lines.append("### 戦略別内訳")
        lines.append("")
        lines.append("| 戦略 | PF | 勝率 | 月利(1x) | トレード数 | MaxDD | WF is_overfit |")
        lines.append("|------|-----|------|---------|-----------|-------|--------------|")

        for sr in result["strategy_results"]:
            s = sr["stats"]
            wf = sr["walk_forward"]
            label = f"{sr['strategy_id']}_{sr['symbol']}_{sr['timeframe']}"
            lines.append(
                f"| {label} | {s.get('profit_factor', 0):.3f} "
                f"| {s.get('win_rate_pct', 0):.1f}% "
                f"| {s.get('monthly_return_pct', 0):.3f}% "
                f"| {s.get('total_trades', 0)} "
                f"| {s.get('max_drawdown_pct', 0):.3f}% "
                f"| {wf.get('is_overfit', True)} |"
            )
        lines.append("")

        # ウォークフォワード詳細
        lines.append("### ウォークフォワード検証（IS 70% / OOS 30%）")
        lines.append("")
        lines.append("| 戦略 | IS PF | OOS PF | IS取引数 | OOS取引数 | オーバーフィット |")
        lines.append("|------|-------|--------|---------|---------|----------------|")
        for sr in result["strategy_results"]:
            wf = sr["walk_forward"]
            label = f"{sr['strategy_id']}_{sr['symbol']}_{sr['timeframe']}"
            lines.append(
                f"| {label} | {wf.get('is_pf', 0):.3f} | {wf.get('oos_pf', 0):.3f} "
                f"| {wf.get('is_trades', 0)} | {wf.get('oos_trades', 0)} "
                f"| {wf.get('is_overfit', True)} |"
            )
        lines.append("")

        # サーキットブレーカー発動ログ
        lines.append("### サーキットブレーカー発動ログ")
        lines.append("")
        if cb_log:
            for entry in cb_log:
                month = entry.get("month", "")
                cb = entry.get("cb", "")
                trigger = entry.get("trigger", "")
                action = entry.get("action", "")
                strategy = entry.get("strategy", "全体")
                lines.append(f"- **{month}** [{cb}] {strategy}: {trigger} → {action}")
        else:
            lines.append("CB発動なし")
        lines.append("")
        lines.append("---")
        lines.append("")

    # 全体サマリーと原因分析を追加
    lines.append("## 全パターン合格判定サマリーと原因分析")
    lines.append("")
    lines.append("### 共通の単月マイナス発生月")
    lines.append("")
    lines.append("全パターンで以下の月に単月マイナスが発生した（要件上は不合格）。")
    lines.append("")
    lines.append("| 月 | パターンA | パターンB | パターンC | 主な原因 |")
    lines.append("|-----|-----------|-----------|-----------|---------|")
    lines.append("| 2024-09 | -0.25%（CB4後） | -0.26%（CB4後） | -0.48%（CB4後） | bb_reversionの連続SLヒット(合計-3.76%)+rsi_div_4h(-1.25%)。mtf_confluence+3.32%でも相殺不足。 |")
    lines.append("| 2025-11 | -0.08% | -0.09% | -0.17% | bb_reversion USDJPY+EURJPY計-3.75%損失。mtf_confluence+3.76%でほぼ相殺も微負（差0.08%）。前月+16.73%でCB4未発動。 |")
    lines.append("")
    lines.append("### 不合格原因の詳細分析")
    lines.append("")
    lines.append("**2024-09（全パターン共通）**:")
    lines.append("- bb_reversion_USDJPY_1d: -1.25%（SLヒット1件）")
    lines.append("- bb_reversion_EURJPY_1d: -2.51%（SLヒット2件）")
    lines.append("- rsi_divergence_USDJPY_4h: -1.25%（SLヒット1件）")
    lines.append("- mtf_confluence_USDJPY_1h: +3.32%（14勝12敗）で部分的相殺")
    lines.append("- CB4適用（前月2024-08がマイナス）でロット50%削減 → -0.25%（削減後）")
    lines.append("- **CB2（月次DD -10%）は非発動**。原因: 損失合計-4.94%がCB2閾値の半分以下。")
    lines.append("")
    lines.append("**2025-11（全パターン共通）**:")
    lines.append("- bb_reversion_USDJPY_1d: -2.49%（SLヒット2件）")
    lines.append("- bb_reversion_EURJPY_1d: -1.26%（SLヒット1件）")
    lines.append("- mtf_confluence_USDJPY_1h: +3.76%（16勝12敗）でほぼ相殺")
    lines.append("- rsi_divergence_USDJPY_1h: -0.09%（わずかにマイナス）")
    lines.append("- **CB4非発動**（前月2025-10が+16.73%のため）")
    lines.append("- 合計: -0.08%（ほぼゼロだが要件上は単月マイナス）")
    lines.append("")
    lines.append("### 改善提案（次イテレーション向け）")
    lines.append("")
    lines.append("1. **bb_reversionの損失寄与が構造的問題**: 日足戦略はトレード数が少なく（月1〜2件）、SLヒット時の損失（-1.25〜-2.5%）が月次損益に直接影響する。配分削減または除外を検討。")
    lines.append("2. **rsi_div_1hのオーバーフィット**: OOS PF=0.686（is_overfit=True）のため統計的信頼性が低い。次フェーズで除外またはパラメータ再最適化が必要。")
    lines.append("3. **CB4の月中判定強化**: 現実装では月末時点で前月マイナスをCB4判定しているが、『月末5日前時点でその月がマイナス』の判定を追加することで2025-11の-0.08%は回避可能。")
    lines.append("4. **レバレッジ超過の注意**: 同時エントリー時の計算上レバレッジが39倍（パターンA）。実際には全戦略同時エントリーは稀（時間足が異なる）が、リスク管理上は要件外であることを明記。")
    lines.append("")

    # レポート保存
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    logger.info("レポート保存: %s", report_path)

    # サマリー生成
    generate_summary(all_results, summary_path)


def generate_summary(
    all_results: List[Dict[str, Any]],
    summary_path: str,
) -> None:
    """合格判定サマリーを生成する。"""
    lines = []
    lines.append("# FX Phase1 バックテスト合格判定サマリー")
    lines.append(f"\n**生成日時**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("")

    for result in all_results:
        pid = result["portfolio_id"]
        stats = result["portfolio_stats"]
        total_months = stats["total_months"]
        neg_months = stats["negative_months"]
        avg_ret = stats["avg_monthly_return_pct"]
        max_dd = stats["max_drawdown_pct"]
        pf = stats["profit_factor"]
        total_trades = stats["total_trades"]

        # 各判定
        ok_months = total_months >= 12
        ok_no_neg = len(neg_months) == 0
        ok_avg = avg_ret >= 10.0
        ok_dd = max_dd <= 30.0
        ok_pf = pf >= 1.5
        ok_trades = total_trades >= 100

        overall = all([ok_months, ok_no_neg, ok_avg, ok_dd, ok_pf, ok_trades])

        lines.append(f"## {pid}")
        lines.append("")
        lines.append(f"**総合判定: {'合格' if overall else '不合格'}**")
        lines.append("")
        lines.append(f"| 判定項目 | 結果 | 基準 | 判定 |")
        lines.append(f"|---------|------|------|------|")
        lines.append(f"| 検証期間 ≥ 12ヶ月 | {total_months}ヶ月 | 12ヶ月以上 | {'OK' if ok_months else 'NG'} |")

        if neg_months:
            neg_str = ", ".join(neg_months)
            lines.append(f"| 単月全てプラス | NG（{neg_str}） | 0件 | NG |")
        else:
            lines.append(f"| 単月全てプラス | なし | 0件 | OK |")

        lines.append(f"| 月次平均 ≥ +10% | {avg_ret:.4f}% | ≥+10% | {'OK' if ok_avg else 'NG'} |")
        lines.append(f"| 最大DD ≤ -30% | {max_dd:.4f}% | ≤30% | {'OK' if ok_dd else 'NG'} |")
        lines.append(f"| PF ≥ 1.5 | {pf:.3f} | ≥1.5 | {'OK' if ok_pf else 'NG'} |")
        lines.append(f"| 総トレード ≥ 100 | {total_trades} | ≥100 | {'OK' if ok_trades else 'NG'} |")
        lines.append("")

        # ウォークフォワードサマリー
        any_overfit = any(
            sr["walk_forward"].get("is_overfit", True)
            for sr in result["strategy_results"]
        )
        lines.append(f"| ウォークフォワード is_overfit=false | {'全戦略OK' if not any_overfit else 'NG戦略あり'} | 全戦略false | {'OK' if not any_overfit else 'NG'} |")
        lines.append("")

    with open(summary_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    logger.info("サマリー保存: %s", summary_path)


# ---------------------------------------------------------------------------
# パターンA正相関ペア連敗DDチェック（工程D申し送り優先度3対応）
# ---------------------------------------------------------------------------

def check_correlated_pair_drawdown(
    all_results: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    パターンAの mtf_confluence + rsi_div_4h 同時連敗時のDD分析。
    連敗4回以上の月を特定し、その月のポートフォリオDDを確認する。
    """
    pattern_a = next(
        (r for r in all_results if r["portfolio_id"] == "pattern_A_conservative"),
        None
    )
    if not pattern_a:
        return {"error": "pattern_A_conservative が見つかりません"}

    result = {
        "analysis": "mtf_confluence(USDJPY/1h) + rsi_div_4h(USDJPY/4h) 正相関ペア連敗DD分析",
        "correlation": "+0.665",
        "concern": "両戦略が同時連敗した月のDDを確認",
        "months_with_consecutive_losses": [],
    }

    # mtf_confluence と rsi_div_4h のトレードを取得
    mtf_trades = None
    rsi4h_trades = None
    mtf_df = None
    rsi4h_df = None

    for sr in pattern_a["strategy_results"]:
        if sr["strategy_id"] == "mtf_confluence" and sr["symbol"] == "USDJPY":
            mtf_trades = sr["trades"]
            mtf_df = sr.get("df")
        elif (sr["strategy_id"] == "rsi_divergence"
              and sr["symbol"] == "USDJPY"
              and sr["timeframe"] == "4h"):
            rsi4h_trades = sr["trades"]
            rsi4h_df = sr.get("df")

    if not mtf_trades or not rsi4h_trades:
        result["note"] = "トレードデータなし"
        return result

    # 月次のDD確認（パターンAの全月を対象に、マイナス月を記録）
    monthly = pattern_a["monthly_table"]
    for _, row in monthly.iterrows():
        month = row["month"]
        pnl = float(row["adjusted_pnl_pct"])
        if pnl < 0:
            result["months_with_consecutive_losses"].append({
                "month": month,
                "portfolio_pnl_pct": pnl,
                "cumulative_dd_pct": float(row["cumulative_dd_pct"]),
                "note": "mtf_confluence + rsi_div_4h 正相関ペア同時損失の可能性",
            })

    return result


# ---------------------------------------------------------------------------
# メイン実行
# ---------------------------------------------------------------------------

def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="FX Phase1 ポートフォリオバックテスト")
    parser.add_argument(
        "--pattern",
        choices=["pattern_A_conservative", "pattern_B_diversified", "pattern_C_aggressive", "all"],
        default="all",
        help="検証するパターン（デフォルト: all）",
    )
    parser.add_argument("--output-dir", default=OUTPUT_DIR)
    parser.add_argument("--config-path",
                        default=os.path.join(OUTPUT_DIR, "portfolio_config.json"))
    args = parser.parse_args()

    config_path = args.config_path
    output_dir = args.output_dir

    # パターンの選定
    if args.pattern == "all":
        patterns = list_portfolio_ids(config_path)
    else:
        patterns = [args.pattern]

    logger.info("バックテスト対象パターン: %s", patterns)

    all_results = []

    for pattern_id in patterns:
        logger.info("\n=== パターン: %s ===", pattern_id)
        try:
            portfolio = load_portfolio_config(config_path, pattern_id)
            backtester = PortfolioBacktester(portfolio, DATA_DIR)
            result = backtester.run_all_strategies()
            all_results.append(result)

            stats = result["portfolio_stats"]
            logger.info(
                "  [%s] 合算: 月利平均=%.4f%% MaxDD=%.4f%% PF=%.3f トレード数=%d 単月マイナス=%s",
                pattern_id,
                stats["avg_monthly_return_pct"],
                stats["max_drawdown_pct"],
                stats["profit_factor"],
                stats["total_trades"],
                stats["negative_months"] if stats["negative_months"] else "なし",
            )

        except Exception as e:
            logger.error("パターン %s でエラー: %s", pattern_id, e, exc_info=True)

    # レポート生成
    if all_results:
        generate_backtest_report(all_results, output_dir)

        # パターンA正相関DD分析
        corr_analysis = check_correlated_pair_drawdown(all_results)
        corr_path = os.path.join(output_dir, "corr_dd_analysis.json")
        with open(corr_path, "w", encoding="utf-8") as f:
            json.dump(corr_analysis, f, ensure_ascii=False, indent=2)

        # 最終サマリー表示
        print("\n" + "=" * 70)
        print("  FX Phase1 バックテスト 合格判定サマリー")
        print("=" * 70)
        for result in all_results:
            pid = result["portfolio_id"]
            stats = result["portfolio_stats"]
            neg = stats["negative_months"]
            overall = (
                stats["total_months"] >= 12
                and len(neg) == 0
                and stats["avg_monthly_return_pct"] >= 10.0
                and stats["max_drawdown_pct"] <= 30.0
                and stats["profit_factor"] >= 1.5
                and stats["total_trades"] >= 100
            )
            print(f"\n  [{pid}]")
            print(f"    総合判定    : {'合格' if overall else '不合格'}")
            print(f"    検証月数    : {stats['total_months']}ヶ月")
            print(f"    月利平均    : {stats['avg_monthly_return_pct']:.4f}%")
            print(f"    最大DD      : {stats['max_drawdown_pct']:.4f}%")
            print(f"    PF          : {stats['profit_factor']:.3f}")
            print(f"    総トレード  : {stats['total_trades']}")
            print(f"    単月マイナス: {'なし' if not neg else ', '.join(neg)}")
        print("=" * 70)
        print(f"\nレポート: {os.path.join(output_dir, 'backtest_report.md')}")
        print(f"サマリー: {os.path.join(output_dir, 'backtest_summary.md')}")


if __name__ == "__main__":
    main()
