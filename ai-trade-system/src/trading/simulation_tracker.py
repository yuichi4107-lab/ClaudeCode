"""
シミュレーション（ペーパートレード）トラッカー

全シグナルを「仮想トレード」として記録し、実売買の有無に関わらず
戦略ごとの収支を追跡する。週次・月次レポートを生成。

実トレードとは独立して動作し、data/simulation/ に状態を永続化する。
"""
import os
import json
from datetime import datetime, timezone, timedelta

JST = timezone(timedelta(hours=9))
from collections import defaultdict

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
SIM_DIR = os.path.join(PROJECT_ROOT, "data/simulation")
SIM_POSITIONS_FILE = os.path.join(SIM_DIR, "sim_positions.json")
SIM_HISTORY_FILE = os.path.join(SIM_DIR, "sim_history.json")
SIM_REPORTS_DIR = os.path.join(SIM_DIR, "reports")


class SimulationTracker:
    """仮想トレード記録・管理"""

    def __init__(self):
        os.makedirs(SIM_DIR, exist_ok=True)
        os.makedirs(SIM_REPORTS_DIR, exist_ok=True)
        self.positions = self._load_json(SIM_POSITIONS_FILE, {})
        self.history = self._load_json(SIM_HISTORY_FILE, [])

    def _load_json(self, path, default):
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        return default

    def _save_positions(self):
        with open(SIM_POSITIONS_FILE, "w", encoding="utf-8") as f:
            json.dump(self.positions, f, indent=2, ensure_ascii=False)

    def _save_history(self):
        with open(SIM_HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(self.history, f, indent=2, ensure_ascii=False)

    def _now(self):
        """現在時刻を返す。テスト時に差し替えやすいようメソッド化する。"""
        return datetime.now(JST)

    def _parse_opened_at(self, pos):
        opened_at = pos.get("opened_at")
        if not opened_at:
            return None
        try:
            opened = datetime.fromisoformat(opened_at)
        except (TypeError, ValueError):
            return None
        if opened.tzinfo is None:
            opened = opened.replace(tzinfo=JST)
        return opened.astimezone(JST)

    def _elapsed_hold_days(self, pos, now=None):
        """エントリーからの実経過日数（24時間単位）を返す。"""
        opened = self._parse_opened_at(pos)
        if opened is None:
            return pos.get("bars_held", 0)
        now = now or self._now()
        if now.tzinfo is None:
            now = now.replace(tzinfo=JST)
        elapsed = now.astimezone(JST) - opened
        return max(0, elapsed.days)

    def _is_hold_expired(self, pos, now=None):
        """保有期間が実日数で満了しているか判定する。"""
        opened = self._parse_opened_at(pos)
        hold_days = int(pos.get("hold_bars", 0) or 0)
        if opened is None:
            return pos.get("bars_held", 0) >= hold_days
        now = now or self._now()
        if now.tzinfo is None:
            now = now.replace(tzinfo=JST)
        return now.astimezone(JST) >= opened + timedelta(days=hold_days)

    def record_signal(self, symbol, strategy_id, entry_price, stop_loss_pct,
                      take_profit_pct, hold_bars, signal_data=None):
        """
        シグナル検出時に仮想ポジションをオープンする。

        既にポジション有りの場合でも、戦略評価のため別キーで記録する。
        """
        now = self._now()
        # 同一戦略で複数ポジションを持てるよう、タイムスタンプ付きキーを使用
        position_key = f"{symbol}:{strategy_id}:{now.strftime('%Y%m%d_%H%M%S')}"

        position = {
            "symbol": symbol,
            "strategy_id": strategy_id,
            "position_key": position_key,
            "entry_price": entry_price,
            "stop_loss_pct": stop_loss_pct,
            "take_profit_pct": take_profit_pct,
            "stop_loss_price": entry_price * (1 - stop_loss_pct) if stop_loss_pct else None,
            "take_profit_price": entry_price * (1 + take_profit_pct) if take_profit_pct else None,
            "hold_bars": hold_bars,
            "bars_held": 0,
            "opened_at": now.isoformat(),
            "closed_at": None,
            "exit_price": None,
            "pnl_pct": None,
            "close_reason": None,
        }

        self.positions[position_key] = position
        self._save_positions()
        print(f"    [SIM] Opened: {symbol}[{strategy_id}] @ {entry_price:,.2f}")
        return position

    def update_positions(self, price_getter):
        """
        全仮想ポジションの日次チェック。

        Args:
            price_getter: callable(symbol) -> float  現在価格を返す関数
        """
        closed_keys = []

        for key, pos in list(self.positions.items()):
            if pos.get("closed_at"):
                continue

            pos["bars_held"] = self._elapsed_hold_days(pos)

            try:
                current_price = price_getter(pos["symbol"])
            except Exception as e:
                print(f"    [SIM] Price fetch failed for {pos['symbol']}: {e}")
                continue

            # SL/TP/Hold チェック
            reason = None
            exit_price = current_price

            if pos["stop_loss_price"] and current_price <= pos["stop_loss_price"]:
                reason = "stop_loss"
                exit_price = pos["stop_loss_price"]
            elif pos["take_profit_price"] and current_price >= pos["take_profit_price"]:
                reason = "take_profit"
                exit_price = pos["take_profit_price"]
            elif self._is_hold_expired(pos):
                reason = "hold_expired"

            if reason:
                self._close_position(key, exit_price, reason)
                closed_keys.append(key)
            else:
                pnl_pct = (current_price - pos["entry_price"]) / pos["entry_price"] * 100
                print(f"    [SIM] {pos['symbol']}[{pos['strategy_id']}]: "
                      f"Price {current_price:,.2f} | PnL {pnl_pct:+.2f}% | "
                      f"Day {pos['bars_held']}/{pos['hold_bars']}")

        self._save_positions()

    def _close_position(self, key, exit_price, reason):
        """仮想ポジションを決済する"""
        pos = self.positions[key]
        entry = pos["entry_price"]
        pnl_pct = (exit_price - entry) / entry * 100

        pos["exit_price"] = exit_price
        pos["pnl_pct"] = round(pnl_pct, 2)
        pos["close_reason"] = reason
        pos["closed_at"] = self._now().isoformat()

        # 履歴に追加
        self.history.append(pos)
        self._save_history()

        # アクティブポジションから削除
        del self.positions[key]

        reason_label = {
            "stop_loss": "SL",
            "take_profit": "TP",
            "hold_expired": "HOLD",
        }.get(reason, reason)

        print(f"    [SIM] Closed: {pos['symbol']}[{pos['strategy_id']}] "
              f"@ {exit_price:,.2f} | PnL {pnl_pct:+.2f}% | {reason_label}")

    def generate_report(self, period="week"):
        """
        週次または月次レポートを生成する。

        Args:
            period: "week" or "month"
        Returns:
            dict: レポートデータ
        """
        now = datetime.now(JST)

        if period == "week":
            cutoff = now - timedelta(days=7)
            period_label = f"Weekly ({cutoff.strftime('%m/%d')}~{now.strftime('%m/%d')})"
        else:
            cutoff = now - timedelta(days=30)
            period_label = f"Monthly ({cutoff.strftime('%m/%d')}~{now.strftime('%m/%d')})"

        # 期間内の決済済みトレードをフィルタ
        period_trades = [
            t for t in self.history
            if t.get("closed_at") and datetime.fromisoformat(t["closed_at"]) >= cutoff
        ]

        # 戦略別集計
        by_strategy = defaultdict(list)
        for t in period_trades:
            key = f"{t['symbol']}:{t['strategy_id']}"
            by_strategy[key].append(t)

        # 全体集計
        total_trades = len(period_trades)
        wins = [t for t in period_trades if t.get("pnl_pct", 0) > 0]
        losses = [t for t in period_trades if t.get("pnl_pct", 0) <= 0]
        avg_pnl = sum(t.get("pnl_pct", 0) for t in period_trades) / total_trades if total_trades else 0

        report = {
            "period": period_label,
            "generated_at": now.isoformat(),
            "summary": {
                "total_trades": total_trades,
                "wins": len(wins),
                "losses": len(losses),
                "win_rate": round(len(wins) / total_trades * 100, 1) if total_trades else 0,
                "avg_pnl_pct": round(avg_pnl, 2),
                "total_pnl_pct": round(sum(t.get("pnl_pct", 0) for t in period_trades), 2),
                "best_trade_pnl_pct": round(max((t.get("pnl_pct", 0) for t in period_trades), default=0), 2),
                "worst_trade_pnl_pct": round(min((t.get("pnl_pct", 0) for t in period_trades), default=0), 2),
            },
            "by_strategy": {},
            "open_positions": len(self.positions),
        }

        for strat_key, trades in sorted(by_strategy.items()):
            s_wins = [t for t in trades if t.get("pnl_pct", 0) > 0]
            s_total_pnl = sum(t.get("pnl_pct", 0) for t in trades)
            close_reasons = defaultdict(int)
            for t in trades:
                close_reasons[t.get("close_reason", "unknown")] += 1

            report["by_strategy"][strat_key] = {
                "trades": len(trades),
                "wins": len(s_wins),
                "win_rate": round(len(s_wins) / len(trades) * 100, 1) if trades else 0,
                "total_pnl_pct": round(s_total_pnl, 2),
                "avg_pnl_pct": round(s_total_pnl / len(trades), 2) if trades else 0,
                "close_reasons": dict(close_reasons),
            }

        return report

    def format_report(self, report):
        """レポートを見やすいテキストに整形する"""
        lines = []
        s = report["summary"]
        lines.append(f"\n{'='*60}")
        lines.append(f"  SIMULATION REPORT - {report['period']}")
        lines.append(f"{'='*60}")
        lines.append(f"  Total trades: {s['total_trades']} ({s['wins']}W / {s['losses']}L)")
        lines.append(f"  Win rate: {s['win_rate']}%")
        lines.append(f"  Avg PnL: {s['avg_pnl_pct']:+.2f}%")
        lines.append(f"  Total PnL: {s['total_pnl_pct']:+.2f}%")
        lines.append(f"  Best: {s['best_trade_pnl_pct']:+.2f}% | Worst: {s['worst_trade_pnl_pct']:+.2f}%")
        lines.append(f"  Open positions: {report['open_positions']}")

        if report["by_strategy"]:
            lines.append(f"\n  {'─'*56}")
            lines.append(f"  Strategy Breakdown:")
            lines.append(f"  {'─'*56}")
            for strat, data in report["by_strategy"].items():
                reasons = ", ".join(f"{k}:{v}" for k, v in data["close_reasons"].items())
                lines.append(f"  {strat}:")
                lines.append(f"    {data['trades']} trades | WR {data['win_rate']}% | "
                             f"PnL {data['total_pnl_pct']:+.2f}% (avg {data['avg_pnl_pct']:+.2f}%)")
                lines.append(f"    Exit: {reasons}")

        lines.append(f"{'='*60}")
        return "\n".join(lines)

    def save_report(self, report):
        """レポートをファイルに保存する"""
        now = datetime.now(JST)
        filename = f"report_{now.strftime('%Y%m%d_%H%M%S')}.json"
        path = os.path.join(SIM_REPORTS_DIR, filename)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        print(f"  [SIM] Report saved: {path}")
        return path

    def print_status(self):
        """現在のシミュレーション状況を表示する"""
        open_count = len(self.positions)
        closed_count = len(self.history)

        print(f"\n  [SIM] Status: {open_count} open, {closed_count} closed")

        for key, pos in self.positions.items():
            print(f"    {pos['symbol']}[{pos['strategy_id']}]: "
                  f"Entry {pos['entry_price']:,.2f} | "
                  f"Day {pos['bars_held']}/{pos['hold_bars']}")
