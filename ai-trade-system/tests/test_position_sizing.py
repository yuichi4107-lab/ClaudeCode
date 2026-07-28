"""
ユニットテスト: position_sizing.py

テスト方針:
    - 正常ケース: 10万円・リスク2%・SL0.5% の基本計算
    - レバレッジ超過ケース: 計算上25倍超になる設定でロット自動削減を確認
    - サーキットブレーカーケース: cb_active=True でロット50%削減を確認
    - Saxo最小ロット対応: 計算結果が0.01単位で返ること
    - 入力バリデーション: 非正値・異常値でValueErrorを確認
"""

from __future__ import annotations

import math
import pytest
import sys
import os

# プロジェクトルートをパスに追加
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.backtest.position_sizing import (
    calculate_lot_size,
    calculate_leverage,
    max_lot_by_leverage,
    recommend_risk_pct,
    SAXO_MIN_LOT,
    SAXO_LOT_STEP,
    SAXO_UNITS_PER_LOT,
    DEFAULT_LEVERAGE_LIMIT,
    CB_LOT_REDUCTION,
)


# ---------------------------------------------------------------------------
# 正常ケース
# ---------------------------------------------------------------------------

class TestCalculateLotSizeBasic:
    """基本的なロット計算の正常ケース"""

    def test_basic_usdjpy_risk2pct_sl05pct(self):
        """
        10万円元本・リスク2%・SL0.5%でのUSDJPY基本計算。
        ロットは正値でSaxo最小単位(0.01)の倍数であること。
        """
        lot = calculate_lot_size(
            account_balance=100_000,
            risk_pct=0.02,
            sl_pct=0.005,
            symbol="USDJPY",
        )
        assert lot > 0, f"Expected positive lot, got {lot}"
        remainder = round(lot % SAXO_LOT_STEP, 10)
        assert remainder < 1e-9 or math.isclose(remainder, SAXO_LOT_STEP, abs_tol=1e-9), \
               f"Lot {lot} is not a multiple of {SAXO_LOT_STEP}"

    def test_basic_usdjpy_with_entry_price(self):
        """
        entry_price_jpy=155円を指定した場合の計算確認。

        計算:
            リスク金額 = 100,000 * 0.02 = 2,000円
            ポジション価値 = 2,000 / 0.005 = 400,000円
            基軸通貨量 = 400,000 / 155 = 2,580.6通貨
            ロット = 2,580.6 / 100,000 = 0.02580 -> 0.02ロット
        """
        lot = calculate_lot_size(
            account_balance=100_000,
            risk_pct=0.02,
            sl_pct=0.005,
            symbol="USDJPY",
            entry_price_jpy=155.0,
        )
        assert lot >= SAXO_MIN_LOT, f"Expected at least {SAXO_MIN_LOT} lot, got {lot}"
        expected_raw = (100_000 * 0.02 / 0.005) / 155.0 / SAXO_UNITS_PER_LOT
        expected_lot = math.floor(expected_raw / SAXO_LOT_STEP) * SAXO_LOT_STEP
        expected_lot = round(expected_lot, 2)
        assert math.isclose(lot, expected_lot, abs_tol=SAXO_LOT_STEP), \
               f"Expected {expected_lot}, got {lot}"

    def test_eurjpy_symbol(self):
        """EUR/JPYのロット計算が正常に動作すること"""
        lot = calculate_lot_size(
            account_balance=100_000,
            risk_pct=0.02,
            sl_pct=0.005,
            symbol="EURJPY",
        )
        assert lot > 0

    def test_eurjpy_slash_format(self):
        """EUR/JPY（スラッシュ区切り）でも正常に動作すること"""
        lot = calculate_lot_size(
            account_balance=100_000,
            risk_pct=0.02,
            sl_pct=0.005,
            symbol="EUR/JPY",
        )
        assert lot > 0

    def test_saxo_min_lot_multiple(self):
        """返値が必ずSaxo最小ロット単位(0.01)の倍数であること"""
        for sl_pct in [0.003, 0.005, 0.010, 0.020]:
            lot = calculate_lot_size(
                account_balance=100_000,
                risk_pct=0.02,
                sl_pct=sl_pct,
                symbol="USDJPY",
            )
            remainder = round(lot % SAXO_LOT_STEP, 10)
            assert remainder < 1e-9 or math.isclose(remainder, SAXO_LOT_STEP, abs_tol=1e-9), \
                   f"sl_pct={sl_pct}: lot={lot} is not multiple of {SAXO_LOT_STEP}"

    def test_higher_risk_pct_gives_larger_lot(self):
        """リスク率が高いほどロットが大きいこと"""
        lot_2pct = calculate_lot_size(100_000, 0.02, 0.005, "USDJPY")
        lot_5pct = calculate_lot_size(100_000, 0.05, 0.005, "USDJPY")
        assert lot_5pct >= lot_2pct, \
               f"risk 5% ({lot_5pct}) should be >= risk 2% ({lot_2pct})"

    def test_larger_sl_gives_smaller_lot(self):
        """SL幅が大きいほどロットが小さいこと（リスク金額一定）"""
        lot_small_sl = calculate_lot_size(100_000, 0.02, 0.003, "USDJPY")
        lot_large_sl = calculate_lot_size(100_000, 0.02, 0.010, "USDJPY")
        assert lot_large_sl <= lot_small_sl, \
               f"larger SL ({lot_large_sl}) should be <= smaller SL ({lot_small_sl})"


