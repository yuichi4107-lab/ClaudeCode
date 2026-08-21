"""
ログ集計モジュール — FX Phase1 フォワードテスト用

trades_YYYYMMDD.jsonl を読み込み、期間別の損益・勝率・DDを集計する。
バックテスト期待値（パターンC）との乖離も計算する。

使い方:
    from src.forward.log_aggregator import LogAggregator

    agg = LogAggregator(log_dir="logs/forward")
    trades = agg.load_trades(start_date="2026-04-13", end_date="2026-05-13")
    result = agg.aggregate(trades)
    deviation = agg.compare_with_backtest(result)
"""

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# パターンC の期待値（backtest_report.md の pattern_C_growth より）
PATTERN_C_MONTHLY_RETURN_PCT: float = 10.24
PATTERN_C_MAX_DD_PCT: float = 0.40
PATTERN_C_MONTHLY_WIN_RATE_PCT: float = 90.0

# 戦略キーの正規化マッピング
# executor.py が出力する strategy フィールドの値をレポート用キーに変換する
_STRATEGY_NORMALIZE: Dict[str, str] = {
    "mtf_confluence": "mtf_confluence",
    "rsi_divergence": "rsi_divergence",
    "bb_reversion_USDJPY": "bb_reversion_USDJPY",
    "bb_reversion_EURJPY": "bb_reversion_EURJPY",
    # symbol/timeframe 付きの場合も対応
    "mtf_confluence:USDJPY:1h": "mtf_confluence",
    "rsi_divergence:USDJPY:4h": "rsi_divergence",
    "bb_reversion:USDJPY:1d": "bb_reversion_USDJPY",
    "bb_reversion:EURJPY:1d": "bb_reversion_EURJPY",
}

# 集計で使用する戦略一覧
_STRATEGY_KEYS = [
    "mtf_confluence",
    "rsi_divergence",
    "bb_reversion_USDJPY",
    "bb_reversion_EURJPY",
]


def _empty_strategy_stats() -> Dict[str, Any]:
    """戦略別集計の空テンプレートを返す。"""
    return {
        "total_trades": 0,
        "wins": 0,
        "losses": 0,
        "win_rate_pct": 0.0,
        "total_pnl_pct": 0.0,
        "avg_pnl_pct": 0.0,
        "profit_factor": 0.0,
        "max_drawdown_pct": 0.0,
    }


