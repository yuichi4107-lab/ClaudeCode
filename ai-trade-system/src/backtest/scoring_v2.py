"""
スコアリング関数 v2 — 期待値ベース

概要:
    前バージョン（勝率×0.4 + PF×0.3 + 月利×0.2 + (1-DD/10)×0.1）は
    勝率に過剰な重みを置いた結果、期待値マイナスのパラメータが選定された
    （例: bb_reversion 勝率57% / PF=0.951 / 月利=-0.165%）。

    v2 は期待値（EV）を主軸とし、PF・月利・DDのハードフィルターを設けることで
    「儲からないパラメータを確実に排除する」設計に変更する。

インターフェース:
    score_v2(stats: dict) -> float

    入力: FXRunner._calc_stats() が返す dict（またはそれと互換の dict）
    出力: 0.0〜1.0 の float（高いほど優良。失格条件該当時は 0.0）

必須キー:
    - profit_factor        (float): プロフィットファクター
    - monthly_return_pct   (float): 月次平均リターン（%表記、例: 10.5）
    - max_drawdown_pct     (float): 最大ドローダウン（%表記、例: 15.0）
    - win_rate_pct         (float): 勝率（%表記、例: 57.0）
    - avg_win_pct          (float, optional): 平均利益（%表記）。なければ 0 扱い
    - avg_loss_pct         (float, optional): 平均損失（%表記、正値で渡す）。なければ 0 扱い

Python バージョン: 3.11+

---
サーキットブレーカー仕様（詳細は circuit_breaker_spec.md を参照）:
    CB-1 連敗N回      : 同一戦略で連続5回損失 → その戦略を当日停止
    CB-2 月次DD閾値   : 月初比DD -10%超過 → 全戦略停止
    CB-3 累積DD閾値   : 運用開始比累積DD -25%超過 → 全戦略停止+アラート
    CB-4 月末縮小     : 月末5日前時点で当月マイナスの場合 → ロット50%削減
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# ハードフィルター定数
# ---------------------------------------------------------------------------

PF_MIN: float = 1.5          # PF がこの値未満なら即失格
MONTHLY_RETURN_MIN: float = 0.0   # 月利がこの値未満（マイナス）なら即失格
MAX_DD_LIMIT: float = 30.0   # ドローダウンがこの値超過なら即失格

# ---------------------------------------------------------------------------
# スコア重み（合計 = 1.0）
# ---------------------------------------------------------------------------

WEIGHT_MONTHLY_RETURN: float = 0.40  # 月利（最重要）
WEIGHT_PF: float = 0.30              # プロフィットファクター
WEIGHT_EV: float = 0.20              # 期待値（EV）
WEIGHT_DD: float = 0.10              # ドローダウン最小化

# ---------------------------------------------------------------------------
# 正規化基準値
# ---------------------------------------------------------------------------

MONTHLY_RETURN_FULL: float = 10.0   # 月利 10% で満点
PF_FULL_OFFSET: float = 2.0         # PF-1.0 の 2.0（つまり PF=3.0）で満点
EV_FULL: float = 0.5                # EV 0.5% で満点


def score_v2(stats: dict) -> float:
    """
    期待値ベーススコアリング関数 v2。

    FXRunner._calc_stats() が返す stats dict（またはそれと互換の dict）を受け取り、
    0.0〜1.0 のスコアを返す。失格条件に一つでも該当すれば 0.0 を返す。

    Args:
        stats: バックテスト統計 dict。必須キーは以下の通り:
            - profit_factor      (float): プロフィットファクター
            - monthly_return_pct (float): 月次平均リターン（%表記）
            - max_drawdown_pct   (float): 最大ドローダウン（%表記、正値）
            - win_rate_pct       (float): 勝率（%表記）
            - avg_win_pct        (float, optional): 平均利益（%表記）
            - avg_loss_pct       (float, optional): 平均損失（%表記、正値）

    Returns:
        float: 0.0〜1.0 のスコア。失格時は 0.0。

    Examples:
        >>> stats = {
        ...     "profit_factor": 2.0,
        ...     "monthly_return_pct": 8.0,
        ...     "max_drawdown_pct": 12.0,
        ...     "win_rate_pct": 55.0,
        ...     "avg_win_pct": 0.6,
        ...     "avg_loss_pct": 0.4,
        ... }
        >>> score = score_v2(stats)
        >>> 0.0 < score <= 1.0
        True

        >>> # 失格ケース: PF < 1.5
        >>> score_v2({"profit_factor": 0.951, "monthly_return_pct": -0.165,
        ...           "max_drawdown_pct": 10.0, "win_rate_pct": 57.0})
        0.0
    """
    pf = float(stats["profit_factor"])
    monthly_return = float(stats["monthly_return_pct"])
    max_dd = float(stats["max_drawdown_pct"])
    win_rate = float(stats["win_rate_pct"]) / 100.0
    avg_win = float(stats.get("avg_win_pct", 0) or 0)
    avg_loss = float(stats.get("avg_loss_pct", 0) or 0)

    # ------------------------------------------------------------------
    # ハードフィルター（失格条件）
    # どれか一つでも該当したら 0.0 を即返す
    # ------------------------------------------------------------------
    if pf < PF_MIN:
        return 0.0
    if monthly_return < MONTHLY_RETURN_MIN:
        return 0.0
    if max_dd > MAX_DD_LIMIT:
        return 0.0

    # ------------------------------------------------------------------
    # 期待値計算（%ベース）
    # EV = 勝率 × 平均利益 - (1 - 勝率) × 平均損失
    # avg_loss は正値で受け取る前提
    # ------------------------------------------------------------------
    ev = win_rate * avg_win - (1.0 - win_rate) * avg_loss

    # ------------------------------------------------------------------
    # スコア合成（各コンポーネントは 0.0〜1.0 にクランプ）
    # ------------------------------------------------------------------
    score = (
        WEIGHT_MONTHLY_RETURN * min(monthly_return / MONTHLY_RETURN_FULL, 1.0)
        + WEIGHT_PF * min((pf - 1.0) / PF_FULL_OFFSET, 1.0)
        + WEIGHT_EV * min(max(ev, 0.0) / EV_FULL, 1.0)
        + WEIGHT_DD * (1.0 - max_dd / MAX_DD_LIMIT)
    )

    # 浮動小数点誤差による微小な範囲外をクランプ
    return float(max(0.0, min(score, 1.0)))