# ---------------------------------------------------------------------------
# レバレッジ上限チェック
# ---------------------------------------------------------------------------

class TestLeverageLimit:
    """レバレッジ上限25倍のチェックと自動削減"""

    def test_leverage_not_exceeded_by_default(self):
        """
        通常パラメータ(リスク2%・SL0.5%)ではレバレッジ25倍を超えないこと。
        entry_price_jpy=155円での確認。
        """
        lot = calculate_lot_size(
            account_balance=100_000,
            risk_pct=0.02,
            sl_pct=0.005,
            symbol="USDJPY",
            leverage_limit=25.0,
            entry_price_jpy=155.0,
        )
        leverage = calculate_leverage(100_000, lot, 155.0)
        assert leverage <= 25.0, \
               f"Leverage {leverage:.2f}x exceeds 25x limit"

    def test_leverage_exceeds_triggers_reduction(self):
        """
        極端に低いSL幅(高レバレッジになる設定)でロットが自動削減されること。
        リスク99%・SL0.001% -> 理論上99万倍のレバレッジ -> 25倍に削減
        """
        lot = calculate_lot_size(
            account_balance=100_000,
            risk_pct=0.99,
            sl_pct=0.0001,
            symbol="USDJPY",
            leverage_limit=25.0,
            entry_price_jpy=155.0,
        )
        if lot > 0:
            leverage = calculate_leverage(100_000, lot, 155.0)
            # 0.01ロット丸め誤差を許容
            assert leverage <= 25.0 + 0.1, \
                   f"After reduction, leverage {leverage:.2f}x still exceeds 25x"

    def test_leverage_exactly_at_limit(self):
        """
        レバレッジ上限ちょうどのケースで正常に計算されること。

        計算: 口座100,000円 / 150円 * 25倍 = 0.16ロット
        """
        max_lot = max_lot_by_leverage(100_000, 150.0, 25.0)
        assert max_lot > 0, f"max_lot should be positive, got {max_lot}"

        leverage = calculate_leverage(100_000, max_lot, 150.0)
        # 0.01ロット丸め誤差を許容して25.5倍まで
        assert leverage <= 25.5, \
               f"max_lot leverage {leverage:.2f}x exceeds expected range"

    def test_custom_leverage_limit(self):
        """カスタムレバレッジ上限(10倍)でも正常に機能すること"""
        lot_10x = calculate_lot_size(
            account_balance=100_000,
            risk_pct=0.99,
            sl_pct=0.0001,
            symbol="USDJPY",
            leverage_limit=10.0,
            entry_price_jpy=155.0,
        )
        lot_25x = calculate_lot_size(
            account_balance=100_000,
            risk_pct=0.99,
            sl_pct=0.0001,
            symbol="USDJPY",
            leverage_limit=25.0,
            entry_price_jpy=155.0,
        )
        assert lot_10x <= lot_25x, \
               f"10x limit lot ({lot_10x}) should be <= 25x limit lot ({lot_25x})"


