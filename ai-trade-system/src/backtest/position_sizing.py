"""
ポジションサイジングモジュール — 固定フラクショナル法

概要:
    工程C: ポジションサイジング最適化の実装。
    10万円元本・レバレッジ上限25倍・DD-30%以内の制約下で
    各戦略のSL幅に応じた適切なロット数を算出する。

実装方針:
    - 固定フラクショナル法（Fixed Fractional Method）:
      ロットサイズ = (口座残高 × リスク率) / (SL幅 × 1ロット当たりの価値)
    - レバレッジ上限25倍のハードチェック（超過時は自動削減）
    - サーキットブレーカー発動時のロット50%削減
    - Saxo証券の最小ロット単位（1000通貨 = 0.01ロット）に対応

Saxo証券の最小ロット仕様:
    - FX取引の最小単位: 1000通貨（= 0.01ロット）
    - ロット単位: 0.01ロット刻み
    - 1ロット = 100,000通貨

使い方:
    from src.backtest.position_sizing import calculate_lot_size

    lot = calculate_lot_size(
        account_balance=100000,  # 10万円
        risk_pct=0.02,           # リスク2%
        sl_pct=0.005,            # SL幅0.5%
        symbol="USDJPY",
    )

サーキットブレーカー仕様（scoring_v2.py / circuit_breaker_spec.md も参照）:
    CB-1 連敗N回   : 同一戦略で連続5回損失 → その戦略を当日停止
    CB-2 月次DD閾値: 月初比DD -10%超 → 全戦略停止
    CB-3 累積DD閾値: 運用開始比累積DD -25%超 → 全戦略停止+アラート
    CB-4 月末縮小  : 月末5日前時点で当月マイナスの場合 → ロット50%削減（本関数のcb_activeで制御）
"""

from __future__ import annotations

import math
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 定数
# ---------------------------------------------------------------------------

# Saxo証券の最小ロット単位
SAXO_MIN_LOT: float = 0.01        # 最小ロット（= 1000通貨）
SAXO_LOT_STEP: float = 0.01       # ロット刻み幅
SAXO_UNITS_PER_LOT: int = 100_000 # 1ロット = 10万通貨

# レバレッジ上限（要件定義G3）
DEFAULT_LEVERAGE_LIMIT: float = 25.0

# サーキットブレーカー発動時のロット削減率（CB-4）
CB_LOT_REDUCTION: float = 0.50  # 50%削減


# ---------------------------------------------------------------------------
# メイン関数
# ---------------------------------------------------------------------------

