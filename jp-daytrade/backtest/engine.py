"""
バックテストエンジン。

寄り成り（Open で約定）→ TP/SL/大引けクローズ の保守的評価を行う。

保守的評価ルール（日䶳のみのデータ制約による近似）:
    1. Low ≤ SL 価格 → 損切優先（Low が High より先に発生したと仮定）
    2. High ≥ TP_50% 価格（SL 未到達の場合のみ）→ 0.5 量を +5% で利確
    3. High ≥ TP_100% 価格（SL 未到達の場合のみ）→ 残り 0.5 量を +10% で利確
    4. それ以外 → 当日 Close で残量クローズ（大引け）
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

import pandas as pd

try:
    from ..strategy.config import BACKTEST_CONFIG, SCREENING_CONFIG
except ImportError:
    import importlib.util as _ilu
    import pathlib as _pl
    _cfg_path = _pl.Path(__file__).parent.parent / "strategy" / "config.py"
    _spec = _ilu.spec_from_file_location("strategy_config", _cfg_path)
    _cfg_mod = _ilu.module_from_spec(_spec)
    _spec.loader.exec_module(_cfg_mod)
    BACKTEST_CONFIG = _cfg_mod.BACKTEST_CONFIG
    SCREENING_CONFIG = _cfg_mod.SCREENING_CONFIG

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# データクラス
# ---------------------------------------------------------------------------

@dataclass
class Trade:
    """1 取引の記録。"""

    date: str
    code: str
    open_price: float       # 当日始値（エントリー参照価格）
    entry_price: float      # エントリー価格（スリッページ適用後）
    close_price_day: float  # 当日終値
    high: float             # 当日高値
    low: float              # 当日安値

    sl_price: float         # 損切価格
    tp1_price: float        # 第1利確価格（+5%）
    tp2_price: float        # 第2利確価格（+10%）

    exit_price_full: float  # フルクローズ時の実効価格（スリッページ適用後）
    exit_price_tp1: float   # TP1 エグジット価格（スリッページ適用後）
    exit_price_tp2: float   # TP2 エグジット価格（スリッページ適用後）

    exit_reason: str        # "SL" / "TP1+Close" / "TP1+TP2" / "Close"
    pnl_pct: float          # PnL (%) 対エントリー価格
    pnl_abs: float          # PnL (円) 対投入資金

    shares: float           # 購入株数
    invested: float         # 投入資金（円）
    bonus_score: float      # スクリーニングスコア

    # 寄り天判定: 当日 Open が当日 High と一致（±スリッページ 0.1%）
    is_yori_ten: bool = field(default=False)


@dataclass
class BacktestResult:
    """バックテスト全体の結果。"""

    trades: list[Trade]
    daily_pnl: pd.Series        # 日次損益（%）
    equity_curve: pd.Series     # 累積資産カーブ

    # 集計指標
    total_trades: int = 0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    sharpe_ratio: float = 0.0
    max_drawdown: float = 0.0
    expected_value: float = 0.0
    yori_ten_rate: float = 0.0   # 寄り天発生率
    final_capital: float = 0.0


# ---------------------------------------------------------------------------
# エグジットロジック
# ---------------------------------------------------------------------------

def _apply_slippage(price: float, direction: str, slippage: float) -> float:
    """
    スリッページを適用する。

    Parameters
    ----------
    price : float
        スリッページ適用前の価格
    direction : str
        "buy" → 高い方向（エントリー）/ "sell" → 低い方向（エグジッヘ）
    slippage : float
        スリッページ率（例: 0.001 = 0.1%）
    """
    if direction == "buy":
        return price * (1 + slippage)
    else:
        return price * (1 - slippage)


def simulate_trade(
    row: pd.Series,
    invested: float,
    cfg: Optional[dict] = None,
) -> Trade:
    """
    1 銘柄・1 日の取引シミュレーションを実行する。

    Parameters
    ----------
    row : pd.Series
        スクリーニング済みの 1 行（date, code, open, high, low, close, bonus_score を含む）
    invested : float
        このポジションに投入する資金（円）
    cfg : dict, optional
        バックテスト設定（省略時は BACKTEST_CONFIG）

    Returns
    -------
    Trade
        取引記録
    """
    c = cfg or BACKTEST_CONFIG
    slippage = c["slippage"]
    tp1_pct = c["tp1_pct"]
    tp1_ratio = c["tp1_ratio"]
    tp2_pct = c["tp2_pct"]
    sl_pct = c["sl_pct"]

    open_price: float = float(row["open"])
    high: float = float(row["high"])
    low: float = float(row["low"])
    close: float = float(row["close"])
    date_str: str = str(row["date"].date()) if hasattr(row["date"], "date") else str(row["date"])
    code: str = str(row["code"])
    bonus_score: float = float(row.get("bonus_score", 0))

    # エントリー価格（スリッページ: 買い→高め）
    entry_price = _apply_slippage(open_price, "buy", slippage)

    # 購入株数（投入資金 / エントリー価格、端数切り捨て）
    shares = invested / entry_price
    # 実際の投入資金（株数 × エントリー価格）
    actual_invested = shares * entry_price

    # TP / SL 価格（エントリー価格基準）
    tp1_price = entry_price * (1 + tp1_pct)
    tp2_price = entry_price * (1 + tp2_pct)
    sl_price = entry_price * (1 + sl_pct)

    # エグジット価格（スリッページ: 売り→低め）
    exit_sl = _apply_slippage(sl_price, "sell", slippage)
    exit_tp1 = _apply_slippage(tp1_price, "sell", slippage)
    exit_tp2 = _apply_slippage(tp2_price, "sell", slippage)
    exit_close = _apply_slippage(close, "sell", slippage)

    # ---------------------------------------------------------------------------
    # 保守的評価ルール:
    #   Step1. Low ≤ SL 価格 → 損切優先（Low が先に発生）
    #   Step2. High ≥ TP1 かつ High ≥ TP2 → TP1(50%) + TP2(50%)
    #   Step3. High ≥ TP1 のみ → TP1(50%) + Close(50%)
    #   Step4. それ以外 → Close(100%)
    # ---------------------------------------------------------------------------

    if low <= sl_price:
        # SL ヒット → 全量損切
        exit_reason = "SL"
        pnl_pct = (exit_sl - entry_price) / entry_price
        pnl_abs = actual_invested * pnl_pct

        exit_price_full = exit_sl
        exit_price_tp1 = exit_sl  # 未使用だが記録用
        exit_price_tp2 = exit_sl

    elif high >= tp2_price:
        # TP1(50%) + TP2(50%) 両方到達
        exit_reason = "TP1+TP2"
        pnl_pct = (
            tp1_ratio * (exit_tp1 - entry_price) / entry_price
            + (1 - tp1_ratio) * (exit_tp2 - entry_price) / entry_price
        )
        pnl_abs = actual_invested * pnl_pct

        exit_price_full = exit_tp2  # 残量のエグジット
        exit_price_tp1 = exit_tp1
        exit_price_tp2 = exit_tp2

    elif high >= tp1_price:
        # TP1(50%) のみ到達、残り 50% は大引けクローズ
        exit_reason = "TP1+Close"
        pnl_pct = (
            tp1_ratio * (exit_tp1 - entry_price) / entry_price
            + (1 - tp1_ratio) * (exit_close - entry_price) / entry_price
        )
        pnl_abs = actual_invested * pnl_pct

        exit_price_full = exit_close
        exit_price_tp1 = exit_tp1
        exit_price_tp2 = exit_close  # 到達せず大引け

    else:
        # TP1 未到達 → 全量大引けクローズ
        exit_reason = "Close"
        pnl_pct = (exit_close - entry_price) / entry_price
        pnl_abs = actual_invested * pnl_pct

        exit_price_full = exit_close
        exit_price_tp1 = exit_close  # 未到達
        exit_price_tp2 = exit_close

    # 寄り天判定: Open が High と一致（±0.1%）= 寄り付き直後に天井
    yori_ten_threshold = 0.001
    is_yori_ten = abs(open_price - high) / max(high, 1e-9) <= yori_ten_threshold

    return Trade(
        date=date_str,
        code=code,
        open_price=open_price,
        entry_price=entry_price,
        close_price_day=close,
        high=high,
        low=low,
        sl_price=sl_price,
        tp1_price=tp1_price,
        tp2_price=tp2_price,
        exit_price_full=exit_price_full,
        exit_price_tp1=exit_price_tp1,
        exit_price_tp2=exit_price_tp2,
        exit_reason=exit_reason,
        pnl_pct=pnl_pct,
        pnl_abs=pnl_abs,
        shares=shares,
        invested=actual_invested,
        bonus_score=bonus_score,
        is_yori_ten=is_yori_ten,
    )


# ---------------------------------------------------------------------------
# バックテストループ
# ---------------------------------------------------------------------------

def run_backtest(
    prices_all: pd.DataFrame,
    trading_days: list[pd.Timestamp],
    eligible_codes: set[str],
    screening_cfg: Optional[dict] = None,
    backtest_cfg: Optional[dict] = None,
) -> BacktestResult:
    """
    全期間バックテストを実行する。

    Parameters
    ----------
    prices_all : pd.DataFrame
        フィルター計算列を付加した日足データ（screener.run_screening_pipeline の出力）
    trading_days : list[pd.Timestamp]
        全営業日リスト
    eligible_codes : set[str]
        F1 通過銘柄コードのセット
    screening_cfg : dict, optional
        スクリーニング設定
    backtest_cfg : dict, optional
        バックテスト設定

    Returns
    -------
    BacktestResult
    """
    try:
        from ..strategy.screener import screen_for_date
        from ..strategy.config import SCREENING_CONFIG as _SC, BACKTEST_CONFIG as _BC
    except ImportError:
        import importlib.util as _ilu
        import pathlib as _pl
        _base = _pl.Path(__file__).parent.parent / "strategy"
        _s = _ilu.spec_from_file_location("screener", _base / "screener.py")
        _m = _ilu.module_from_spec(_s)
        _s.loader.exec_module(_m)
        screen_for_date = _m.screen_for_date
        _c = _ilu.spec_from_file_location("config", _base / "config.py")
        _cm = _ilu.module_from_spec(_c)
        _c.loader.exec_module(_cm)
        _SC = _cm.SCREENING_CONFIG
        _BC = _cm.BACKTEST_CONFIG
    SCREENING_CONFIG = _SC
    BACKTEST_CONFIG = _BC

    sc = screening_cfg or SCREENING_CONFIG
    bc = backtest_cfg or BACKTEST_CONFIG

    initial_capital = bc["initial_capital"]
    max_positions = bc["max_positions"]
    pos_ratio = bc["position_size_ratio"]

    capital = initial_capital
    trades: list[Trade] = []
    daily_pnl_list: list[tuple[str, float]] = []  # (date, pnl_abs)

    for day in trading_days:
        # 当日のスクリーニング
        candidates = screen_for_date(
            target_date=day,
            prices_all=prices_all,
            eligible_codes=eligible_codes,
            cfg=sc,
            is_backtest=True,
        )

        if candidates.empty:
            daily_pnl_list.append((str(day.date()), 0.0))
            continue

        # 上位 max_positions 銘柄を選択
        selected = candidates.head(max_positions)

        day_pnl_abs = 0.0
        for _, row in selected.iterrows():
            invested = capital * pos_ratio
            trade = simulate_trade(row, invested, bc)
            trades.append(trade)
            day_pnl_abs += trade.pnl_abs
            logger.info(
                "[%s] %s: entry=%.0f exit=%s pnl=%.2f%% invested=%.0f",
                trade.date, trade.code, trade.entry_price,
                trade.exit_reason, trade.pnl_pct * 100, trade.invested,
            )

        capital += day_pnl_abs
        daily_pnl_list.append((str(day.date()), day_pnl_abs))

    # ---------------------------------------------------------------------------
    # 集計
    # ---------------------------------------------------------------------------
    result = _compute_metrics(trades, daily_pnl_list, initial_capital, capital)
    return result


def _compute_metrics(
    trades: list[Trade],
    daily_pnl_list: list[tuple[str, float]],
    initial_capital: float,
    final_capital: float,
) -> BacktestResult:
    """
    取引リストから集計指標を計算する。

    Parameters
    ----------
    trades : list[Trade]
    daily_pnl_list : list[tuple[str, float]]
        (date_str, daily_pnl_abs) のリスト
    initial_capital : float
    final_capital : float

    Returns
    -------
    BacktestResult
    """
    dates = [d for d, _ in daily_pnl_list]
    pnl_abs_list = [p for _, p in daily_pnl_list]

    daily_pnl = pd.Series(pnl_abs_list, index=pd.to_datetime(dates), name="daily_pnl_abs")

    # 累積資産カーブ
    equity_curve = daily_pnl.cumsum() + initial_capital

    total_trades = len(trades)

    if total_trades == 0:
        return BacktestResult(
            trades=trades,
            daily_pnl=daily_pnl,
            equity_curve=equity_curve,
            total_trades=0,
        )

    pnl_pcts = [t.pnl_pct for t in trades]
    wins = [p for p in pnl_pcts if p > 0]
    losses = [p for p in pnl_pcts if p <= 0]

    win_rate = len(wins) / total_trades if total_trades > 0 else 0.0

    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

    expected_value = sum(pnl_pcts) / total_trades if total_trades > 0 else 0.0

    # シャープレシオ: 日次収益率（絶対値をエクイティで割った）の年換算
    daily_return_pct = daily_pnl / initial_capital
    mean_r = daily_return_pct.mean()
    std_r = daily_return_pct.std()
    sharpe_ratio = (mean_r / std_r * (252 ** 0.5)) if std_r > 0 else 0.0

    # 最大ドローダウン
    rolling_max = equity_curve.cummax()
    drawdown = (equity_curve - rolling_max) / rolling_max
    max_drawdown = float(drawdown.min())

    # 寄り天発生率
    yori_ten_count = sum(1 for t in trades if t.is_yori_ten)
    yori_ten_rate = yori_ten_count / total_trades if total_trades > 0 else 0.0

    logger.info("=== Backtest Summary ===")
    logger.info("Total trades: %d", total_trades)
    logger.info("Win rate: %.2f%%", win_rate * 100)
    logger.info("Profit factor: %.3f", profit_factor)
    logger.info("Sharpe ratio: %.3f", sharpe_ratio)
    logger.info("Max drawdown: %.2f%%", max_drawdown * 100)
    logger.info("Expected value: %.4f", expected_value)
    logger.info("Yori-ten rate: %.2f%%", yori_ten_rate * 100)

    return BacktestResult(
        trades=trades,
        daily_pnl=daily_pnl,
        equity_curve=equity_curve,
        total_trades=total_trades,
        win_rate=win_rate,
        profit_factor=profit_factor,
        sharpe_ratio=sharpe_ratio,
        max_drawdown=max_drawdown,
        expected_value=expected_value,
        yori_ten_rate=yori_ten_rate,
        final_capital=final_capital,
    )
