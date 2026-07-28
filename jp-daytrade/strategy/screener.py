"""
スクリーニングエンジン。

J-Quants Free プランで取得できる日足データのみを使ぁ、
F1 / F3 / F4 / F5(プロキシ) / 加点3 を実装する。
F2（時価総額）・F6ほF7 はデータ制約でスキップ（ログ出力あり）。
適時開示フラグ（加点1）は将来対応のため常に False。

先読みバイアス防止:
    エントリー判定（F1〜F5）にはすべて「前日までのデータ」を使う。
    当日 Open は判定後に参照してよいが、当日 High / Low / Close は判定禁止。
"""

from __future__ import annotations

import logging
import os
import warnings
from typing import Optional

import pandas as pd

try:
    from .config import SCREENING_CONFIG
except ImportError:
    # 直接実行時やテスト時の fallback（パッケージ外からのロード）
    import importlib.util as _ilu
    import pathlib as _pl
    _cfg_path = _pl.Path(__file__).parent / "config.py"
    _spec = _ilu.spec_from_file_location("strategy_config", _cfg_path)
    _cfg_mod = _ilu.module_from_spec(_spec)
    _spec.loader.exec_module(_cfg_mod)
    SCREENING_CONFIG = _cfg_mod.SCREENING_CONFIG

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# DB パス解決
# ---------------------------------------------------------------------------

def _get_data_dir() -> str:
    """環境変数 JP_DAYTRADE_DATA_DIR からデータディレクトリを取得する。"""
    data_dir = os.environ.get("JP_DAYTRADE_DATA_DIR", "C:/dev/jp-daytrade-data")
    return data_dir.rstrip("/\\")


def _prices_db_path() -> str:
    return os.path.join(_get_data_dir(), "daily_prices.db")


def _master_db_path() -> str:
    return os.path.join(_get_data_dir(), "stocks_master.db")


# ---------------------------------------------------------------------------
# データロード
# ---------------------------------------------------------------------------

def load_prices(db_path: Optional[str] = None) -> pd.DataFrame:
    """
    daily_prices テーブルを全件ロードして DataFrame を返す。

    Returns
    -------
    pd.DataFrame
        columns: code, date(datetime), open, high, low, close, volume, turnover, adjustment_factor
        index: 連番
    """
    import sqlite3

    path = db_path or _prices_db_path()
    with sqlite3.connect(path) as con:
        df = pd.read_sql_query(
            "SELECT code, date, open, high, low, close, volume, turnover, adjustment_factor "
            "FROM daily_prices ORDER BY code, date",
            con,
            parse_dates=["date"],
        )
    logger.info("loaded %d rows from daily_prices (%s)", len(df), path)
    return df


def load_master(db_path: Optional[str] = None) -> pd.DataFrame:
    """
    stocks_master テーブルから is_value_stock=0 の銘柄を返す。

    Returns
    -------
    pd.DataFrame
        columns: code, name, market, last_price, unit_shares, is_value_stock
    """
    import sqlite3

    path = db_path or _master_db_path()
    with sqlite3.connect(path) as con:
        df = pd.read_sql_query(
            "SELECT code, name, market, last_price, unit_shares, is_value_stock "
            "FROM stocks_master",
            con,
        )
    logger.info("loaded %d stocks from stocks_master (%s)", len(df), path)
    return df


# ---------------------------------------------------------------------------
# フィルター関数
# ---------------------------------------------------------------------------

def apply_f1_price(
    master: pd.DataFrame,
    cfg: Optional[dict] = None,
) -> pd.DataFrame:
    """
    F1: 株価 ≤ 3,000円 かつ 単元代金 ≤ 30万円（is_value_stock=0 で判定）。

    対象市場: グロース市場のみ（戦略仕様: グロース市場中心）。
    市場名に「グロース」が含まれる銘柄をフィルターする。

    Parameters
    ----------
    master : pd.DataFrame
        stocks_master 全体
    cfg : dict, optional
        設定辞書（省略時は SCREENING_CONFIG を使用）

    Returns
    -------
    pd.DataFrame
        フィルター通過銘柄で  stocks_master（グロース市場 + is_value_stock=0）
    """
    _ = cfg or SCREENING_CONFIG
    # グロース市場のみに絞る（戦略仕杆通り）
    growth_mask = master["market"].str.contains("グロース", na=False)
    filtered = master[growth_mask & (master["is_value_stock"] == 0)].copy()
    logger.debug(
        "F1: %d -> %d stocks (growth market + price/unit filter)",
        len(master), len(filtered),
    )
    return filtered