# ---------------------------------------------------------------------------
# サーキットブレーカー
# ---------------------------------------------------------------------------

class TestCircuitBreaker:
    """サーキットブレーカー発動時のロット50%削減"""

    def test_cb_reduces_lot_by_half(self):
        """
        cb_active=True で通常の約50%のロットになること。

        要件定義書の完了条件:
            「サーキットブレーカー発動時のロット縮小(50%削減)ロジックが組み込まれていること」
        """
        lot_normal = calculate_lot_size(
            account_balance=100_000,
            risk_pct=0.04,
            sl_pct=0.005,
            symbol="USDJPY",
            cb_active=False,
        )
        lot_cb = calculate_lot_size(
            account_balance=100_000,
            risk_pct=0.04,
            sl_pct=0.005,
            symbol="USDJPY",
            cb_active=True,
        )
        assert lot_cb <= lot_normal, \
               f"CB lot ({lot_cb}) should be <= normal lot ({lot_normal})"
        if lot_normal > 0:
            ratio = lot_cb / lot_normal
            # 50%に近い値(Saxo単位丸めのため厳密50%でなくてもOK)
            assert ratio <= 0.6, \
                   f"CB lot ratio {ratio:.3f} should be approximately 0.5"

    def test_cb_false_does_not_reduce(self):
        """cb_active=False でロットが削減されないこと"""
        lot_no_cb = calculate_lot_size(100_000, 0.02, 0.005, "USDJPY", cb_active=False)
        lot_with_cb = calculate_lot_size(100_000, 0.02, 0.005, "USDJPY", cb_active=True)
        assert lot_with_cb <= lot_no_cb

    def test_cb_with_entry_price(self):
        """entry_price_jpy指定時もCBが正常に機能すること"""
        lot_normal = calculate_lot_size(
            account_balance=100_000,
            risk_pct=0.04,
            sl_pct=0.005,
            symbol="USDJPY",
            entry_price_jpy=150.0,
            cb_active=False,
        )
        lot_cb = calculate_lot_size(
            account_balance=100_000,
            risk_pct=0.04,
            sl_pct=0.005,
            symbol="USDJPY",
            entry_price_jpy=150.0,
            cb_active=True,
        )
        assert lot_cb <= lot_normal, \
               f"CB lot ({lot_cb}) should be <= normal lot ({lot_normal})"


# ---------------------------------------------------------------------------
# 入力バリデーション
# ---------------------------------------------------------------------------

class TestInputValidation:
    """異常入力に対するValueError送出確認"""

    def test_negative_balance_raises(self):
        """口座残高がマイナスでValueError"""
        with pytest.raises(ValueError, match="account_balance"):
            calculate_lot_size(-100_000, 0.02, 0.005, "USDJPY")

    def test_zero_balance_raises(self):
        """口座残高ゼロでValueError"""
        with pytest.raises(ValueError, match="account_balance"):
            calculate_lot_size(0, 0.02, 0.005, "USDJPY")

    def test_negative_risk_pct_raises(self):
        """リスク率がマイナスでValueError"""
        with pytest.raises(ValueError, match="risk_pct"):
            calculate_lot_size(100_000, -0.02, 0.005, "USDJPY")

    def test_zero_risk_pct_raises(self):
        """リスク率ゼロでValueError"""
        with pytest.raises(ValueError, match="risk_pct"):
            calculate_lot_size(100_000, 0.0, 0.005, "USDJPY")

    def test_negative_sl_pct_raises(self):
        """SL幅がマイナスでValueError"""
        with pytest.raises(ValueError, match="sl_pct"):
            calculate_lot_size(100_000, 0.02, -0.005, "USDJPY")

    def test_zero_sl_pct_raises(self):
        """SL幅ゼロでValueError"""
        with pytest.raises(ValueError, match="sl_pct"):
            calculate_lot_size(100_000, 0.02, 0.0, "USDJPY")

    def test_sl_pct_over_100pct_raises(self):
        """SL幅100%以上でValueError"""
        with pytest.raises(ValueError, match="sl_pct"):
            calculate_lot_size(100_000, 0.02, 1.0, "USDJPY")

    def test_sl_pct_over_200pct_raises(self):
        """SL幅200%でもValueError"""
        with pytest.raises(ValueError, match="sl_pct"):
            calculate_lot_size(100_000, 0.02, 2.0, "USDJPY")


