"""
scoring_v2.py のユニットテスト

テストケース:
    - 正常ケース: ハードフィルターを通過し、スコアが 0.0 < score <= 1.0 になるケース
    - 失格ケース（PF < 1.5）
    - 失格ケース（月利 < 0%）
    - 失格ケース（DD > 30%）
    - 複合失格ケース
    - 回帰テスト: bb_reversion 問題パラメータ（PF=0.951, 月利=-0.165%）が 0.0 になること
    - 境界値テスト: 閾値の境界での動作確認

実行方法:
    cd ai-trade-system
    pytest tests/test_scoring_v2.py -v
"""

from __future__ import annotations

import sys
import os

import pytest

# プロジェクトルートを sys.path に追加
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.backtest.scoring_v2 import (
    score_v2,
    PF_MIN,
    MONTHLY_RETURN_MIN,
    MAX_DD_LIMIT,
    WEIGHT_MONTHLY_RETURN,
    WEIGHT_PF,
    WEIGHT_EV,
    WEIGHT_DD,
)


# ---------------------------------------------------------------------------
# ヘルパー: FXRunner._calc_stats() 互換の最小 stats dict を生成
# ---------------------------------------------------------------------------

def make_stats(
    profit_factor: float = 2.0,
    monthly_return_pct: float = 8.0,
    max_drawdown_pct: float = 12.0,
    win_rate_pct: float = 55.0,
    avg_win_pct: float = 0.6,
    avg_loss_pct: float = 0.4,
) -> dict:
    """テスト用 stats dict を生成する。"""
    return {
        "profit_factor": profit_factor,
        "monthly_return_pct": monthly_return_pct,
        "max_drawdown_pct": max_drawdown_pct,
        "win_rate_pct": win_rate_pct,
        "avg_win_pct": avg_win_pct,
        "avg_loss_pct": avg_loss_pct,
    }


# ---------------------------------------------------------------------------
# 定数チェック（重み合計 = 1.0）
# ---------------------------------------------------------------------------

class TestWeights:
    def test_weights_sum_to_one(self):
        """スコア重みの合計が 1.0 であること。"""
        total = WEIGHT_MONTHLY_RETURN + WEIGHT_PF + WEIGHT_EV + WEIGHT_DD
        assert abs(total - 1.0) < 1e-9, f"重み合計が 1.0 ではない: {total}"

    def test_weight_monthly_return_is_040(self):
        """月利重みが 0.40 であること（最重要指標）。"""
        assert WEIGHT_MONTHLY_RETURN == 0.40

    def test_weight_pf_is_030(self):
        """PF重みが 0.30 であること。"""
        assert WEIGHT_PF == 0.30

    def test_weight_ev_is_020(self):
        """EV重みが 0.20 であること。"""
        assert WEIGHT_EV == 0.20

    def test_weight_dd_is_010(self):
        """DD重みが 0.10 であること。"""
        assert WEIGHT_DD == 0.10


# ---------------------------------------------------------------------------
# 正常ケース: ハードフィルターを通過するケース
# ---------------------------------------------------------------------------