def apply_f2_market_cap_skip(cfg: Optional[dict] = None) -> None:
    """
    F2: 時価総額フィルター。

    データ未提供のため暫定コルスト。呼び出凷時に WARNING を出力する。
    """
    c = cfg or SCREENING_CONFIG
    if not c.get("market_cap_available", False):
        warnings.warn(
            "F2 (市価総額フィルター) はデータ未提供のためスキップします。"
            "将来 market_cap データが取得できたら SCREENING_CONFIG.market_cap_available=True に変更してください。",
            UserWarning,
            stacklevel=2,
        )
        logger.warning(
            "F2 SKIPPED: market_cap data not available. "
            "Filter range %s–%s 億円 is NOT applied.",
            c.get("market_cap_min_billion"),
            c.get("market_cap_max_billion"),
        )


def compute_intraday_range(
    prices: pd.DataFrame,
    days: int = 5,
) -> pd.DataFrame:
    """
    各銘柄ほ各日の「直近 N 日間の日中値幃率平均」を計算する。

    日中値幃率 = (high - low) / close

    先読みバイアス注意:
        当日の high/low/close は当日終了後にしか確誜だしていため、
        当日を含む N 日ローリングではなく、前日までの N 日」を使う。
        実装上は shift(1) した後に rolling(N).mean() を適用する。

    Parameters
    ----------
    prices : pd.DataFrame
        load_prices() の返り値（code, date, high, low, close を含む）
    days : int
        ローリング日数

    Returns
    -------
    pd.DataFrame
        prices に列 `intraday_range_avg` を追加したもの
    """
    prices = prices.sort_values(["code", "date"]).copy()
    prices["intraday_range"] = (prices["high"] - prices["low"]) / prices["close"]
    # shift(1): 前日以前のデータのみを使う（先読み防止）
    prices["intraday_range_avg"] = (
        prices.groupby("code")["intraday_range"]
        .transform(lambda s: s.shift(1).rolling(days, min_periods=days).mean())
    )
    return prices


def apply_f3_intraday_range(
    prices: pd.DataFrame,
    cfg: Optional[dict] = None,
) -> pd.DataFrame:
    """
    F3: 直近5日日中値幃率（(high-low)/close の5日平均）≥ 5%。

    Parameters
    ----------
    prices : pd.DataFrame
        `intraday_range_avg` 列を含む DataFrame（compute_intraday_range の出力）

    Returns
    -------
    pd.DataFrame
        F3 条件を満たす行のみ
    """
    c = cfg or SCREENING_CONFIG
    threshold = c["intraday_range_min"]
    filtered = prices[prices["intraday_range_avg"] >= threshold]
    logger.debug("F3: %d -> %d rows (intraday_range >= %.1f%%)",
                 len(prices), len(filtered), threshold * 100)
    return filtered


def compute_prev_volume(prices: pd.DataFrame) -> pd.DataFrame:
    """
    前日出来高（volume_prev）列を追加する。

    先読み防止: shift(1) で前日値を取得する。
    """
    prices = prices.sort_values(["code", "date"]).copy()
    prices["volume_prev"] = prices.groupby("code")["volume"].transform(
        lambda s: s.shift(1)
    )
    return prices


def apply_f4_volume(
    prices: pd.DataFrame,
    cfg: Optional[dict] = None,
) -> pd.DataFrame:
    """
    F4: 前日出来高 ≥ 100万株。

    Parameters
    ----------
    prices : pd.DataFrame
        `volume_prev` 列を含む DataFrame

    Returns
    -------
    pd.DataFrame
        F4 条件を満たす行のみ
    """
    c = cfg or SCREENING_CONFIG
    threshold = c["volume_min"]
    filtered = prices[prices["volume_prev"] >= threshold]
    logger.debug("F4: %d -> %d rows (prev_volume >= %d)",
                 len(prices), len(filtered), threshold)
    return filtered