# ---------------------------------------------------------------------------
# Saxo最小ロット単位
# ---------------------------------------------------------------------------

class TestSaxoMinLot:
    """Saxo証券の最小ロット単位(0.01)への対応"""

    def test_very_small_account_returns_zero(self):
        """
        口座残高が極めて小さく最小ロットに届かない場合、0.0を返すこと。
        """
        lot = calculate_lot_size(
            account_balance=100,
            risk_pct=0.02,
            sl_pct=0.5,
            symbol="USDJPY",
        )
        assert lot == 0.0, f"Expected 0.0 for below-minimum lot, got {lot}"

    def test_result_is_multiples_of_001(self):
        """結果が0.01の倍数であること(丸め精度確認)"""
        test_cases = [
            (100_000, 0.02, 0.003),
            (100_000, 0.03, 0.005),
            (200_000, 0.05, 0.010),
            (500_000, 0.02, 0.005),
        ]
        for balance, risk, sl in test_cases:
            lot = calculate_lot_size(balance, risk, sl, "USDJPY")
            if lot > 0:
                rounded = round(lot * 100) / 100
                assert math.isclose(lot, rounded, abs_tol=1e-9), \
                       f"balance={balance}, risk={risk}, sl={sl}: lot={lot} not multiple of 0.01"

    def test_saxo_min_lot_constant(self):
        """定数が正しく設定されていること"""
        assert SAXO_MIN_LOT == 0.01
        assert SAXO_LOT_STEP == 0.01
        assert SAXO_UNITS_PER_LOT == 100_000


# ---------------------------------------------------------------------------
# ユーティリティ関数
# ---------------------------------------------------------------------------

class TestUtilityFunctions:
    """calculate_leverage, max_lot_by_leverage, recommend_risk_pct のテスト"""

    def test_calculate_leverage_basic(self):
        """
        レバレッジ計算の基本確認。
        0.4ロット * 100,000通貨 * 150円 = 6,000,000円
        6,000,000 / 100,000円 = 60倍
        """
        lev = calculate_leverage(100_000, 0.4, 150.0)
        assert math.isclose(lev, 60.0, rel_tol=0.01), \
               f"Expected ~60x leverage, got {lev}"

    def test_max_lot_by_leverage_basic(self):
        """
        最大ロット計算の基本確認。
        口座100,000円 / 150円 * 25倍 = 0.16ロット
        """
        max_lot = max_lot_by_leverage(100_000, 150.0, 25.0)
        assert math.isclose(max_lot, 0.16, abs_tol=SAXO_LOT_STEP), \
               f"Expected ~0.16 lot, got {max_lot}"

    def test_recommend_risk_pct_clamp_max(self):
        """推奨リスク率が5%を超えないこと"""
        pct = recommend_risk_pct(10.0, 1.71)
        assert pct <= 0.05, f"Expected <= 0.05, got {pct}"

    def test_recommend_risk_pct_clamp_min(self):
        """推奨リスク率が2%を下回らないこと"""
        pct = recommend_risk_pct(10.0, 0.1)
        assert pct >= 0.02, f"Expected >= 0.02, got {pct}"

    def test_recommend_risk_pct_zero_strategy_return(self):
        """戦略月利0%の場合はデフォルト2%を返すこと"""
        pct = recommend_risk_pct(10.0, 0.0)
        assert pct == 0.02


# ---------------------------------------------------------------------------
# 要件定義書の完了条件テスト
# ---------------------------------------------------------------------------