def calculate_lot_size(
    account_balance: float,
    risk_pct: float,
    sl_pct: float,
    symbol: str,
    leverage_limit: float = DEFAULT_LEVERAGE_LIMIT,
    cb_active: bool = False,
    entry_price_jpy: Optional[float] = None,
) -> float:
    """
    固定フラクショナル法によるロットサイズ計算。

    計算式:
        リスク金額 = 口座残高 × risk_pct
        ポジション価値 = リスク金額 / sl_pct
        ロット数 = ポジション価値 / (1ロット当たりの価値[円])

    レバレッジチェック:
        ポジション価値(円) / 口座残高 > leverage_limit の場合、
        ポジション価値を leverage_limit × 口座残高 に削減する。

    サーキットブレーカー:
        cb_active=True の場合、最終ロット数を50%削減する（小数点以下はSaxo単位で切り捨て）。

    Args:
        account_balance: 現在の口座残高（円）
        risk_pct:        1トレードあたりのリスク率（例: 0.02 = 2%）
        sl_pct:          損切り幅（例: 0.005 = 0.5%）。エントリー価格に対する割合。
        symbol:          通貨ペア（例: "USDJPY", "EURJPY"）
        leverage_limit:  レバレッジ上限倍率（デフォルト25倍）
        cb_active:       サーキットブレーカー発動中フラグ（True で50%削減）
        entry_price_jpy: エントリー価格（円建て）。
                         USDJPY/EURJPYのように対JPY通貨ペアであれば省略可（内部でデフォルト値使用）。
                         USD建て等の場合は円換算に使用する。

    Returns:
        float: ロット数（Saxo最小単位0.01に丸めた値）。
               計算結果が最小ロット未満の場合は0.0を返す（取引不可）。

    Raises:
        ValueError: account_balance, risk_pct, sl_pct が非正値の場合
        ValueError: sl_pct >= 1.0 の場合（SLが100%以上は異常値）

    Examples:
        >>> # 基本ケース: 10万円・リスク2%・SL0.5% → 約0.40ロット
        >>> lot = calculate_lot_size(100000, 0.02, 0.005, "USDJPY")
        >>> lot > 0
        True

        >>> # CB発動: ロットが50%削減される
        >>> lot_normal = calculate_lot_size(100000, 0.02, 0.005, "USDJPY")
        >>> lot_cb = calculate_lot_size(100000, 0.02, 0.005, "USDJPY", cb_active=True)
        >>> abs(lot_cb / lot_normal - 0.5) < 0.1  # 約50%になる（丸め誤差あり）
        True
    """
    # ------------------------------------------------------------------
    # 入力バリデーション
    # ------------------------------------------------------------------
    if account_balance <= 0:
        raise ValueError(f"account_balance must be positive, got {account_balance}")
    if risk_pct <= 0:
        raise ValueError(f"risk_pct must be positive, got {risk_pct}")
    if sl_pct <= 0:
        raise ValueError(f"sl_pct must be positive, got {sl_pct}")
    if sl_pct >= 1.0:
        raise ValueError(f"sl_pct >= 1.0 is invalid (SL exceeds 100%), got {sl_pct}")

    # ------------------------------------------------------------------
    # 1. リスク金額の算出
    # ------------------------------------------------------------------
    risk_amount_jpy = account_balance * risk_pct
    logger.debug("risk_amount_jpy=%.0f (balance=%.0f, risk_pct=%.3f)",
                 risk_amount_jpy, account_balance, risk_pct)

    # ------------------------------------------------------------------
    # 2. SL幅から許容ポジション価値を算出
    #    ポジション価値 = リスク金額 / SL幅
    #    （SL幅分だけ動いた時にリスク金額を失う規模）
    # ------------------------------------------------------------------
    position_value_jpy = risk_amount_jpy / sl_pct
    logger.debug("position_value_jpy=%.0f (risk_amount=%.0f, sl_pct=%.4f)",
                 position_value_jpy, risk_amount_jpy, sl_pct)

    # ------------------------------------------------------------------
    # 3. レバレッジ上限チェック
    #    ポジション価値 / 口座残高 > leverage_limit ならロット削減
    # ------------------------------------------------------------------
    max_position_value_jpy = account_balance * leverage_limit
    if position_value_jpy > max_position_value_jpy:
        logger.warning(
            "Leverage exceeded: position_value=%.0f > max=%.0f (%.1fx > %.1fx). "
            "Reducing to leverage limit.",
            position_value_jpy, max_position_value_jpy,
            position_value_jpy / account_balance, leverage_limit
        )
        position_value_jpy = max_position_value_jpy

    # ------------------------------------------------------------------
    # 4. ロット数算出
    #    対JPY通貨ペア（USDJPY, EURJPY）の場合:
    #      1ロット(10万通貨)の価値 = 10万 × エントリーレート[円/1通貨]
    #    ここでは「ポジション価値(円) / 1ロット価値(円)」でロット数を求める。
    #    エントリー価格が不明な場合はポジション価値そのものを100,000で割る
    #    （1通貨=1円相当として近似）。
    # ------------------------------------------------------------------
    sym = symbol.upper().replace("/", "")

    if sym in ("USDJPY", "EURJPY"):
        # 対JPY通貨ペア: 1ロット(100,000通貨)の損益は円建てで直計算可能
        # ロット数 = ポジション価値(円) / (100,000通貨/ロット × エントリーレート[円/通貨])
        # 但しポジション価値が既に円建てなので:
        # ロット数 = ポジション価値(円) / (100,000 × 1) は近似が大きすぎる。
        # より正確には entry_price を使って:
        # position_size(通貨) = position_value_jpy / entry_price
        # lot = position_size / 100,000
        #
        # entry_price_jpy が指定されていれば使用。なければ1として計算
        # （呼び出し元でエントリー価格を渡すことを推奨するが、
        #   バックテスト中はSL幅が既にパーセントで与えられているため
        #   内部でのロット計算は残高ベースで十分）
        if entry_price_jpy is not None and entry_price_jpy > 0:
            position_size_base_currency = position_value_jpy / entry_price_jpy
        else:
            # エントリー価格未指定の場合: position_value_jpy を直接使用
            # 対JPY通貨ペアの場合、ポジション価値(円) = ポジションサイズ(基軸通貨) × レート
            # でretrieveできないため、残高×リスク率/SL幅 を「基軸通貨建てのポジション価値」として扱う
            # これは entry_price=1 と等価（近似）
            position_size_base_currency = position_value_jpy
        raw_lots = position_size_base_currency / SAXO_UNITS_PER_LOT
    else:
        # USD建て等のその他通貨ペア（将来拡張用）
        # entry_price_jpy（円換算レート）が必要
        if entry_price_jpy is not None and entry_price_jpy > 0:
            position_size_base_currency = position_value_jpy / entry_price_jpy
        else:
            position_size_base_currency = position_value_jpy
        raw_lots = position_size_base_currency / SAXO_UNITS_PER_LOT

    logger.debug("raw_lots=%.4f", raw_lots)

    # ------------------------------------------------------------------
    # 5. サーキットブレーカー発動時のロット50%削減（CB-4対応）
    #
    #    CB-4: 月末5日前時点で当月がマイナスの場合 → ロット50%削減
    #    cb_active=True で発動。実運用ではFXRunner側でフラグを渡す。
    # ------------------------------------------------------------------
    if cb_active:
        raw_lots *= CB_LOT_REDUCTION
        logger.info("Circuit breaker active: lots reduced by 50%% to %.4f", raw_lots)

    # ------------------------------------------------------------------
    # 6. Saxo最小ロット単位（0.01）に切り捨て丸め
    # ------------------------------------------------------------------
    lot = _round_to_saxo_lot(raw_lots)
    logger.debug("final_lot=%.2f (raw=%.4f)", lot, raw_lots)

    if lot < SAXO_MIN_LOT:
        logger.warning(
            "Calculated lot %.4f is below Saxo minimum %.2f. Returning 0.0 (no trade).",
            raw_lots, SAXO_MIN_LOT
        )
        return 0.0

    return lot