def compute_gap_rate(prices: pd.DataFrame) -> pd.DataFrame:
    """
    GAP 率（当日 Open / 前日 Close - 1） を計算する。

    先読み防止:
        前日 Close は shift(1) で取得。
        当日 Open は約定価格として使うのではなくフィルターに判定にのみ使用する
        （エントリー判定後に参照するため先読みにはならない）。

    Note
    ----
    F5 に「8:59 時点の買気配 / 前日終値 - 1」が本来の仕様だが、
    日足のみのデータでは寄り付き価格（Open）で代用する。
    """
    prices = prices.sort_values(["code", "date"]).copy()
    prices["prev_close"] = prices.groupby("code")["close"].transform(
        lambda s: s.shift(1)
    )
    prices["gap_rate"] = prices["open"] / prices["prev_close"] - 1
    return prices


def apply_f5_gap_rate(
    prices: pd.DataFrame,
    cfg: Optional[dict] = None,
) -> pd.DataFrame:
    """
    F5 (パロキシ): GAP 率（当日 Open / 前日 Close - 1）≥ +3%。

    本来は 8:59 時点の買気配 / 前日終値 が、日足で代用。

    Parameters
    ----------
    prices : pd.DataFrame
        `gap_rate` 列を含む DataFrame

    Returns
    -------
    pd.DataFrame
        F5 条件を満たす行のみ
    """
    c = cfg or SCREENING_CONFIG
    threshold = c["gap_rate_min"]
    filtered = prices[prices["gap_rate"] >= threshold]
    logger.debug("F5: %d -> %d rows (gap_rate >= %.1f%%)",
                 len(prices), len(filtered), threshold * 100)
    return filtered


def compute_volume_ratio_week_ago(prices: pd.DataFrame) -> pd.DataFrame:
    """
    前週同日比出来高倍率（volume_ratio_week_ago）を計算する。

    概盬: 5ㅬ開日前の出来高を「前週同日」とする（厳密な旗日一致は不要）。

    先読み防止: 前週の出来高がないので当然当日より前のデータ。
    """
    prices = prices.sort_values(["code", "date"]).copy()
    prices["volume_5d_ago"] = prices.groupby("code")["volume"].transform(
        lambda s: s.shift(5)
    )
    # 分母ゼチェック
    prices["volume_ratio_week_ago"] = prices["volume_prev"] / prices["volume_5d_ago"].replace(0, float("nan"))
    return prices


def compute_bonus_score(prices: pd.DataFrame, cfg: Optional[dict] = None) -> pd.DataFrame:
    """
    加点スコァ（bonus_score）を計算する。

    加点1: 適時開示幁（・洲っ → 常に False￩.将来対応）
    加点3: 前日出来高前週同日比 ≥ 200%

    Parameters
    ----------
    prices : pd.DataFrame
        `volume_ratio_week_ago` 列を含む DataFrame

    Returns
    -------
    pd.DataFrame
        `bonus_score` 列を追加した DataFrame
    """
    c = cfg or SCREENING_CONFIG
    ratio_threshold = c["volume_ratio_vs_week_ago_min"]

    prices = prices.copy()
    # 加点1: データ未整備のため常に 0
    prices["bonus_disclosure"] = 0
    # 加点3: 前日出来高が前週同日比 ≥ 200%
    prices["bonus_volume_ratio"] = (
        prices["volume_ratio_week_ago"] >= ratio_threshold
    ).astype(int)

    prices["bonus_score"] = prices["bonus_disclosure"] + prices["bonus_volume_ratio"]
    logger.debug(
        "bonus_score: disclosure always 0 (data not available), "
        "volume_ratio threshold=%.1fx",
        ratio_threshold,
    )
    return prices


# ---------------------------------------------------------------------------
# ライブ専用フィルター（バックテストスキップ）
# ---------------------------------------------------------------------------

def apply_f6_presale_ratio_live_only(is_backtest: bool = True) -> None:
    """
    F6: 寄り前売買比率ゕィルター（ライブ専用）。

    バックテスト時は常にスキップ。
    """
    if is_backtest:
        logger.debug("F6 SKIPPED (live_only=True): presale ratio filter not applied in backtest.")


def apply_f7_board_depth_live_only(is_backtest: bool = True) -> None:
    """
    F7: 板厚みフィルター（ライブ専用）。

    バックテスト時は常にスキップ。
    """
    if is_backtest:
        logger.debug("F7 SKIPPED (live_only=True): board depth filter not applied in backtest.")


