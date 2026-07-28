"""
ãƒ•ã‚©ãƒ¯ãƒ¼ãƒ‰ãƒ†ã‚¹ãƒˆçµæœãƒ¬ãƒãƒ¼ãƒˆã‚’ç”Ÿæˆã™ã‚‹ã€‚

ä½¿ã„æ–¹:
    python scripts/report_forward.py
    python scripts/report_forward.py --start 2026-04-13 --end 2026-05-13
    python scripts/report_forward.py --output results/forward/report_20260413.txt
    python scripts/report_forward.py --log-dir logs/forward --output results/forward/report.txt

å‡ºåŠ›å½¢å¼ï¼ˆãƒ†ã‚­ã‚¹ãƒˆï¼‰:
    ============================================================
      FX Phase1 ãƒ•ã‚©ãƒ¯ãƒ¼ãƒ‰ãƒ†ã‚¹ãƒˆãƒ¬ãƒãƒ¼ãƒˆ
      æœŸé–“: 2026-04-13 ã€œ 2026-05-13
    ============================================================
    ...
"""

import argparse
import os
import sys

# ãƒ—ãƒ­ã‚¸ã‚§ã‚¯ãƒˆãƒ«ãƒ¼ãƒˆã‚’ãƒ‘ã‚¹ã«è¿½åŠ 
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.abspath(os.path.join(_SCRIPT_DIR, ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from src.forward.log_aggregator import LogAggregator  # noqa: E402


def _pct_str(value: float, decimals: int = 2) -> str:
    """æç›Šç‡ã‚’ç¬¦å·ä»˜ãã®æ–‡å­—åˆ—ã«å¤‰æ›ã™ã‚‹ã€‚"""
    if value > 0:
        return f"+{value:.{decimals}f}%"
    return f"{value:.{decimals}f}%"


def _deviation_str(value: float) -> str:
    """ä¹–é›¢ç‡ã‚’ç¬¦å·ä»˜ãã®æ–‡å­—åˆ—ã«å¤‰æ›ã™ã‚‹ã€‚"""
    if value > 0:
        return f"+{value:.1f}%"
    return f"{value:.1f}%"


def build_report(
    aggregated: dict,
    deviation: dict,
    start_date: str,
    end_date: str,
) -> str:
    """
    é›†è¨ˆçµæœã‹ã‚‰ãƒ¬ãƒãƒ¼ãƒˆãƒ†ã‚­ã‚¹ãƒˆã‚’çµ„ã¿ç«‹ã¦ã‚‹ã€‚

    Args:
        aggregated: LogAggregator.aggregate() ã®è¿”ã‚Šå€¤
        deviation:  LogAggregator.compare_with_backtest() ã®è¿”ã‚Šå€¤
        start_date: é›†è¨ˆé–‹å§‹æ—¥ï¼ˆè¡¨ç¤ºç”¨ï¼‰
        end_date:   é›†è¨ˆçµ‚äº†æ—¥ï¼ˆè¡¨ç¤ºç”¨ï¼‰

    Returns:
        ãƒ¬ãƒãƒ¼ãƒˆãƒ†ã‚­ã‚¹ãƒˆæ–‡å­—åˆ—
    """
    SEP = "=" * 60

    # æœŸé–“è¡¨ç¤º
    period_start = aggregated.get("period_start") or start_date or "---"
    period_end = aggregated.get("period_end") or end_date or "---"

    lines = []
    lines.append(SEP)
    lines.append("  FX Phase1 ãƒ•ã‚©ãƒ¯ãƒ¼ãƒ‰ãƒ†ã‚¹ãƒˆãƒ¬ãƒãƒ¼ãƒˆ")
    lines.append(f"  æœŸé–“: {period_start} ã€œ {period_end}")
    lines.append(SEP)
    lines.append("")

    # ãƒ‡ãƒ¼ã‚¿ã‚¼ãƒ­ä»¶ã®åˆ¤å®š
    total_trades = aggregated.get("total_trades", 0)
    if total_trades == 0:
        lines.append("ã€ãƒ‡ãƒ¼ã‚¿ãªã—ã€‘")
        lines.append("  é›†è¨ˆæœŸé–“å†…ã«ãƒˆãƒ¬ãƒ¼ãƒ‰ãƒ‡ãƒ¼ã‚¿ãŒå­˜åœ¨ã—ã¾ã›ã‚“ã€‚")
        lines.append("  ãƒ•ã‚©ãƒ¯ãƒ¼ãƒ‰ãƒ†ã‚¹ãƒˆã‚’é–‹å§‹ã—ã€trades_YYYYMMDD.jsonl ãŒç”Ÿæˆã•ã‚Œã‚‹ã¨")
        lines.append("  æœ¬ãƒ¬ãƒãƒ¼ãƒˆã«é›†è¨ˆçµæœãŒè¡¨ç¤ºã•ã‚Œã¾ã™ã€‚")
        lines.append("")
        lines.append(SEP)
        return "\n".join(lines)

    # å…¨ä½“ã‚µãƒãƒªãƒ¼
    win_rate = aggregated.get("win_rate_pct", 0.0)
    total_pnl = aggregated.get("total_pnl_pct", 0.0)
    pf = aggregated.get("profit_factor", 0.0)
    max_dd = aggregated.get("max_drawdown_pct", 0.0)

    lines.append("ã€å…¨ä½“ã‚µãƒãƒªãƒ¼ã€‘")
    lines.append(f"  ç·ãƒˆãƒ¬ãƒ¼ãƒ‰æ•°   : {total_trades}")
    lines.append(f"  å‹ç‡           : {win_rate:.1f}%")
    lines.append(f"  ç´æç›Š         : {_pct_str(total_pnl)}")
    lines.append(f"  ãƒ—ãƒ­ãƒ•ã‚£ãƒƒãƒˆãƒ•ã‚¡ã‚¯ã‚¿ãƒ¼: {pf:.2f}")
    lines.append(f"  æœ€å¤§ãƒ‰ãƒ­ãƒ¼ãƒ€ã‚¦ãƒ³: {max_dd:.2f}%")
    lines.append("")
    # ãƒãƒƒã‚¯ãƒ†ã‚¹ãƒˆä¹–é›¢åˆ†æ
    mr_expected = deviation.get("monthly_return_expected", 0.0)
    mr_actual = deviation.get("monthly_return_actual", 0.0)
    mr_dev = deviation.get("monthly_return_deviation_pct", 0.0)
    dd_expected = deviation.get("max_dd_expected", 0.0)
    dd_actual = deviation.get("max_dd_actual", 0.0)
    dd_dev = deviation.get("max_dd_deviation_pct", 0.0)

    lines.append("ã€ãƒãƒƒã‚¯ãƒ†ã‚¹ãƒˆä¹–é›¢åˆ†æã€‘")
    lines.append(
        f"  æœˆåˆ©ï¼ˆæœŸå¾…/å®Ÿç¸¾/ä¹–é›¢ï¼‰: {mr_expected:.2f}% / "
        f"{_pct_str(mr_actual)} / {_deviation_str(mr_dev)}"
    )
    lines.append(
        f"  MaxDDï¼ˆæœŸå¾…/å®Ÿç¸¾/ä¹–é›¢ï¼‰: {dd_expected:.2f}% / "
        f"{dd_actual:.2f}% / {_deviation_str(dd_dev)}"
    )
    lines.append("")

    # æˆ¦ç•¥åˆ¥å†…è¨³
    by_strategy = aggregated.get("by_strategy", {})
    lines.append("ã€æˆ¦ç•¥åˆ¥å†…è¨³ã€‘")

    strategy_display = {
        "mtf_confluence":    "mtf_confluence ",
        "rsi_divergence":    "rsi_divergence ",
        "bb_reversion_USDJPY": "bb_rev_USDJPY  ",
        "bb_reversion_EURJPY": "bb_rev_EURJPY  ",
    }

    for key, display_name in strategy_display.items():
        s = by_strategy.get(key, {})
        n = s.get("total_trades", 0)
        wr = s.get("win_rate_pct", 0.0)
        pnl = s.get("total_pnl_pct", 0.0)
        pnl_str = _pct_str(pnl)
        lines.append(
            f"  {display_name}: {n:3d} trades, WR {wr:5.1f}%, PnL {pnl_str}"
        )
    lines.append("")

    # ã‚µãƒ¼ã‚­ãƒƒãƒˆãƒ–ãƒ¬ãƒ¼ã‚«ãƒ¼ç™ºå‹•
    cb = aggregated.get("cb_triggers", {})
    lines.append("ã€ã‚µãƒ¼ã‚­ãƒƒãƒˆãƒ–ãƒ¬ãƒ¼ã‚«ãƒ¼ç™ºå‹•ã€‘")
    lines.append(f"  CB1ï¼ˆé€£æ•—5fç»ï"HˆØØ‹™Ù]
	ØØŒIË
_yfçˆŠBˆ[™\Ë˜\[™
ˆˆĞŒ»ï"9§"9«(QLL	{ï"HˆØØ‹™Ù]
	ØØŒ‰Ë
_yfçˆŠBˆ[™\Ë˜\[™
ˆˆĞŒûï"9í+ùêcQLI{ï"HˆØØ‹™Ù]
	ØØŒÉË
_yfçˆŠBˆ[™\Ë˜\[™
ˆˆĞŒ;ï"9bcy§"8àç¸à©8àâ¸à®{ï"NˆØØ‹™Ù]
	ØØ	Ë
_yfçˆŠBˆ[™\Ë˜\[™
ˆŠB‚ˆÈ9¥éy«(y¤#yæâ¹£ª9éîÂˆZ[WÜ›HYÙÜ™YØ]Y™Ù]
™Z[WÜ›‹×JBˆYˆZ[WÜ›‚ˆ[™\Ë˜\[™
¸à$9¥éy«(y¤#yæâ¹£ª9éîøà$HŠBˆİ[][]]™HHŒˆ›Üˆ[H[ˆZ[WÜ›‚ˆH[K™Ù]
™]H‹ˆŠBˆ›ÙH[K™Ù]
œ›Üİ‹Œ
Bˆİ[][]]™H
ÏH›Ùˆ[™\Ë˜\[™
ˆˆˆÙH×ÜİÜİŠ›ÙÊNŒLßH
9í+ú*"ˆ×ÜİÜİŠİ[][]]™KÊ_JH‚ˆ
Bˆ[™\Ë˜\[™
ˆŠB‚ˆ[™\Ë˜\[™
ÑT
Bˆ™]\›ˆ—ˆ‹š›Ú[Š[™\ÊB