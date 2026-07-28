"""
screener.py ã®ãƒ¦ãƒ‹ãƒƒãƒˆãƒ†ã‚¹ãƒˆã€‚

å„ãƒ•ã‚£ãƒ«ã‚¿ãƒ¼ã®æ­£ç¢ºæ€§ã‚’å€‹åˆ¥ã«æ¤œè¨¼ã™ã‚‹ã€‚
å…ˆèª­ã¿ãƒã‚¤ã‚¢ã‚¹ã®ãªã„ã“ã¨ã‚’ç¢ºèªã™ã‚‹ãƒ†ã‚¹ãƒˆã‚‚å«ã‚€ã€‚
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pandas as pd
import pytest

# ---------------------------------------------------------------------------
# ãƒ‘ãƒƒã‚±ãƒ¼ã‚¸ãƒ«ãƒ¼ãƒˆè¨­å®š
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_STRATEGY_DIR = _REPO_ROOT / "jp-daytrade" / "strategy"


def _ensure_strategy_package() -> types.ModuleType:
    """
    strategy ãƒ‘ãƒƒã‚±ãƒ¼ã‚¸ã¨ config / screener ãƒ¢ã‚¸ãƒ¥ãƒ¼ãƒ«ã‚’ sys.modules ã«ç™»éŒ²ã™ã‚‹ã€‚

    ãƒã‚¤ãƒ•ãƒ³å…¥ã‚Šãƒ‡ã‚£ãƒ¬ã‚¯ãƒˆãƒªã®ãŸã‚ãƒ‘ãƒƒã‚±ãƒ¼ã‚¸åã¯ `jpdaytrade_strategy` ã§ç™»éŒ²ã™ã‚‹ã€‚
    """
    pkg_name = "jpdaytrade_strategy"
    if pkg_name not in sys.modules:
        pkg = types.ModuleType(pkg_name)
        pkg.__path__ = [str(_STRATEGY_DIR)]
        pkg.__package__ = pkg_name
        sys.modules[pkg_name] = pkg

    # config
    cfg_name = f"{pkg_name}.config"
    if cfg_name not in sys.modules:
        spec = importlib.util.spec_from_file_location(
            cfg_name, _STRATEGY_DIR / "config.py",
            submodule_search_locations=[],
        )
        mod = importlib.util.module_from_spec(spec)
        mod.__package__ = pkg_name
        sys.modules[cfg_name] = mod
        spec.loader.exec_module(mod)
        # screener.py ãŒ `from .config import` ã§ãã‚‹ã‚ˆã†ã€è¦ªãƒ‘ãƒƒã‚±ãƒ¼ã‚¸å±æ€§ã«è¨­å®š
        sys.modules[pkg_name].config = mod

    # screenerï¼ˆconfig ã‚ˆã‚Šå¾Œï¼‰
    scr_name = f"{pkg_name}.screener"
    if scr_name not in sys.modules:
        spec = importlib.util.spec_from_file_location(
            scr_name, _STRATEGY_DIR / "screener.py",
            submodule_search_locations=[],
        )
        mod = importlib.util.module_from_spec(spec)
        mod.__package__ = pkg_name
        sys.modules[scr_name] = mod
        spec.loader.exec_module(mod)
        sys.modules[pkg_name].screener = mod

    return sys.modules[f"{pkg_name}.screener"]


# ãƒ¢ã‚¸ãƒ¥ãƒ¼ãƒ«ã‚’ä¸€åº¦ã ã‘ãƒ­ãƒ¼ãƒ‰
_screener = _ensure_strategy_package()


# ---------------------------------------------------------------------------
# ãƒ†ã‚¹ãƒˆç”¨ã‚µãƒ³ãƒ—ãƒ«ãƒ‡ãƒ¼ã‚¿ç”Ÿæˆãƒ˜ãƒ«ãƒ‘ãƒ¼
# ---------------------------------------------------------------------------

def _make_prices(rows: list[dict]) -> pd.DataFrame:
    """ãƒ†ã‚¹ãƒˆç”¨ã®æ—¥è¶³ DataFrame ã‚’ç”Ÿæˆã™ã‚‹ã€‚"""
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    for col in ["open", "high", "low", "close", "volume", "turnover"]:
        if col not in df.columns:
            df[col] = 0.0
    df["adjustment_factor"] = 1.0
    return df.sort_values(["code", "date"]).reset_index(drop=True)


def _make_master(rows: list[dict]) -> pd.DataFrame:
    """ãƒ†ã‚¹ãƒˆç”¨ã® stocks_master DataFrame ã‚’ç”Ÿæˆã™ã‚‹ã€‚"""
    df = pd.DataFrame(rows)
    if "is_value_stock" not in df.columns:
        # is_value_stock ã‚’è¨ˆç®—ï¼ˆstocks_master ã® STORED åˆ—ã‚’æ¨¡å€£ï¼‰
        unit_shares = df.get("unit_shares", pd.Series([100] * len(df)))
        df["is_value_stock"] = (
            (df["last_price"] > 3000) |
            (df["last_price"] * unit_shares > 300000)
        ).astype(int)
    return df


# ---------------------------------------------------------------------------
# F1: æ ªä¾¡ãƒ•ã‚£ãƒ«ã‚¿ãƒ¼ãƒ†ã‚¹ãƒˆ
# ---------------------------------------------------------------------------

class TestF1Price:
    def test_excludes_high_price_stocks(self):
        """3,000å††è¶…ã®éŠ˜æŸ„ã¯é™¤å¤–ã•ã‚Œã‚‹ã€‚"""
        master = _make_master([
            {"code": "A001", "name": "å®‰ã„", "market": "ã‚°ãƒ­ãƒ¼ã‚¹", "last_price": 500.0, "unit_shares": 100},
            {"code": "A002", "name": "é«˜ã„", "market": "ã‚°ãƒ­ãƒ¼ã‚¹", "last_price": 3001.0, "unit_shares": 100},
        ])
        result = _screener.apply_f1_price(master)
        assert "A001" in result["code"].values
        assert "A002" not in result["code"].values

    def test_includes_exactly_3000(self):
        """3,000å††ã¡ã‚‡ã†ã©ã¯é€šéã™ã‚‹ã€‚"""
        master = _make_master([
            {"code": "A003", "name": "å¢ƒç•Œ", "market": "ã‚°ãƒ­ãƒ¼ã‚¹", "last_price": 3000.0, "unit_shares": 100},
        ])
        result = _screener.apply_f1_price(master)
        assert "A003" in result["code"].values

    def test_excludes_high_unit_price(self):
        """å˜å…ƒä»£é‡‘ > 30ä¸‡å††ã¯é™¤å¤–ã•ã‚Œã‚‹ï¼ˆä¾‹: 3,100å†† Ã— 100æ ª = 310,000å††ï¼‰ã€‚"""
        master = _make_master([
            {"code": "A004", "name": "é«˜å˜å…ƒ", "market": "ã‚°ãƒ­ãƒ¼ã‚¹", "last_price": 3100.0, "unit_shares": 100},
        ])
        result = _screener.apply_f1_price(master)
        assert "A004" not in result["code"].values

    def test_all_eligible(self):
        """å…¨éŠ˜æŸ„ãŒæ¡ä»¶ã‚’æº€ãŸã™å ´åˆã€å…¨ä»¶è¿”ã™ã€‚"""
        master = _make_master([
            {"code": "A005", "name": "A", "market": "ã‚°ãƒ­ãƒ¼ã‚¹", "last_price": 500.0, "unit_shares": 100},
            {"code": "A006", "name": "B", "market": "ã‚°ãƒ­ãƒ¼ã‚¹", "last_price": 1500.0, "unit_shares": 100},
        ])
        result = _screener.apply_f1_price(master)
        assert len(result) == 2


# ---------------------------------------------------------------------------
# F3: æ—¥ä¸­å€¤å¹…ç‡ãƒ†ã‚¹ãƒˆ
# ---------------------------------------------------------------------------

class TestF3IntradayRange:
    def _build_data_with_range(self, high_low_ratio: float, days: int = 7) -> pd.DataFrame:
        """æŒ‡å®šã—ãŸå€¤å¹…ç‡ã‚’æŒã¤æ—¥è¶³ãƒ‡ãƒ¼ã‚¿ã‚’ç”Ÿæˆã™ã‚‹ã€‚"""
        rows = []
        base_close = 1000.0
        for i in range(days):
            close = base_close
            high = close * (1 + high_low_ratio / 2)
            low = close * (1 - high_low_ratio / 2)
            rows.append({
                "code": "T001",
                "date": f"2024-01-{i+1:02d}",
                "open": close,
                "high": high,
                "low": low,
                "close": close,
                "volume": 2_000_000.0,
            })
        return _make_prices(rows)

    def test_high_range_passes(self):
        """å€¤å¹…ç‡ 10%ï¼ˆâ‰¥5%ï¼‰ã¯é€šéã™ã‚‹ã€‚"""
        prices = self._build_data_with_range(0.10, days=8)
        prices = _screener.compute_intraday_range(prices, days=5)
        valid = prices.dropna(subset=["intraday_range_avg"])
        result = _screener.apply_f3_intraday_range(valid)
        assert len(result) > 0

    def test_low_range_fails(self):
        """å€¤å¹…ç‡ 2%ï¼ˆ<5%ï¼‰ã¯é™¤å¤–ã•ã‚Œã‚‹ã€‚"""
        prices = self._build_data_with_range(0.02, days=8)
        prices = _screener.compute_intraday_range(prices, days=5)
        valid = prices.dropna(subset=["intraday_range_avg"])
        result = _screener.apply_f3_intraday_range(valid)
        assert len(result) == 0

    def test_no_lookahead_bias(self):
        """å½“æ—¥ãƒ‡ãƒ¼ã‚¿ãŒ intraday_range_avg ã«å«ã¾ã‚Œãªã„ã“ã¨ï¼ˆå…ˆèª­ã¿ãƒã‚¤ã‚¢ã‚¹ãªã—ï¼‰ã€‚"""
        rows = []
        for i in range(6):
            ratio = 0.01 if i < 5 else 0.20  # 6æ—¥ç›®ã ã‘é«˜å€¤å¹…
            close = 1000.0
            high = close * (1 + ratio / 2)
            low = close * (1 - ratio / 2)
            rows.append({
                "code": "T002",
                "date": f"2024-01-{i+1:02d}",
                "open": close,
                "high": high,
                "low": low,
                "close": close,
                "volume": 2_000_000.0,
            })
        prices = _make_prices(rows)
        prices = _screener.compute_intraday_range(prices, days=5)

        # 6 æ—¥ç›®ã® intraday_range_avg ã¯ã€Œå‰æ—¥ã¾ã§ã€ã® 5 æ—¥å¹³å‡ â†’ ä½å€¤å¹…ã®ã¯ãš
        last_row = prices[prices["code"] == "T002"].iloc[-1]
        assert last_row["intraday_range_avg"] < 0.05, (
            f"å…ˆèª­ã¿ãƒã‚¤ã‚¢ã‚¹ã‚’æ¤œå‡º: intraday_range_avg={last_row['intraday_range_avg']:.4f}"
        )


# ---------------------------------------------------------------------------
# F4: å‰æ—¥å‡ºæ¥é«˜ãƒ†ã‚¹ãƒˆ
# ---------------------------------------------------------------------------

class TestF4Volume:
    def test_high_volume_passes(self):
        """å‰æ—¥å‡ºæ¥é«˜ 200ä¸‡æ ªï¼ˆâ‰¥100ä¸‡æ ªï¼‰ã¯é€šéã™ã‚‹ã€‚"""
        rows = [
            {"code": "V001", "date": "2024-01-01", "open": 1000, "high": 1100, "low": 900, "close": 1000, "volume": 2_000_000.0},
            {"code": "V001", "date": "2024-01-02", "open": 1000, "high": 1100, "low": 900, "close": 1000, "volume": 1_500_000.0},
        ]
        prices = _make_prices(rows)
        prices = _screener.compute_prev_volume(prices)
        result = _screener.apply_f4_volume(prices)
        assert len(result[result["code"] == "V001"]) == 1

    def test_low_volume_fails(self):
        """å‰æ—¥å‡ºæ¥é«˜ 50ä¸‡æ ªï¼ˆ<100ä¸‡æ ªï¼‰ã¯é™¤å¤–ã•ã‚Œã‚‹ã€‚"" ¢&÷w2Ò°¢²&6öFR#¢%c""Â&FFR#¢###BÓÓ"Â&÷Vâ#¢Â&†–v‚#¢Â&Æ÷r#¢“Â&6Æ÷6R#¢Â'föÇVÖR#¢SóãÒÀ¢²&6öFR#¢%c""Â&FFR#¢###BÓÓ""Â&÷Vâ#¢Â&†–v‚#¢Â&Æ÷r#¢“Â&6Æ÷6R#¢Â'föÇVÖR#¢ƒóãÒÀ¢Ğ¢&–6W2ÒöÖ¶U÷&–6W2‡&÷w2¢&–6W2Ò÷67&VVæW"æ6ö×WFU÷&We÷föÇVÖR‡&–6W2¢&W7VÇBÒ÷67&VVæW"æÇ•öcE÷föÇVÖR‡&–6W2¢76W'BÆVâ‡&W7VÇE·&W7VÇE²&6öFR%ÒÓÒ%c"%Ò’ÓÒ  ¢FVbFW7EöæõöÆöö¶†VEö&–2‡6VÆb“ ¢""'föÇVÖU÷&Wb8Î[Ù>iz^8îX˜Şiz^Xˆn8).hÈ~8~8n8N8(¾8¾z+®Š©Ş8""" ¢&÷w2Ò°¢²&6öFR#¢%c2"Â&FFR#¢###BÓÓ"Â&÷Vâ#¢Â&†–v‚#¢Â&Æ÷r#¢“Â&6Æ÷6R#¢Â'föÇVÖR#¢SóãÒÀ¢²&6öFR#¢%c2"Â&FFR#¢###BÓÓ""Â&÷Vâ#¢Â&†–v‚#¢Â&Æ÷r#¢“Â&6Æ÷6R#¢Â'föÇVÖR#¢UóóãÒÀ¢Ğ¢&–6W2ÒöÖ¶U÷&–6W2‡&÷w2¢&–6W2Ò÷67&VVæW"æ6ö×WFU÷&We÷föÇVÖR‡&–6W2¢&÷s"Ò&–6W5·&–6W5²&FFR%ÒÓÒBåF–ÖW7F×‚###BÓÓ""•Òæ–Æö5³Ğ¢76W'B&÷s%²'föÇVÖU÷&Wb%ÒÓÒSóã   ¢2ÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒĞ¢2cS¢txè~88n8+88ûÈ89~8:Ş8*Ş8+~ûÈ¢2ÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒÒĞ ¦6Æ72FW7DcTv&FS ¢FVbFW7Eöv÷W÷76W2‡6VÆb“ ¢"""³RRtûÈ(šR³2^ûÈ8ş˜	®˜î88(¾8"""
        rows = [
            {"code": "G001", "date": "2024-01-01", "open": 1000, "high": 1100, "low": 900, "close": 1000, "volume": 1_000_000},
            {"code": "G001", "date": "2024-01-02", "open": 1050, "high": 1100, "low": 900, "close": 1000, "volume": 1_000_000},
        ]
        prices = _make_prices(rows)
        prices = _screener.compute_gap_rate(prices)
        result = _screener.apply_f5_gap_rate(prices)
        assert len(result[result["code"] == "G001"]) == 1

    def test_small_gap_fails(self):
        """+1% GAPï¼ˆ<+3%ï¼‰ã¯é™¤å¤–ã•ã‚Œã‚‹ã€‚"" ¢&÷w2Ò°¢²&6öFR#¢$s""Â&FFR#¢###BÓÓ"Â&÷Vâ#¢Â&†–v‚#¢Â&Æ÷r#¢“Â&6Æ÷6R#¢Â'föÇVÖR#¢óóÒÀ¢²&6öFR#¢$s""Â&FFR#¢###BÓÓ""Â&÷Vâ#¢Â&†–v‚#¢Â&Æ÷r#¢“Â&6Æ÷6R#¢Â'föÇVÖR#¢óóÒÀ¢Ğ¢&–6W2ÒöÖ¶U÷&–6W2‡&÷w2¢&–6W2Ò÷67&VVæW"æ6ö×WFUöv÷&FR‡&–6W2¢&W7VÇBÒ÷67&VVæW"æÇ•öcUöv÷&FR‡&–6W2¢76W'BÆVâ‡&W7VÇE·&W7VÇE²&6öFR%ÒÓÒ$s"%Ò’ÓÒ  ¢FVbFW7EöæõöÆöö¶†VEö&–2‡6VÆb“ ¢""'&Weö6Æ÷6R8Î[Ù>iz^8îX˜Şiz^{X.X
N8).Xø.xZ~8~8n8N8(¾8>88""" ¢&÷w2Ò°¢²&6öFR#¢$s2"Â&FFR#¢###BÓÓ"Â&÷Vâ#¢Â&†–v‚#¢Â&Æ÷r#¢“Â&6Æ÷6R#¢“Â'föÇVÖR#¢óóÒÀ¢²&6öFR#¢$s2"Â&FFR#¢###BÓÓ""Â&÷Vâ#¢“cÂ&†–v‚#¢Â&Æ÷r#¢“Â&6Æ÷6R#¢Â'föÇVÖR#¢óóÒÀ¢Ğ¢&–6W2ÒöÖ¶U÷&–6W2‡&÷w2¢&–6W2Ò÷67&VVæW"æ6ö×WFUöv÷&FR‡&–6W2¢&÷s"Ò&–6W5·&–6W5²&FFR%ÒÓÒBåF–ÖW7F×‚###BÓÓ""•Òæ–Æö5³Ğ¢W‡V7FVEövÒ“cò“Ò¢76W'B'2‡&÷s%²&v÷&FR%ÒÒW‡V7FVEöv’ÂRÓ` ¢FVbFW7EövöF÷våöf–Ç2‡6VÆb“ ¢"".89î8*N88®8+’t8ş™šNZIn8^8(Î8(¾8"""
        rows = [
            {"code": "G004", "date": "2024-01-01", "open": 1000, "high": 1100, "low": 900, "close": 1000, "volume": 1_000_000},
            {"code": "G004", "date": "2024-01-02", "open": 950, "high": 1100, "low": 900, "close": 1000, "volume": 1_000_000},
        ]
        prices = _make_prices(rows)
        prices = _screener.compute_gap_rate(prices)
        result = _screener.apply_f5_gap_rate(prices)
        assert len(result[result["code"] == "G004"]) == 0