# ---------------------------------------------------------------------------
# スクリーニングパイプライン（1日分）
# ---------------------------------------------------------------------------

def screen_for_date(
    target_date: pd.Timestamp,
    prices_all: pd.DataFrame,
    eligible_codes: set[str],
    cfg: Optional[dict] = None,
    is_backtest: bool = True,
) -> pd.DataFrame:
    """
    指定日のスクリーニングを実行し、エントリー候補を返す。

    Parameters
    ----------
    target_date : pd.Timestamp
        当日（エントリー対象日）
    prices_all : pd.DataFrame
        load_prices() にフィルター計算列を付加した完全 DataFrame
        （intraday_range_avg, volume_prev, gap_rate, volume_ratio_week_ago, bonus_score を含む）
    eligible_codes : set[str]
        F1 通過銘柄コードのセット
    cfg : dict, optional
        設定辞書
    is_backtest : bool
        True の場合 F6 / F7 をスキップ

    Returns
    -------
    pd.DataFrame
        当日のエントリー候補（bonus_score 降順でソート済み）
        columns: code, date, open, high, low, close, volume, intraday_range_avg,
                 volume_prev, gap_rate, volume_ratio_week_ago, bonus_score
    """
    c = cfg or SCREENING_CONFIG

    # ライブ専用フィルターのスキップを明示
    apply_f6_presale_ratio_live_only(is_backtest)
    apply_f7_board_depth_live_only(is_backtest)

    # 当日の行を抽出
    day_df = prices_all[prices_all["date"] == target_date].copy()

    # F1: eligible_codes でフィルタ
    day_df = day_df[day_df["code"].isin(eligible_codes)]

    # F2: スキップ（警告は pipeline 起動時に 1 度だけ出す）

    # F3: 日中値幅率
    day_df = day_df[day_df["intraday_range_avg"] >= c["intraday_range_min"]]

    # F4: 前日出来高
    day_df = day_df[day_df["volume_prev"] >= c["volume_min"]]

    # F5: GAP 率（プロキシ）
    day_df = day_df[day_df["gap_rate"] >= c["gap_rate_min"]]

    # NaN 除去（計算不能な初期行は除外）
    day_df = day_df.dropna(subset=["intraday_range_avg", "volume_prev", "gap_rate"])

    # bonus_score 降騆でソート
    day_df = day_df.sort_values("bonus_score", ascending=False)

    logger.info(
        "[%s] screened: %d candidates (F1=%d codes, live_only F6/F7 skipped=%s)",
        target_date.date(),
        len(day_df),
        len(eligible_codes),
        is_backtest,
    )
    return day_df.reset_index(drop=True)


# ---------------------------------------------------------------------------
# 全期間スクリーニング（バックテスト用一括）
# ---------------------------------------------------------------------------

def run_screening_pipeline(
    cfg: Optional[dict] = None,
    prices_db: Optional[str] = None,
    master_db: Optional[str] = None,
) -> tuple[pd.DataFrame, list[pd.Timestamp]]:
    """
    全期間のスクリーニング済みデータを返す。

    Returns
    -------
    prices_all : pd.DataFrame
        フィルター計算列を付加した日足データ
    trading_days : list[pd.Timestamp]
        バックテスト対象の全営業日（昇順）
    """
    c = cfg or SCREENING_CONFIG

    # データロード
    prices = load_prices(prices_db)
    master = load_master(master_db)

    # F1 通過銘柄（is_value_stock=0）を取得
    eligible_master = apply_f1_price(master, c)
    eligible_codes = set(eligible_master["code"].tolist())
    logger.info("F1: %d eligible codes", len(eligible_codes))

    # F2 スキップ警告（1 度だけ）
    apply_f2_market_cap_skip(c)

    # 計算列の付加（先読みバイアスなし）
    prices = compute_intraday_range(prices, c["intraday_range_days"])
    prices = compute_prev_volume(prices)
    prices = compute_gap_rate(prices)
    prices = compute_volume_ratio_week_ago(prices)
    prices = compute_bonus_score(prices, c)

    # 全営業日リスト（eligible_codes に属する日のみ）
    trading_days = sorted(prices["date"].unique().tolist())
    trading_days = [pd.Timestamp(d) for d in trading_days]
    logger.info("total trading days: %d", len(trading_days))

    return prices, trading_days, eligible_codes