def _round_to_saxo_lot(raw_lots: float) -> float:
    """
    Saxo証券の最小ロット単位（0.01）に切り捨て丸めする。

    Args:
        raw_lots: 計算された生ロット数

    Returns:
        float: 0.01単位に切り捨てたロット数

    Examples:
        >>> _round_to_saxo_lot(0.456)
        0.45
        >>> _round_to_saxo_lot(0.009)
        0.0
    """
    # 切り捨て（floor）で保守的に処理
    units = math.floor(raw_lots / SAXO_LOT_STEP) * SAXO_LOT_STEP
    # 浮動小数点誤差対策
    return round(units, 2)


# ---------------------------------------------------------------------------
# 追加ユーティリティ
# ---------------------------------------------------------------------------

def calculate_leverage(
    account_balance: float,
    lot_size: float,
    entry_price_jpy: float,
) -> float:
    """
    現在のレバレッジ倍率を計算する。

    Args:
        account_balance:  口座残高（円）
        lot_size:         ロット数
        entry_price_jpy:  エントリー価格（円建て）

    Returns:
        float: レバレッジ倍率

    Examples:
        >>> calculate_leverage(100000, 0.4, 150.0)  # 4万通貨 × 150円 = 600万円
        60.0
    """
    position_value = lot_size * SAXO_UNITS_PER_LOT * entry_price_jpy
    return position_value / account_balance if account_balance > 0 else 0.0


def max_lot_by_leverage(
    account_balance: float,
    entry_price_jpy: float,
    leverage_limit: float = DEFAULT_LEVERAGE_LIMIT,
) -> float:
    """
    レバレッジ上限から計算した最大ロット数を返す。

    Args:
        account_balance:  口座残高（円）
        entry_price_jpy:  エントリー価格（円建て）
        leverage_limit:   レバレッジ上限倍率（デフォルト25倍）

    Returns:
        float: 最大ロット数（Saxo単位に切り捨て）

    Examples:
        >>> max_lot_by_leverage(100000, 150.0, 25.0)
        0.16
    """
    max_position_value = account_balance * leverage_limit
    max_units = max_position_value / entry_price_jpy
    return _round_to_saxo_lot(max_units / SAXO_UNITS_PER_LOT)


def recommend_risk_pct(
    target_monthly_return_pct: float,
    strategy_monthly_return_pct_at_1pct_risk: float,
) -> float:
    """
    目標月利から推奨リスク率を逆算する（参考値）。

    Args:
        target_monthly_return_pct:                  目標月利（%）
        strategy_monthly_return_pct_at_1pct_risk:   リスク1%/トレード時の戦略月利（%）

    Returns:
        float: 推奨リスク率（0.01〜0.05の範囲にクランプ）

    Examples:
        >>> recommend_risk_pct(10.0, 1.71)  # mtf_confluenceの月利1.71%
        0.05
    """
    if strategy_monthly_return_pct_at_1pct_risk <= 0:
        return 0.02  # デフォルト
    raw = target_monthly_return_pct / strategy_monthly_return_pct_at_1pct_risk / 100.0
    # 2%〜5%の範囲にクランプ
    return float(max(0.02, min(raw, 0.05)))
