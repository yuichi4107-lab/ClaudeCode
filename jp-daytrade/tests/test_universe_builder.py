"""
universe_builder のテスト

値嵩株フィルター境界値テスト・ユニバース生成の正確性を検証する。
"""

import os
import sqlite3
import sys
from datetime import date

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from data.universe_builder import (
    VALUE_STOCK_PRICE_THRESHOLD,
    VALUE_STOCK_UNIT_VALUE_THRESHOLD,
    build_universe,
    is_value_stock,
    calculate_volatility,
)


# ---------------------------------------------------------------------------
# is_value_stock 境界値テスト
# ---------------------------------------------------------------------------

class TestIsValueStock:
    """
    値嵩株判定の境界値テスト

    条件: 株価 > 3,000円 OR 単元代金（株価 × unit_shares）> 300,000円
    """

    # --- 株価境界値（unit_shares=100 で単元代金は最大 30万円以下）---

    def test_price_2999_not_value_stock(self):
        """株価 2,999円（閾値-1）は値嵩ではない"""
        assert is_value_stock(2999, 100) is False

    def test_price_3000_not_value_stock(self):
        """株価 3,000円（閾値）は値嵩ではない（> 3000 のため）"""
        assert is_value_stock(3000, 100) is False

    def test_price_3001_is_value_stock(self):
        """株価 3,001円（閾値+1）は値嵩"""
        assert is_value_stock(3001, 100) is True

    def test_price_5000_is_value_stock(self):
        """株価 5,000円は値嵩"""
        assert is_value_stock(5000, 100) is True

    # --- 単元代金境界値 ---

    def test_unit_value_299999_not_value(self):
        """単元代金 299,999円（閾値-1）は値嵩ではない"""
        # price=2999, unit=100 → 299,900円 < 300,000円
        assert is_value_stock(2999, 100) is False

    def test_unit_value_300000_not_value(self):
        """単元代金 300,000円（閾値）は値嵩ではない（> 300,000 のため）"""
        # price=3000, unit=100 → 300,000円
        assert is_value_stock(3000, 100) is False

    def test_unit_value_300001_is_value(self):
        """単元代金 300,001円（閾値+1）は値嵩"""
        # price=1500, unit=200 → 300,000円（ちょうど）→ 値嵩ではない
        assert is_value_stock(1500, 200) is False
        # price=1500, unit=201 → 301,500円 > 300,000円 → 値嵩
        assert is_value_stock(1500, 201) is True

    def test_unit_value_exact_300001(self):
        """単元代金がちょうど 300,001円になるケース"""
        # price=3001, unit=100 → 300,100円 > 300,000 AND price > 3000 → 値嵩（両条件）
        assert is_value_stock(3001, 100) is True

    # --- その他の組み合わせ ---

    def test_low_price_large_unit(self):
        """低株価・大単元数で単元代金オーバー"""
        # price=500, unit=700 → 350,000円 > 300,000円 → 値嵩
        assert is_value_stock(500, 700) is True

    def test_low_price_normal_unit(self):
        """通常の小型株は値嵩でない"""
        # price=800, unit=100 → 80,000円 → 値嵩でない
        assert is_value_stock(800, 100) is False

    def test_zero_price(self):
        """株価0円（異常値）は値嵩でない"""
        assert is_value_stock(0, 100) is False

    def test_negative_price(self):
        """負の株価は値嵩でない（異常値扱い）"""
        assert is_value_stock(-100, 100) is False

    def test_price_exactly_at_threshold_various_units(self):
        """株価 3,000円でも単元株数が多ければ値嵩になること"""
        # 3000 * 100 = 300,000（ちょうど） → 値嵩でない
        assert is_value_stock(3000, 100) is False
        # 3000 * 101 = 303,000 > 300,000 → 値嵩
        assert is_value_stock(3000, 101) is True


# ---------------------------------------------------------------------------
# calculate_volatility
# ---------------------------------------------------------------------------

class TestCalculateVolatility:
    @pytest.fixture
    def prices_db(self, tmp_path):
        """テスト用日足DBを作成"""
        db = str(tmp_path / "daily_prices.db")
        schema_path = os.path.join(
            os.path.dirname(__file__), "..", "data", "schemas", "daily_prices.sql"
        )
        with open(schema_path, encoding="utf-8") as f:
            schema_sql = f.read()

        with sqlite3.connect(db) as conn:
            conn.executescript(schema_sql)
            # 日中値幅率 5% のサンプルデータを挿入
            # high - low = 5% * close
            rows = []
            for i in range(10):
                day = f"2024-01-{i+1:02d}"
                close = 1000.0
                high = close * 1.05  # +5%
                low = close
                rows.append(("7203", day, close, high, low, close, 1000000, None, 1.0))

            conn.executemany(
                "INSERT INTO daily_prices (code, date, open, high, low, close, volume, turnover, adjustment_factor) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                rows,
            )
            conn.commit()
        return db

    def test_returns_float(self, prices_db):
        vol = calculate_volatility(prices_db, "7203", days=5)
        assert isinstance(vol, float)

    def test_calculates_correctly(self, prices_db):
        """日中値幅率 5% のデータで approx 5.0% が返ること"""
        vol = calculate_volatility(prices_db, "7203", days=5)
        assert vol == pytest.approx(5.0, rel=0.01)

    def test_returns_none_if_db_missing(self, tmp_path):
        vol = calculate_volatility(str(tmp_path / "nonexistent.db"), "7203")
        assert vol is None

    def test_returns_none_if_insufficient_data(self, prices_db):
        """データが日数に満たない場合 None を返すこと"""
        vol = calculate_volatility(prices_db, "9999", days=5)  # 存在しないコード
        assert vol is None