# ---------------------------------------------------------------------------
# åŠ ç‚¹3: å‰é€±åŒæ—¥æ¯”å…ºæ¥é«˜ãƒ†ã‚¹ãƒˆ
# ---------------------------------------------------------------------------

class TestBonusVolumeRatio:
    def test_high_ratio_gets_bonus(self):
        """å‰é€±åŒæ—¥æ¯” 300%ï¼ˆâ‰¥200%ï¼‰ã¯åŠ ç‚¹ã•ã‚Œã‚‹ã€‚"""
        rows = []
        for i in range(8):
            vol = 3_000_000.0 if i == 6 else 1_000_000.0  # 7æ—¥ç›®ï¼ˆi=6â€‰ï¼‰: å‰æ—¥åˆ†
            rows.append({
                "code": "B001",
                "date": f"2024-01-{i+1:02d}",
                "open": 1000, "high": 1100, "low": 900, "close": 1000,
                "volume": vol,
            })
        prices = _make_prices(rows)
        prices = _screener.compute_prev_volume(prices)
        prices = _screener.compute_volume_ratio_week_ago(prices)
        prices = _screener.compute_bonus_score(prices)
        last = prices.iloc[-1]
        assert last["bonus_volume_ratio"] == 1

    def test_low_ratio_no_bonus(self):
        """å‰é€±åŒæ—¥æ¯” 150%ï¼ˆ<200%ï¼‰ã¯åŠ ç‚¹ã•ã‚Œãªã„ã€‚"""
        rows = []
        for i in range(8):
            vol = 1_500_000.0 if i == 6 else 1_000_000.0
            rows.append({
                "code": "B002",
                "date": f"2024-01-{i+1:02d}",
                "open": 1000, "high": 1100, "low": 900, "close": 1000,
                "volume": vol,
            })
        prices = _make_prices(rows)
        prices = _screener.compute_prev_volume(prices)
        prices = _screener.compute_volume_ratio_week_ago(prices)
        prices = _screener.compute_bonus_score(prices)
        last = prices.iloc[-1]
        assert last["bonus_volume_ratio"] == 0


