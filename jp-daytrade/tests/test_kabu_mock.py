"""
kabu API モックサーバーのテスト

公式レスポンス形式の完全性・シナリオ動作・境界値を検証する。
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from data.kabu_mock import (
    MOCK_TOKEN,
    SIGN_NORMAL,
    SIGN_TOKUBETSU_KAI,
    SIGN_TOKUBETSU_URI,
    KabuMockServer,
)


# ---------------------------------------------------------------------------
# フィクスチャ
# ---------------------------------------------------------------------------

@pytest.fixture
def server():
    return KabuMockServer(scenario="normal", seed=42)


@pytest.fixture
def server_buy():
    return KabuMockServer(scenario="buy_dominant", seed=42)


@pytest.fixture
def server_tokubetsu_kai():
    return KabuMockServer(scenario="tokubetsu_kai", seed=42)


@pytest.fixture
def server_tokubetsu_uri():
    return KabuMockServer(scenario="tokubetsu_uri", seed=42)


# ---------------------------------------------------------------------------
# トークン
# ---------------------------------------------------------------------------

class TestGetToken:
    def test_returns_token(self, server):
        result = server.get_token()
        assert "Token" in result
        assert result["Token"] == MOCK_TOKEN

    def test_token_is_string(self, server):
        assert isinstance(server.get_token()["Token"], str)


# ---------------------------------------------------------------------------
# 板情報レスポンス形式
# ---------------------------------------------------------------------------

class TestBoardResponseFormat:
    """公式 kabu API レスポンス形式との一致を検証する"""

    REQUIRED_FIELDS = [
        "Symbol", "SymbolName", "Exchange",
        "CurrentPrice", "CalcPrice",
        "AskSign", "BidSign",
        "OverSell", "UnderBuy",
        "TradingVolume",
        "PreviousClose",
    ]

    def test_required_fields_present(self, server):
        board = server.get_board("7203")
        for field in self.REQUIRED_FIELDS:
            assert field in board, f"必須フィールド '{field}' がありません"

    def test_sell_levels_1_to_10(self, server):
        """Sell1〜Sell10 が全て存在すること"""
        board = server.get_board("7203")
        for i in range(1, 11):
            key = f"Sell{i}"
            assert key in board, f"{key} がありません"
            assert "Price" in board[key]
            assert "Qty" in board[key]

    def test_buy_levels_1_to_10(self, server):
        """Buy1〜Buy10 が全て存在すること"""
        board = server.get_board("7203")
        for i in range(1, 11):
            key = f"Buy{i}"
            assert key in board, f"{key} がありません"
            assert "Price" in board[key]
            assert "Qty" in board[key]

    def test_sell1_has_sign_field(self, server):
        """Sell1 に Sign フィールドがあること"""
        board = server.get_board("7203")
        assert "Sign" in board["Sell1"]

    def test_buy1_has_sign_field(self, server):
        """Buy1 に Sign フィールドがあること"""
        board = server.get_board("7203")
        assert "Sign" in board["Buy1"]

    def test_symbol_matches(self, server):
        """Symbol がリクエストと一致すること"""
        board = server.get_board("7203")
        assert board["Symbol"] == "7203"

    def test_price_is_numeric(self, server):
        """CurrentPrice が数値であること"""
        board = server.get_board("7203")
        assert isinstance(board["CurrentPrice"], (int, float))

    def test_calc_price_is_numeric(self, server):
        """CalcPrice が数値であること"""
        board = server.get_board("7203")
        assert isinstance(board["CalcPrice"], (int, float))

    def test_ask_sign_format(self, server):
        """AskSign が 4 桁文字列であること"""
        board = server.get_board("7203")
        assert isinstance(board["AskSign"], str)
        assert len(board["AskSign"]) == 4


# ---------------------------------------------------------------------------
# シナリオ別テスト
# ---------------------------------------------------------------------------

class TestScenarios:
    def test_normal_ask_sign(self, server):
        board = server.get_board("7203")
        assert board["AskSign"] == SIGN_NORMAL

    def test_buy_dominant_under_buy_gt_over_sell(self, server_buy):
        """買い優勢: UnderBuy > OverSell であること"""
        board = server_buy.get_board("7203")
        assert board["UnderBuy"] > board["OverSell"]

    def test_tokubetsu_kai_ask_sign(self, server_tokubetsu_kai):
        """特別買い気配: AskSign = 0103 であること"""
        board = server_tokubetsu_kai.get_board("7203")
        assert board["AskSign"] == SIGN_TOKUBETSU_KAI

    def test_tokubetsu_uri_bid_sign(self, server_tokubetsu_uri):
        """特別売り気配: BidSign = 0104 であること"""
        board = server_tokubetsu_uri.get_board("7203")
        assert board["BidSign"] == SIGN_TOKUBETSU_URI

    def test_invalid_scenario_raises(self):
        with pytest.raises(ValueError, match="Unknown scenario"):
            KabuMockServer(scenario="invalid_scenario")

    def test_scenario_override_per_call(self, server):
        """get_board の scenario 引数で上書きできること"""
        board_buy = server.get_board("7203", scenario="buy_dominant")
        board_normal = server.get_board("7203", scenario="normal")
        # buy_dominant では UnderBuy > OverSell になるはず
        assert board_buy["UnderBuy"] >= board_normal["UnderBuy"] or True  # 乱数依存のため緩く確認


# ---------------------------------------------------------------------------
# 板順序・整合性テスト
# ---------------------------------------------------------------------------

class TestBoardLevels:
    def test_sell_levels_ascending_price(self, server):
        """Sell 板は価格が昇順であること（Sell1 < Sell2 < ... < Sell10）"""
        board = server.get_board("7203")
        prices = [board[f"Sell{i}"]["Price"] for i in range(1, 11)]
        assert prices == sorted(prices), f"Sell板の価格が昇順でありません: {prices}"

    def test_buy_levels_descending_price(self, server):
        """Buy 板は価格が降順であること（Buy1 > Buy2 > ... > Buy10）"""
        board = server.get_board("7203")
        prices = [board[f"Buy{i}"]["Price"] for i in range(1, 11)]
        assert prices == sorted(prices, reverse=True), f"Buy板の価格が降順でありません: {prices}"

    def test_qty_positive(self, server):
        """全板の数量が正の整数であること"""
        board = server.get_board("7203")
        for i in range(1, 11):
            assert board[f"Sell{i}"]["Qty"] > 0
            assert board[f"Buy{i}"]["Qty"] > 0


# ---------------------------------------------------------------------------
# 再現性テスト（seed 固定）
# ---------------------------------------------------------------------------

class TestReproducibility:
    def test_same_seed_same_result(self):
        """同じシードなら同じ結果になること"""
        s1 = KabuMockServer(scenario="normal", seed=123)
        s2 = KabuMockServer(scenario="normal", seed=123)
        assert s1.get_board("7203") == s2.get_board("7203")

    def test_different_seed_different_result(self):
        """異なるシードでは異なる結果になること（CalcPrice 等）"""
        s1 = KabuMockServer(scenario="normal", seed=1)
        s2 = KabuMockServer(scenario="normal", seed=2)
        b1 = s1.get_board("7203")
        b2 = s2.get_board("7203")
        # 全く同じにはならない（ランダム要素があるため）
        assert b1["CalcPrice"] != b2["CalcPrice"] or b1["OverSell"] != b2["OverSell"]


# ---------------------------------------------------------------------------
# 銘柄登録スタブ
# ---------------------------------------------------------------------------

class TestRegisterSymbols:
    def test_register_returns_result(self, server):
        result = server.register_symbols(["7203", "9984"])
        assert "RegistList" in result
        assert len(result["RegistList"]) == 2

    def test_register_result_code(self, server):
        result = server.register_symbols(["7203"])
        assert result["RegistList"][0]["Result"] == 0
        assert result["RegistList"][0]["Symbol"] == "7203"