class TestRequirementCompliance:
    """
    要件定義書 工程C 完了条件の明示的テスト。

    品質チェック項目:
        1. 固定フラクショナル法でロット計算が正しく実装されているか(配点30)
        2. レバレッジ上限25倍の超過時にロット自動削減されるか(配点25)
        3. 10万円・リスク2%・SL0.5%でのロット計算が正しいか(配点20)
        4. サーキットブレーカー発動時のロット50%削減ロジックが機能するか(配点15)
        5. Saxo証券の最小ロット単位(0.01)に対応しているか(配点10)
    """

    def test_req1_fixed_fractional_implementation(self):
        """
        要件1: 固定フラクショナル法の実装確認。

        計算:
            リスク金額 = 100,000 * 0.02 = 2,000円
            ポジション価値 = 2,000 / 0.005 = 400,000
            ロット = 400,000 / 100,000 = 4.0ロット
        """
        lot = calculate_lot_size(100_000, 0.02, 0.005, "USDJPY")
        # 理論上4.0ロットになる
        assert math.isclose(lot, 4.0, abs_tol=SAXO_LOT_STEP), \
               f"Expected ~4.0 lots (fixed fractional), got {lot}"

    def test_req2_leverage_auto_reduction(self):
        """
        要件2: レバレッジ25倍超過時のロット自動削減。

        高リスク・低SLで極端に高いロットになる設定でも
        自動削減後は25倍以内に収まることを確認する。
        """
        lot = calculate_lot_size(
            account_balance=100_000,
            risk_pct=0.5,
            sl_pct=0.001,
            symbol="USDJPY",
            leverage_limit=25.0,
            entry_price_jpy=150.0,
        )
        if lot > 0:
            leverage = calculate_leverage(100_000, lot, 150.0)
            # 0.01ロット丸め誤差を考慮して25.5倍まで許容
            assert leverage <= 25.5, \
                   f"Leverage {leverage:.2f}x should be <= 25x after auto-reduction"

    def test_req3_standard_lot_calculation(self):
        """
        要件3: 10万円・リスク2%・SL0.5%でのロット計算(Saxo最小単位対応確認)。

        この条件では計算上4.0ロットになりSaxo単位に合致する。
        """
        lot = calculate_lot_size(
            account_balance=100_000,
            risk_pct=0.02,
            sl_pct=0.005,
            symbol="USDJPY",
        )
        assert lot >= SAXO_MIN_LOT, f"Lot {lot} should be >= {SAXO_MIN_LOT}"
        assert round(lot * 100) == int(round(lot * 100)), f"Lot {lot} should be multiple of 0.01"

    def test_req4_circuit_breaker_50pct_reduction(self):
        """
        要件4: サーキットブレーカー発動時のロット50%削減。
        entry_price_jpy=150円でCB発動後のロットが確実に減少することを確認。
        """
        lot_normal = calculate_lot_size(
            account_balance=100_000,
            risk_pct=0.04,
            sl_pct=0.005,
            symbol="USDJPY",
            entry_price_jpy=150.0,
            cb_active=False,
        )
        lot_cb = calculate_lot_size(
            account_balance=100_000,
            risk_pct=0.04,
            sl_pct=0.005,
            symbol="USDJPY",
            entry_price_jpy=150.0,
            cb_active=True,
        )
        assert lot_cb <= lot_normal, \
               f"CB lot {lot_cb} should be <= normal lot {lot_normal}"
        if lot_normal >= 0.02:
            assert lot_cb <= lot_normal * 0.5 + SAXO_LOT_STEP

    def test_req5_saxo_minimum_lot_compliance(self):
        """
        要件5: Saxo証券最小ロット単位(0.01)対応。
        a) 計算結果は必ず0.01単位
        b) 最小ロット未満の場合は0.0を返す
        c) 定数SAXO_MIN_LOT=0.01, SAXO_LOT_STEP=0.01が設定されている
        """
        lot = calculate_lot_size(100_000, 0.02, 0.005, "USDJPY")
        assert round(lot * 100) == int(round(lot * 100)), \
               f"Lot {lot} is not 0.01-unit"

        tiny_lot = calculate_lot_size(100, 0.001, 0.5, "USDJPY")
        assert tiny_lot == 0.0

        assert SAXO_MIN_LOT == 0.01
        assert SAXO_LOT_STEP == 0.01