# ---------------------------------------------------------------------------
# build_universe
# ---------------------------------------------------------------------------

class TestBuildUniverse:
    @pytest.fixture
    def master_db(self, tmp_path):
        """テスト用銘柄マスターDBを作成"""
        db = str(tmp_path / "stocks_master.db")
        schema_path = os.path.join(
            os.path.dirname(__file__), "..", "data", "schemas", "stocks_master.sql"
        )
        with open(schema_path, encoding="utf-8") as f:
            schema_sql = f.read()

        with sqlite3.connect(db) as conn:
            conn.executescript(schema_sql)
            # テストデータ投入
            rows = [
                # グロース・通常銘柄（対象）
                ("1111", "グロース銘柄A", "グロース250（内国）", 50_000_000_000, 800.0,  100, "2026-04-15"),
                ("2222", "グロース銘柄B", "グロース500（内国）", 80_000_000_000, 2500.0, 100, "2026-04-15"),
                # グロース・値嵩（株価 > 3000）
                ("3333", "グロース値嵩C", "グロース250（内国）", 60_000_000_000, 3500.0, 100, "2026-04-15"),
                # グロース・単元代金超（price=1500, unit=300 → 450,000円）
                ("4444", "グロース値嵩D", "グロース500（内国）", 40_000_000_000, 1500.0, 300, "2026-04-15"),
                # プライム（市場フィルターで除外）
                ("5555", "プライム銘柄E", "プライム（内国）",   200_000_000_000, 1200.0, 100, "2026-04-15"),
            ]
            conn.executemany(
                "INSERT INTO stocks_master (code, name, market, market_cap, last_price, unit_shares, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                rows,
            )
            conn.commit()
        return db

    def test_excludes_value_stocks(self, master_db, tmp_path):
        """値嵩株が除外されること"""
        prices_db = str(tmp_path / "prices.db")  # 存在しない = ボラ計算スキップ
        candidates = build_universe(
            market="growth",
            exclude_value_stock=True,
            master_db=master_db,
            prices_db=prices_db,
        )
        codes = [c["code"] for c in candidates]
        assert "1111" in codes
        assert "2222" in codes
        assert "3333" not in codes  # 株価 > 3000
        assert "4444" not in codes  # 単元代金 > 300,000

    def test_includes_value_stocks_when_not_excluded(self, master_db, tmp_path):
        """除外フラグ OFF のとき値嵩株が含まれること"""
        prices_db = str(tmp_path / "prices.db")
        candidates = build_universe(
            market="growth",
            exclude_value_stock=False,
            master_db=master_db,
            prices_db=prices_db,
        )
        codes = [c["code"] for c in candidates]
        assert "3333" in codes

    def test_market_filter_growth_only(self, master_db, tmp_path):
        """market=growth のとき、プライム銘柄が除外されること"""
        prices_db = str(tmp_path / "prices.db")
        candidates = build_universe(
            market="growth",
            exclude_value_stock=False,
            master_db=master_db,
            prices_db=prices_db,
        )
        codes = [c["code"] for c in candidates]
        assert "5555" not in codes

    def test_market_filter_all(self, master_db, tmp_path):
        """market=all のとき、全市場が含まれること"""
        prices_db = str(tmp_path / "prices.db")
        candidates = build_universe(
            market="all",
            exclude_value_stock=False,
            master_db=master_db,
            prices_db=prices_db,
        )
        codes = [c["code"] for c in candidates]
        assert "5555" in codes

    def test_raises_if_db_missing(self, tmp_path):
        """DB が存在しない場合 FileNotFoundError を送出すること"""
        with pytest.raises(FileNotFoundError):
            build_universe(master_db=str(tmp_path / "nonexistent.db"))

    def test_result_contains_expected_fields(self, master_db, tmp_path):
        """戻り値に必要フィールドが含まれること"""
        prices_db = str(tmp_path / "prices.db")
        candidates = build_universe(master_db=master_db, prices_db=prices_db)
        assert len(candidates) > 0
        required = ["code", "name", "market", "market_cap", "last_price", "unit_shares", "is_value_stock"]
        for field in required:
            assert field in candidates[0], f"'{field}' がありません"

    def test_is_value_stock_flag_correct(self, master_db, tmp_path):
        """is_value_stock フラグが正しく設定されること（exclude_value_stock=False 時）"""
        prices_db = str(tmp_path / "prices.db")
        candidates = build_universe(
            market="growth",
            exclude_value_stock=False,
            master_db=master_db,
            prices_db=prices_db,
        )
        by_code = {c["code"]: c for c in candidates}

        # 通常銘柄は False
        assert by_code["1111"]["is_value_stock"] is False
        # 値嵩銘柄は True（株価 > 3000）
        assert by_code["3333"]["is_value_stock"] is True