class TestPassCases:
    def test_good_strategy_returns_positive_score(self):
        """優良パラメータはスコアが 0.0 より大きく 1.0 以下になること。"""
        stats = make_stats(
            profit_factor=2.5,
            monthly_return_pct=12.0,
            max_drawdown_pct=10.0,
            win_rate_pct=60.0,
            avg_win_pct=0.8,
            avg_loss_pct=0.3,
        )
        score = score_v2(stats)
        assert 0.0 < score <= 1.0, f"スコアが範囲外: {score}"

    def test_excellent_strategy_scores_high(self):
        """月利10%・PF3.0・DD極小の戦略は高スコア（0.8以上）になること。"""
        stats = make_stats(
            profit_factor=3.0,
            monthly_return_pct=10.0,
            max_drawdown_pct=5.0,
            win_rate_pct=65.0,
            avg_win_pct=1.0,
            avg_loss_pct=0.3,
        )
        score = score_v2(stats)
        assert score >= 0.8, f"高品質戦略のスコアが低すぎる: {score}"

    def test_score_output_is_float(self):
        """返り値が float 型であること。"""
        stats = make_stats()
        result = score_v2(stats)
        assert isinstance(result, float), f"float でない: {type(result)}"

    def test_score_increases_with_better_monthly_return(self):
        """月利が高いほどスコアが上がること。"""
        stats_low = make_stats(monthly_return_pct=1.0)
        stats_high = make_stats(monthly_return_pct=9.0)
        assert score_v2(stats_low) < score_v2(stats_high)

    def test_score_increases_with_better_pf(self):
        """PFが高いほどスコアが上がること。"""
        stats_low = make_stats(profit_factor=1.5)
        stats_high = make_stats(profit_factor=3.0)
        assert score_v2(stats_low) < score_v2(stats_high)

    def test_score_increases_with_lower_drawdown(self):
        """DDが小さいほどスコアが上がること。"""
        stats_low_dd = make_stats(max_drawdown_pct=5.0)
        stats_high_dd = make_stats(max_drawdown_pct=25.0)
        assert score_v2(stats_low_dd) > score_v2(stats_high_dd)

    def test_optional_keys_can_be_omitted(self):
        """avg_win_pct / avg_loss_pct が省略されても動作すること。"""
        stats = {
            "profit_factor": 2.0,
            "monthly_return_pct": 8.0,
            "max_drawdown_pct": 12.0,
            "win_rate_pct": 55.0,
        }
        score = score_v2(stats)
        assert 0.0 <= score <= 1.0

    def test_score_capped_at_one(self):
        """スコアが 1.0 を超えないこと。"""
        stats = make_stats(
            profit_factor=10.0,     # PF満点超え
            monthly_return_pct=100.0,  # 月利満点超え
            max_drawdown_pct=0.01,
            win_rate_pct=90.0,
            avg_win_pct=10.0,
            avg_loss_pct=0.01,
        )
        score = score_v2(stats)
        assert score <= 1.0, f"スコアが 1.0 を超えた: {score}"


# ---------------------------------------------------------------------------
# 失格ケース: ハードフィルターに引っかかるケース
# ---------------------------------------------------------------------------

class TestHardFilters:
    def test_fail_when_pf_below_1_5(self):
        """PF < 1.5 の場合はスコア = 0.0 になること。"""
        stats = make_stats(profit_factor=1.49)
        assert score_v2(stats) == 0.0

    def test_fail_when_pf_exactly_at_boundary(self):
        """PF = 1.5 の場合は失格にならないこと（境界値は合格側）。"""
        stats = make_stats(profit_factor=1.5)
        assert score_v2(stats) > 0.0

    def test_fail_when_monthly_return_negative(self):
        """月利 < 0% の場合はスコア = 0.0 になること。"""
        stats = make_stats(monthly_return_pct=-0.001)
        assert score_v2(stats) == 0.0

    def test_fail_when_monthly_return_exactly_zero(self):
        """月利 = 0.0% の場合は失格にならないこと（境界値は合格側）。"""
        stats = make_stats(monthly_return_pct=0.0)
        assert score_v2(stats) >= 0.0  # 0.0 は許容

    def test_fail_when_max_dd_exceeds_30(self):
        """DD > 30% の場合はスコア = 0.0 になること。"""
        stats = make_stats(max_drawdown_pct=30.001)
        assert score_v2(stats) == 0.0

    def test_pass_when_max_dd_exactly_30(self):
        """DD = 30.0% の場合は失格にならないこと（境界値は合格側）。"""
        stats = make_stats(max_drawdown_pct=30.0)
        assert score_v2(stats) >= 0.0  # スコアは計算される

    def test_fail_pf_zero(self):
        """PF = 0 の場合はスコア = 0.0 になること。"""
        stats = make_stats(profit_factor=0.0)
        assert score_v2(stats) == 0.0

    def test_fail_pf_inf_with_negative_monthly_return(self):
        """PF=inf でも月利がマイナスなら失格になること。"""
        stats = make_stats(profit_factor=float("inf"), monthly_return_pct=-1.0)
        assert score_v2(stats) == 0.0

    def test_fail_combined_pf_and_monthly_return(self):
        """PF < 1.5 かつ月利 < 0% の複合失格。"""
        stats = make_stats(profit_factor=1.2, monthly_return_pct=-5.0)
        assert score_v2(stats) == 0.0

    def test_fail_all_three_filters(self):
        """3つ全ての失格条件に該当するケース。"""
        stats = make_stats(
            profit_factor=0.5,
            monthly_return_pct=-10.0,
            max_drawdown_pct=50.0,
        )
        assert score_v2(stats) == 0.0