class LogAggregator:
    """
    trades_YYYYMMDD.jsonl を読み込み、期間別の損益・勝率・DDを集計する。

    Args:
        log_dir: トレードログが格納されているディレクトリ（デフォルト: logs/forward）
    """

    def __init__(self, log_dir: str = "logs/forward"):
        # 相対パスの場合はプロジェクトルートからの絶対パスに変換
        if not os.path.isabs(log_dir):
            _this_dir = os.path.dirname(__file__)
            project_root = os.path.abspath(os.path.join(_this_dir, "../.."))
            self.log_dir = os.path.join(project_root, log_dir)
        else:
            self.log_dir = log_dir

        logger.debug("LogAggregator 初期化: log_dir=%s", self.log_dir)

    # ─────────────────────────────────────────────
    # パブリックメソッド
    # ─────────────────────────────────────────────

    def load_trades(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        指定期間のトレードログを読み込む。

        Args:
            start_date: 開始日（"YYYY-MM-DD" 形式）。None の場合は全期間。
            end_date:   終了日（"YYYY-MM-DD" 形式、含む）。None の場合は全期間。

        Returns:
            トレードレコードのリスト（status が "executed" のもののみ）。
            データがない場合は空リスト。
        """
        if not os.path.isdir(self.log_dir):
            logger.info("ログディレクトリが存在しない: %s", self.log_dir)
            return []

        # 期間のパース
        start_dt: Optional[datetime] = None
        end_dt: Optional[datetime] = None
        if start_date:
            try:
                start_dt = datetime.strptime(start_date, "%Y-%m-%d").replace(
                    tzinfo=timezone.utc
                )
            except ValueError:
                logger.warning("start_date のパース失敗: %s", start_date)
        if end_date:
            try:
                # end_date は当日23:59:59まで含む
                end_dt = datetime.strptime(end_date, "%Y-%m-%d").replace(
                    tzinfo=timezone.utc
                ) + timedelta(days=1) - timedelta(seconds=1)
            except ValueError:
                logger.warning("end_date のパース失敗: %s", end_date)

        trades: List[Dict[str, Any]] = []
        log_files = sorted(
            f for f in os.listdir(self.log_dir)
            if f.startswith("trades_") and f.endswith(".jsonl")
        )

        if not log_files:
            logger.info("トレードログファイルが見つからない: %s", self.log_dir)
            return []

        for filename in log_files:
            # ファイル名の日付フィルタ（trades_YYYYMMDD.jsonl）
            try:
                date_str = filename[len("trades_"):-len(".jsonl")]
                file_dt = datetime.strptime(date_str, "%Y%m%d").replace(
                    tzinfo=timezone.utc
                )
            except (ValueError, IndexError):
                logger.debug("日付解析スキップ: %s", filename)
                continue

            if start_dt is not None and file_dt < start_dt.replace(
                hour=0, minute=0, second=0, microsecond=0
            ):
                continue
            if end_dt is not None and file_dt > end_dt.replace(
                hour=23, minute=59, second=59, microsecond=0
            ):
                continue

            filepath = os.path.join(self.log_dir, filename)
            file_trades = self._load_jsonl(filepath, start_dt, end_dt)
            trades.extend(file_trades)

        logger.info(
            "load_trades: 期間 %s〜%s で %d 件ロード",
            start_date or "全期間",
            end_date or "全期間",
            len(trades),
        )
        return trades

    def aggregate(self, trades: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        トレードリストを集計する。

        Args:
            trades: load_trades() の返り値（または同形式のリスト）

        Returns:
            集計結果 dict。トレードが0件の場合はゼロ値で返す。
        """
        # 戦略別状態の初期化
        by_strategy: Dict[str, Dict[str, Any]] = {
            k: _empty_strategy_stats() for k in _STRATEGY_KEYS
        }
        cb_triggers = {"cb1": 0, "cb2": 0, "cb3": 0, "cb4": 0}

        # 損益シリーズ（累積DD計算用）
        pnl_series: List[float] = []
        # 日付別損益集計
        daily_pnl_map: Dict[str, float] = {}

        total_gross_profit = 0.0
        total_gross_loss = 0.0
        wins = 0
        losses = 0

        # executed ステータスのトレードのみ集計
        executed_trades = [t for t in trades if t.get("status") == "executed"]

        period_start: Optional[str] = None
        period_end: Optional[str] = None

        for trade in executed_trades:
            ts = trade.get("timestamp", "")
            pnl_pct = self._extract_pnl_pct(trade)

            # 損益値が取れない場合はスキップ
            if pnl_pct is None:
                continue

            # 期間の記録
            date_str = ts[:10] if ts else ""  # "YYYY-MM-DD"
            if date_str:
                if period_start is None or date_str < period_start:
                    period_start = date_str
                if period_end is None or date_str > period_end:
                    period_end = date_str
                daily_pnl_map[date_str] = daily_pnl_map.get(date_str, 0.0) + pnl_pct

            pnl_series.append(pnl_pct)

            if pnl_pct > 0:
                wins += 1
                total_gross_profit += pnl_pct
            elif pnl_pct < 0:
                losses += 1
                total_gross_loss += abs(pnl_pct)

            # 戦略別集計
            strategy_key = self._normalize_strategy(trade)
            if strategy_key in by_strategy:
                s = by_strategy[strategy_key]
                s["total_trades"] += 1
                s["total_pnl_pct"] += pnl_pct
                if pnl_pct > 0:
                    s["wins"] += 1
                elif pnl_pct < 0:
                    s["losses"] += 1

            # CB 発動カウント
            cb_status = trade.get("cb_status", {})
            if cb_status.get("cb1"):
                cb_triggers["cb1"] += 1
            if cb_status.get("cb2"):
                cb_triggers["cb2"] += 1
            if cb_status.get("cb3"):
                cb_triggers["cb3"] += 1
            if cb_status.get("cb4_lot_modifier", 1.0) < 1.0:
                cb_triggers["cb4"] += 1

        # CB ブロックされたトレードから CB 発動もカウント
        for trade in trades:
            if trade.get("status") == "cb_blocked":
                cb_status = trade.get("cb_status", {})
                if cb_status.get("cb1"):
                    cb_triggers["cb1"] += 1
                if cb_status.get("cb2"):
                    cb_triggers["cb2"] += 1
                if cb_status.get("cb3"):
                    cb_triggers["cb3"] += 1

        total_trades = wins + losses
        win_rate = (wins / total_trades * 100) if total_trades > 0 else 0.0
        total_pnl = sum(pnl_series)
        avg_pnl = total_pnl / total_trades if total_trades > 0 else 0.0

        # プロフィットファクター
        if total_gross_loss > 0:
            profit_factor = total_gross_profit / total_gross_loss
        elif total_gross_profit > 0:
            profit_factor = float("inf")
        else:
            profit_factor = 0.0

        # 最大ドローダウン計算（累積損益のピークからの最大下落）
        max_drawdown = self._calc_max_drawdown(pnl_series)

        # 戦略別の派生指標を計算
        for s in by_strategy.values():
            n = s["total_trades"]
            s["win_rate_pct"] = (s["wins"] / n * 100) if n > 0 else 0.0
            s["avg_pnl_pct"] = s["total_pnl_pct"] / n if n > 0 else 0.0
            s["total_pnl_pct"] = round(s["total_pnl_pct"], 4)
            s["win_rate_pct"] = round(s["win_rate_pct"], 1)
            s["avg_pnl_pct"] = round(s["avg_pnl_pct"], 4)

        # 日次損益リストを日付ソート済みで作成
        daily_pnl = [
            {"date": d, "pnl_pct": round(pnl, 4)}
            for d, pnl in sorted(daily_pnl_map.items())
        ]

        return {
            "total_trades": total_trades,
            "wins": wins,
            "losses": losses,
            "win_rate_pct": round(win_rate, 1),
            "total_pnl_pct": round(total_pnl, 4),
            "avg_pnl_pct": round(avg_pnl, 4),
            "max_drawdown_pct": round(max_drawdown, 4),
            "profit_factor": round(profit_factor, 2) if profit_factor != float("inf") else 9999.99,
            "by_strategy": by_strategy,
            "cb_triggers": cb_triggers,
            "daily_pnl": daily_pnl,
            "period_start": period_start or "",
            "period_end": period_end or "",
        }

    def compare_with_backtest(self, aggregated: Dict[str, Any]) -> Dict[str, Any]:
        """
        バックテスト期待値（パターンC）との乖離を計算する。

        期間が1ヶ月未満の場合は日次リターンから月利を推定する。

        Args:
            aggregated: aggregate() の返り値

        Returns:
            乖離分析 dict。
        """
        total_pnl = aggregated.get("total_pnl_pct", 0.0)
        max_dd = aggregated.get("max_drawdown_pct", 0.0)
        period_start = aggregated.get("period_start", "")
        period_end = aggregated.get("period_end", "")

        # 期間日数から月利換算（30日=1ヶ月として換算）
        period_days = self._calc_period_days(period_start, period_end)
        if period_days > 0:
            monthly_return_actual = total_pnl / period_days * 30
        else:
            monthly_return_actual = 0.0

        # 乖離率の計算（期待値に対する乖離の割合）
        if PATTERN_C_MONTHLY_RETURN_PCT != 0:
            monthly_return_deviation_pct = (
                (monthly_return_actual - PATTERN_C_MONTHLY_RETURN_PCT)
                / PATTERN_C_MONTHLY_RETURN_PCT
                * 100
            )
        else:
            monthly_return_deviation_pct = 0.0

        if PATTERN_C_MAX_DD_PCT != 0:
            max_dd_deviation_pct = (
                (max_dd - PATTERN_C_MAX_DD_PCT)
                / PATTERN_C_MAX_DD_PCT
                * 100
            )
        else:
            max_dd_deviation_pct = 0.0

        return {
            "monthly_return_expected": PATTERN_C_MONTHLY_RETURN_PCT,
            "monthly_return_actual": round(monthly_return_actual, 2),
            "monthly_return_deviation_pct": round(monthly_return_deviation_pct, 1),
            "max_dd_expected": PATTERN_C_MAX_DD_PCT,
            "max_dd_actual": round(max_dd, 2),
            "max_dd_deviation_pct": round(max_dd_deviation_pct, 1),
        }

    # ─────────────────────────────────────────────
    # プライベートメソッド
    # ─────────────────────────────────────────────

    def _load_jsonl(
        self,
        filepath: str,
        start_dt: Optional[datetime],
        end_dt: Optional[datetime],
    ) -> List[Dict[str, Any]]:
        """JSONL ファイルを読み込み、期間フィルタを適用して返す。"""
        trades = []
        try:
            with open(filepath, encoding="utf-8") as f:
                for lineno, line in enumerate(f, 1):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError as e:
                        logger.warning(
                            "JSONL パースエラー: %s 行 %d: %s", filepath, lineno, e
                        )
                        continue

                    # タイムスタンプフィルタ
                    ts = record.get("timestamp", "")
                    if ts and (start_dt is not None or end_dt is not None):
                        try:
                            record_dt = datetime.strptime(
                                ts, "%Y-%m-%dT%H:%M:%SZ"
                            ).replace(tzinfo=timezone.utc)
                        except ValueError:
                            # タイムスタンプ形式が異なる場合はスキップせず含める
                            record_dt = None

                        if record_dt is not None:
                            if start_dt is not None and record_dt < start_dt:
                                continue
                            if end_dt is not None and record_dt > end_dt:
                                continue

                    trades.append(record)

        except OSError as e:
            logger.error("ファイル読み込みエラー: %s: %s", filepath, e)

        return trades

    @staticmethod
    def _extract_pnl_pct(trade: Dict[str, Any]) -> Optional[float]:
        """
        トレードレコードから損益率 (%) を取得する。

        1. pnl_pct キーが存在すればそのまま使用（決済済みレコード）
        2. pnl_pct が無い場合は price/sl/tp/side から推定計算する
           - BUY: tp到達時 = +(tp - price) / price * 100
                  sl到達時 = -(price - sl) / price * 100
                  推定値  = RR比に基づく期待損益（勝率50%仮定で中間値）
           - SELL: 逆方向で同様に計算

        注: 推定値は実損益ではない。決済結果が記録されるまでの暫定値として使用する。

        Returns:
            損益率（%）。計算不能な場合は None。
        """
        # 1. 明示的な pnl_pct があればそのまま使用
        pnl = trade.get("pnl_pct")
        if pnl is not None:
            try:
                return float(pnl)
            except (TypeError, ValueError):
                pass

        # 2. price/sl/tp/side から推定
        try:
            price = float(trade.get("price", 0))
            sl = trade.get("sl")
            tp = trade.get("tp")
            side = trade.get("side", "").upper()

            if price <= 0 or sl is None or tp is None or not side:
                return None

            sl = float(sl)
            tp = float(tp)

            if side == "BUY":
                win_pnl = (tp - price) / price * 100
                loss_pnl = (sl - price) / price * 100  # 負の値
            elif side == "SELL":
                win_pnl = (price - tp) / price * 100
                loss_pnl = (price - sl) / price * 100  # 負の値
            else:
                return None

            # 推定損益 = 勝ち・負けの中間値（バックテストの勝率を反映した推定）
            # 保守的に勝率50%で計算
            estimated_pnl = (win_pnl + loss_pnl) / 2
            return round(estimated_pnl, 4)

        except (TypeError, ValueError, ZeroDivisionError):
            return None

    @staticmethod
    def _normalize_strategy(trade: Dict[str, Any]) -> str:
        """
        トレードレコードから戦略キーを正規化して返す。

        strategy + symbol + timeframe の組み合わせから
        集計用キー（mtf_confluence, rsi_divergence, bb_reversion_USDJPY, bb_reversion_EURJPY）
        に変換する。
        """
        strategy = trade.get("strategy", "")
        symbol = trade.get("symbol", "")

        # strategy:symbol:timeframe の組み合わせキーを試す
        timeframe = trade.get("timeframe", "")
        compound_key = f"{strategy}:{symbol}:{timeframe}"
        if compound_key in _STRATEGY_NORMALIZE:
            return _STRATEGY_NORMALIZE[compound_key]

        # strategy のみで試す
        if strategy in _STRATEGY_NORMALIZE:
            return _STRATEGY_NORMALIZE[strategy]

        # bb_reversion は symbol で区別
        if "bb_reversion" in strategy or strategy == "bb_reversion":
            if "EUR" in symbol:
                return "bb_reversion_EURJPY"
            return "bb_reversion_USDJPY"

        return strategy

    @staticmethod
    def _calc_max_drawdown(pnl_series: List[float]) -> float:
        """
        累積損益シリーズから最大ドローダウン（%）を計算する。

        ピーク（累積損益の高値）からの最大下落幅を返す。

        Args:
            pnl_series: 時系列順の損益率リスト（%単位）

        Returns:
            最大ドローダウン（%、非負）。シリーズが空の場合は 0.0。
        """
        if not pnl_series:
            return 0.0

        cumulative = 0.0
        peak = 0.0
        max_dd = 0.0

        for pnl in pnl_series:
            cumulative += pnl
            if cumulative > peak:
                peak = cumulative
            dd = peak - cumulative
            if dd > max_dd:
                max_dd = dd

        return max_dd

    @staticmethod
    def _calc_period_days(start_date: str, end_date: str) -> int:
        """
        開始日・終了日の文字列から期間日数を計算する。

        Args:
            start_date: "YYYY-MM-DD"
            end_date:   "YYYY-MM-DD"

        Returns:
            日数（int）。パース失敗時は 0。
        """
        if not start_date or not end_date:
            return 0
        try:
            start = datetime.strptime(start_date, "%Y-%m-%d")
            end = datetime.strptime(end_date, "%Y-%m-%d")
            delta = (end - start).days + 1  # 両端含む
            return max(delta, 1)
        except ValueError:
            return 0