# ---------------------------------------------------------------------------
# F2 ã‚¹ã‚­ãƒƒãƒ—ãƒ»ãƒ³ã‚¹ã‚ˆã‚‹ã³ãƒ¡ãƒ¦ãƒ³å¾Œã‚ã‚»ãƒ‹ãƒ³ã‚°ãƒ‡ãƒ¼ã‚¿
# ---------------------------------------------------------------------------

class TestSkippedFilters:
    def test_f2_emits_warning(self):
        """F2 å‘¼ã³å‡ºã—æ™‚ã« UserWarning ãŒç™ºç”Ÿã™ã‚‹ã“ã¨ã€‚"" ¢–×÷'Bv&æ–æw0¢v—F‚v&æ–æw2æ6F6…÷v&æ–æw2‡&V6÷&CÕG'VR’2s ¢v&æ–æw2ç6–×ÆVf–ÇFW"‚&Çv—2"¢÷67&VVæW"æÇ•öc%öÖ&¶WEö6÷6¶—‚¢76W'BÆVâ‡r’ÓÒ¢76W'B—77V&6Æ72‡u³Òæ6FVv÷'’ÂW6W%v&æ–ær¢76W'B$c""–â7G"‡u³ÒæÖW76vR ¢FVbFW7EöceöÆ—fUööæÇ•öæõöW'&÷"‡6VÆb“ ¢""$cnûÈ8:8*N89nX)yJûÈ8ş8988>8*ş88n8+88i˜.8¾8*8:8;Î8®8şX¹^KÙÎ88(¾8""" ¢÷67&VVæW"æÇ•öce÷&W6ÆU÷&F–õöÆ—fUööæÇ’†—5ö&6·FW7CÕG'VR ¢FVbFW7EöcuöÆ—fUööæÇ•öæõöW'&÷"‡6VÆb“ ¢""$c~ûÈ8:8*N89nX)yJûÈ8ş8988>8*ş88n8+88i˜.8¾8*8:8;Î8®8şX¹^KÙÎ88(¾8""" ¢÷67&VVæW"æÇ•öcuö&ö&EöFWF…öÆ—fUööæÇ’†—5ö&6·FW7CÕG'VR