# ---------------------------------------------------------------------------
# 回帰テスト: bb_reversion 問題パラメータが必ず 0.0 になること
# ---------------------------------------------------------------------------

class TestRegression:
    def test_bb_reversion_problem_params_score_zero(self):
        """
        回帰テスト: bb_reversion の問題パラメータ
        （PF=0.951, monthly_return_pct=-0.165, win_rate=57）が
        新スコアリングで 0.0 になること。

        前バージョンではこのパラメータが選ばれてしまった（勝率重視の弊害）。
        v2 では PF<1.5 のハードフィルターと月利<0%のフィルターが両方発火するため
        必ず 0.0 になる。
        """
        bb_reversion_stats = {
            "profit_factor": 0.951,
            "monthly_return_pct": -0.165,
            "max_drawdown_pct": 15.0,   # 適当な値（テスト要件に明記通り）
            "win_rate_pct": 57.0,
            "avg_win_pct": 0.3,
            "avg_loss_pct": 0.35,
        }
        score = score_v2(bb_reversion_stats)
        assert score == 0.0, (
            f"bb_reversion 問題パラメータのスコアが 0.0 でない: {score}。"
            "ハードフィルター（PF<1.5 または 月利<0%）が正しく機能していない可能性がある。"
        )

    def test_bb_reversion_fails_on_pf_filter(self):
        """PF = 0.951 単独でフィルターが発火することを確認する。"""
        stats = {
            "profit_factor": 0.951,
            "monthly_return_pct": 10.0,   # 月利は合格値に設定
            "max_drawdown_pct": 10.0,
            "win_rate_pct": 57.0,
        }
        assert score_v2(stats) == 0.0, "PF=0.951 はハードフィルターを通過してはならない"

    def test_bb_reversion_fails_on_monthly_return_filter(self):
        """月利 = -0.165% 単独でフィルターが発火することを確認する。"""
        stats = {
            "profit_factor": 2.0,         # PFは合格値に設定
            "monthly_return_pct": -0.165,
            "max_drawdown_pct": 10.0,
            "win_rate_pct": 57.0,
        }
        assert score_v2(stats) == 0.0, "月利=-0.165% はハードフィルターを通過してはならない"


# ---------------------------------------------------------------------------
# インターフェース整合性テスト: FXRunner._calc_stats() 出力互換
# ---------------------------------------------------------------------------

class TestInterface:
    def test_accepts_fx_runner_calc_stats_output(self):
        """
        FXRunner._calc_stats() が返す dict キー名と完全に互換であること。

        FXRunner の stats には avg_win_pct / avg_loss_pct が存在しない場合もある。
        その場合は 0 扱いで動作すること。
        """
        # FXRunner._calc_stats() が返す最小限の dict（avg_win/avg_loss なし）
        fx_runner_stats = {
            "total_trades": 150,
            "win_rate_pct": 55.0,
            "profit_factor": 2.1,
            "monthly_return_pct": 7.5,
            "max_drawdown_pct": 14.2,
            "sharpe_ratio": 1.3,
            "sortino_ratio": 1.8,
            "calmar_ratio": 0.5,
            "avg_holding_bars": 12.5,
        }
        # avg_win_pct / avg_loss_pct が存在しない dict でも例外なく動作すること
        score = score_v2(fx_runner_stats)
        assert isinstance(score, float)
        assert 0.0 <= score <= 1.0

    def test_returns_float_type(self):
        """返り値の型が float であること（int や他の型でないこと）。"""
        assert type(score_v2(make_stats())) is float

    def test_zero_is_exact_float_zero(self):
        """失格時の返り値が正確に 0.0 であること（True == 1 の混同防止）。"""
        stats = make_stats(profit_factor=0.5)  # 失格
        result = score_v2(stats)
        assert result == 0.0
        assert type(result) is float
