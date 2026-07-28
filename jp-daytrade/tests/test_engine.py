"""
engine.py ã®ãƒ¦ãƒ‹ãƒƒãƒˆãƒ†ã‚¹ãƒˆã€‚

ã‚¨ãƒ³ãƒˆãƒªãƒ¼/ã‚¨ã‚°ã‚¸ãƒƒãƒˆãƒ­ã‚¸ãƒƒã‚¯ï¼ˆSL/TP/å¤§å¼•ã‘ï¼‰ã¨ã‚¹ãƒªãƒƒãƒšãƒ¼ã‚¸è£œæ­£ã®æ­£ç¢ºæ€§ã‚’æ¤œè¨¼ã™ã‚‹ã€‚
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
_BACKTEST_DIR = _REPO_ROOT / "jp-daytrade" / "backtest"


def _ensure_modules():
    """engine ã¨ screener / config ã‚’ sys.modules ã«ç™»éŒ²ã™ã‚‹ã€‚"""
    # --- strategy ãƒ‘ãƒƒã‚±ãƒ¼ã‚¸ ---
    pkg_name = "jpdaytrade_strategy"
    if pkg_name not in sys.modules:
        pkg = types.ModuleType(pkg_name)
        pkg.__path__ = [str(_STRATEGY_DIR)]
        pkg.__package__ = pkg_name
        sys.modules[pkg_name] = pkg

    cfg_name = f"{pkg_name}.config"
    if cfg_name not in sys.modules:
        spec = importlib.util.spec_from_file_location(cfg_name, _STRATEGY_DIR / "config.py")
        mod = importlib.util.module_from_spec(spec)
        mod.__package__ = pkg_name
        sys.modules[cfg_name] = mod
        spec.loader.exec_module(mod)

    scr_name = f"{pkg_name}.screener"
    if scr_name not in sys.modules:
        spec = importlib.util.spec_from_file_location(scr_name, _STRATEGY_DIR / "screener.py")
        mod = importlib.util.module_from_spec(spec)
        mod.__package__ = pkg_name
        sys.modules[scr_name] = mod
        spec.loader.exec_module(mod)

    # --- backtest ãƒ‘ãƒƒã‚±ãƒ¼ã‚¸ ---
    bt_pkg = "jpdaytrade_backtest"
    if bt_pkg not in sys.modules:
        pkg = types.ModuleType(bt_pkg)
        pkg.__path__ = [str(_BACKTEST_DIR)]
        pkg.__package__ = bt_pkg
        sys.modules[bt_pkg] = pkg

    eng_name = f"{bt_pkg}.engine"
    if eng_name not in sys.modules:
        spec = importlib.util.spec_from_file_location(eng_name, _BACKTEST_DIR / "engine.py")
        mod = importlib.util.module_from_spec(spec)
        mod.__package__ = bt_pkg
        sys.modules[eng_name] = mod
        spec.loader.exec_module(mod)

    return sys.modules[eng_name]


_engine = _ensure_modules()


# ---------------------------------------------------------------------------
# ãƒ†ã‚¹ãƒˆç”¨ãƒ˜ãƒ«ãƒ‘ãƒ¼
# ---------------------------------------------------------------------------

def _make_row(
    code: str = "T001",
    date: str = "2024-01-10",
    open_price: float = 1000.0,
    high: float = 1100.0,
    low: float = 950.0,
    close: float = 1050.0,
    bonus_score: float = 0.0,
) -> pd.Series:
    """ãƒ†ã‚¹ãƒˆç”¨ã® 1 è¡Œ Series ã‚’ç”Ÿæˆã™ã‚‹ã€‚"""
    return pd.Series({
        "code": code,
        "date": pd.Timestamp(date),
        "open": open_price,
        "high": high,
        "low": low,
        "close": close,
        "volume": 2_000_000.0,
        "bonus_score": bonus_score,
    })


_TEST_CFG = {
    "slippage": 0.001,
    "tp1_pct": 0.05,
    "tp1_ratio": 0.5,
    "tp2_pct": 0.10,
    "sl_pct": -0.02,
}
_INVESTED = 300_000.0


# ---------------------------------------------------------------------------
# ã‚¹ãƒªãƒƒãƒšãƒ¼ã‚¸ãƒ†ã‚¹ãƒˆ
# ---------------------------------------------------------------------------

class TestSlippage:
    def test_buy_slippage_increases_price(self):
        """ã‚¨ãƒ³ãƒˆãƒªãƒ¼ï¼ˆè²·ã„ï¼‰ã¯ã‚¹ãƒªãƒƒãƒšãƒ¼ã‚¸ã§é«˜ããªã‚‹ã€‚"""
        result = _engine._apply_slippage(1000.0, "buy", 0.001)
        assert result == pytest.approx(1001.0)

    def test_sell_slippage_decreases_price(self):
        """ã‚¨ã‚°ã‚¸ãƒƒãƒˆï¼ˆå£²ã‚Šï¼‰ã¯ã‚¹ãƒªãƒƒãƒšãƒ¼ã‚¸ã§ä½ããªã‚‹ã€‚"""
        result = _engine._apply_slippage(1000.0, "sell", 0.001)
        assert result == pytest.approx(999.0)

    def test_zero_slippage(self):
        """ã‚¹ãƒªãƒƒãƒšãƒ¼ã‚¸ 0 ã®å ´åˆã¯ä¾¡æ ¼å¤‰åŒ–ãªã—ã€‚"""
        assert _engine._apply_slippage(1000.0, "buy", 0.0) == pytest.approx(1000.0)
        assert _engine._apply_slippage(1000.0, "sell", 0.0) == pytest.approx(1000.0)


# ---------------------------------------------------------------------------
# ã‚¨ã‚°ã‚¸ãƒƒãƒˆãƒ­ã‚¸ãƒƒã‚¯ãƒ†ã‚¹ãƒˆ
# ---------------------------------------------------------------------------

class TestSimulateTrade:
    def test_sl_hit(self):
        """Low â‰¤ SL ä¾¡æ ¼ â†’ æåˆ‡ï¼ˆSL å„ªå…ˆï¼‰ã€‚"""
        # ã‚¨ãƒ³ãƒˆãƒªãƒ¼ä¾¡æ ¼ â‰ˆ 1001ï¼ˆã‚¹ãƒªãƒƒãƒšãƒ¼ã‚¸å¾Œï¼‰
        # SL = 1001 * 0.98 â‰ˆ 980.98
        # Low=970 â‰¤ 980.98 â†’ SL ãƒ’ãƒƒãƒˆ
        row = _make_row(open_price=1000, high=1050, low=970, close=1020)
        trade = _engine.simulate_trade(row, _INVESTED, _TEST_CFG)
        assert trade.exit_reason == "SL"
        assert trade.pnl_pct < 0

    def test_tp1_and_tp2_hit(self):
        """High â‰¥ TP2 ä¾¡æ ¼ï¼ˆSLæœªåˆ°é”ï¼‰â†’ TP1+TP2 ä¸¡æ–¹åˆ©ç¢ºã€‚"""
        # ã‚¨ãƒ³ãƒˆãƒªãƒ¼ â‰ˆ 1001
        # TP1 = 1001 * 1.05 â‰ˆ 1051.05
        # TP2 = 1001 * 1.10 â‰ˆ 1101.1
        # High=1200 â‰¥ TP2, Low=990 > SL(â‰ˆ980.98)
        row = _make_row(open_price=1000, high=1200, low=990, close=1050)
        trade = _engine.simulate_trade(row, _INVESTED, _TEST_CFG)
        assert trade.exit_reason == "TP1+TP2"
        assert trade.pnl_pct > 0

    def test_tp1_only_then_close(self):
        """High â‰¥ TP1ï¼ˆSLæœªåˆ°é”ï¼‰ã‹ã¤ High < TP2 â†’ TP1+Closeã€‚"""
        # TP1 â‰ˆ 1051, TP2 â‰ˆ 1101, High=1080ï¼ˆTP1åˆ°é”, TP2æœªåˆ°é”ï¼‰
        row = _make_row(open_price=1000, high=1080, low=990, close=1050)
        trade = _engine.simulate_trade(row, _INVESTED, _TEST_CFG)
        assert trade.exit_reason == "TP1+Close"
        assert trade.pnl_pct > 0

    def test_close_only(self):
        """TP1 æœªåˆ°é”ã‹ã¤ SL æœªåˆ°é” â†’ å¤§å¼•ã‘ã‚¯ãƒ­ãƒ¼ã‚ºã€‚"""
        # TP1 â‰ˆ 1051, SL â‰ˆ 980, High=1040ï¼ˆTP1æœªåˆ°é”ï¼‰, Low=990ï¼ˆSLæœªåˆ°é”ï¼‰
        row = _make_row(open_price=1000, high=1040, low=990, close=1030)
        trade = _engine.simulate_trade(row, _INVESTED, _TEST_CFG)
        assert trade.exit_reason == "Close"

    def test_sl_takes_priority_over_tp(self):
        """Low â‰¤ SL ã‹ã¤ High â‰¥ TP1 ã®å ´åˆã€SL å„ªå…ˆï¼ˆä¿å®ˆçš„è©•ä¾¡ï¼‰ã€‚"""
        # Low=970 â‰¤ SL(â‰ˆ980.98), High=1200 â‰¥ TP1(â‰ˆ1051)
        row = _make_row(open_price=1000, high=1200, low=970, close=1050)
        trade = _engine.simulate_trade(row, _INVESTED, _TEST_CFG)
        assert trade.exit_reason == "SL"
        assert trade.pnl_pct < 0

    def test_pnl_abs_proportional_to_invested(self):
        """pnl_abs ã¯ invested ã«æ¯”ä¾‹ã™ã‚‹ã€‚"""
        row = _make_row(open_price=1000, high=1040, low=990, close=1030)
        trade1 = _engine.simulate_trade(row, 100_000.0, _TEST_CFG)
        trade2 = _engine.simulate_trade(row, 200_000.0, _TEST_CFG)
        assert trade2.pnl_abs == pytest.approx(trade1.pnl_abs * 2, rel=1e-3)

    def test_entry_price_has_slippage(self):
        """ã‚¨ãƒ³ãƒˆãƒªãƒ¼ä¾¡æ ¼ã¯ã‚¹ãƒªãƒƒãƒšãƒ¼ã‚¸ã§ Open ã‚ˆã‚Šé«˜ã„ã€‚"""
        row = _make_row(open_price=1000)
        trade = _engine.simulate_trade(row, _INVESTED, _TEST_CFG)
        assert trade.entry_price > trade.open_price

    def test_sl_exit_price_has_slippage(self):
        """æåˆ‡ã‚¨ã‚°ã‚¸ãƒƒãƒˆä¾¡æ ¼ã¯ã‚¹ãƒªãƒƒãƒšãƒ¼ã‚¸ã§ SL ç†è«–å€¤ã‚ˆã‚Šä½ã„ã€‚"""
        row = _make_row(open_price=1000, high=1050, low=960, close=990)
        trade = _engine.simulate_trade(row, _INVESTED, _TEST_CFG)
        assert trade.exit_reason == "SL"
        sl_theoretical = trade.entry_price * (1 + _TEST_CFG["sl_pct"])
        assert trade.exit_price_full < sl_theoretical


# ---------------------------------------------------------------------------
# å¯„ã‚Šå¤©åˆ¤å®šãƒ†ã‚¹ãƒˆ
# ---------------------------------------------------------------------------

class TestYoriTen:
    def test_yori_ten_detected(self):
        """Open == Highï¼ˆå¯„ã‚Šä»˜ããŒé«˜å€¤ï¼‰ã®å ´åˆã¯å¯„ã‚Šå¤©ãƒ•ãƒ©ã‚° Trueã€‚"""
        row = _make_row(open_price=1000, high=1000, low=950, close=970)
        trade = _engine.simulate_trade(row, _INVESTED, _TEST_CFG)
        assert trade.is_yori_ten is True

    def test_not_yori_ten(self):
        """Open < Highï¼ˆé«˜å€¤ã¯å¯„ã‚Šä»˜ãå¾Œï¼‰ã¯å¯„ã‚Šå¤©ãƒ•ãƒ©ã‚° Falseã€‚"""
        row = _make_row(open_price=1000, high=1100, low=950, close=1050)
        trade = _engine.simulate_trade(row, _INVESTED, _TEST_CFG)
        assert trade.is_yori_ten is False


# ---------------------------------------------------------------------------
# ãƒ‘ãƒ•ã‚©ãƒ¼ãƒãƒ³ã‚¹æŒ‡æ¨™è¨ˆç®—ãƒ†ã‚¹ãƒˆ
# ---------------------------------------------------------------------------

class TestComputeMetrics:
    def _make_trade(self, pnl_pct: float, is_yori_ten: bool = False) -> object:
        """ãƒ€ãƒŸãƒ¼ Trade ã‚ªãƒ–ã‚¸ã‚§ã‚¯ãƒˆã‚’ç”Ÿæˆã™ã‚‹ã€‚"" ¢&WGW&âöVæv–æRåG&FR€¢FFSÒ###BÓÓ"À¢6öFSÒ%C"À¢÷Vå÷&–6SÓãÀ¢VçG'•÷&–6SÓãÀ¢6Æ÷6U÷&–6UöF“ÓSãÀ¢†–vƒÓãÀ¢Æ÷sÓ“ƒãÀ¢6Å÷&–6SÓ“ƒã“‚À¢G÷&–6SÓSãRÀ¢G%÷&–6SÓãÀ¢W†—E÷&–6UögVÆÃÓãÀ¢W†—E÷&–6U÷GÓãÀ¢W†—E÷&–6U÷G#ÓãÀ¢W†—E÷&V6öãÒ$6Æ÷6R"À¢æÅ÷7C×æÅ÷7BÀ¢æÅö'3Ó3ó¢æÅ÷7BÀ¢6†&W3Ó#“’ãrÀ¢–çfW7FVCÓ3óãÀ¢&öçW5÷66÷&SÓãÀ¢—5÷–÷&•÷FVãÖ—5÷–÷&•÷FVâÀ¢ ¢FVbFW7E÷v–å÷&FUö6Æ7VÆF–öâ‡6VÆb“ ¢"".X¹Şxèn8ÎjÚ>8~8şŠˆzé~8^8(Î8(¾8""" ¢G&FW2Ò°¢6VÆbåöÖ¶U÷G&FRƒãR’À¢6VÆbåöÖ¶U÷G&FRƒãR’À¢6VÆbåöÖ¶U÷G&FR‚Óã"’À¢6VÆbåöÖ¶U÷G&FR‚Óã"’À¢Ğ¢F–Ç•÷æÅöÆ—7BÒ²†b###BÓ×¶’³£&GÒ"ÂBçæÅö'2’f÷"’ÂB–âVçVÖW&FR‡G&FW2•Ğ¢&W7VÇBÒöVæv–æRåö6ö×WFUöÖWG&–72‡G&FW2ÂF–Ç•÷æÅöÆ—7BÂóóÂóó¢76W'B&W7VÇBçv–å÷&FRÓÒ—FW7Bæ&÷‚ƒãR ¢FVbFW7E÷&öf—Eöf7F÷%ö6Æ7VÆF–öâ‡6VÆb“ ¢""%bÒ{xşXŠy¸¢ò{xşiŞZK8ÎjÚ>8~8şŠˆzé~8^8(Î8(¾8""" ¢G&FW2Ò°¢6VÆbåöÖ¶U÷G&FRƒã’À¢6VÆbåöÖ¶U÷G&FR‚Óã"’À¢Ğ¢F–Ç•÷æÅöÆ—7BÒ²†b###BÓ×¶’³£&GÒ"ÂBçæÅö'2’f÷"’ÂB–âVçVÖW&FR‡G&FW2•Ğ¢&W7VÇBÒöVæv–æRåö6ö×WFUöÖWG&–72‡G&FW2ÂF–Ç•÷æÅöÆ—7BÂóóÂóó¢76W'B&W7VÇBç&öf—Eöf7F÷"ÓÒ—FW7Bæ&÷‚ƒãòã"Â&VÃÓRÓ2 ¢FVbFW7E÷–÷&•÷FVå÷&FR‡6VÆb“ ¢"".ZøN8(®ZJy›®yIşxè~8ÎjÚ>8~8şŠˆzé~8^8(Î8(¾ûÈƒ"óBÒS^ûÈ8""" ¢G&FW2Ò°¢6VÆbåöÖ¶U÷G&FRƒãRÂ—5÷–÷&•÷FVãÕG'VR’À¢6VÆbåöÖ¶U÷G&FRƒãRÂ—5÷–÷&•÷FVãÕG'VR’À¢6VÆbåöÖ¶U÷G&FR‚Óã"Â—5÷–÷&•÷FVãÔfÇ6R’À¢6VÆbåöÖ¶U÷G&FR‚Óã"Â—5÷–÷&•÷FVãÔfÇ6R’À¢Ğ¢F–Ç•÷æÅöÆ—7BÒ²†b###BÓ×¶’³£&GÒ"ÂBçæÅö'2’f÷"’ÂB–âVçVÖW&FR‡G&FW2•Ğ¢&W7VÇBÒöVæv–æRåö6ö×WFUöÖWG&–72‡G&FW2ÂF–Ç•÷æÅöÆ—7BÂóóÂóó¢76W'B&W7VÇBç–÷&•÷FVå÷&FRÓÒ—FW7Bæ&÷‚ƒãR ¢FVbFW7E÷¦W&õ÷G&FW2‡6VÆb“ ¢"".Xùn[É^8+Î8:Ş8îZNY8ş88~89^8*8:¾88X
N8Î‹ùN8(¾8""" ¢&W7VÇBÒöVæv–æRåö6ö×WFUöÖWG&–72…µÒÂµÒÂóóÂóó¢76W'B&W7VÇBçF÷FÅ÷G&FW2ÓÒ ¢76W'B&W7VÇBçv–å÷&FRÓÒã  