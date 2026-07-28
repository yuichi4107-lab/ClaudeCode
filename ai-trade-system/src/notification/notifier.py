"""
通知システム

Discord Webhook / LINE Messaging API に対応。
売買シグナル、エントリー、決済、日次サマリーを通知する。
"""
import os
import json
import requests
from datetime import datetime, timezone, timedelta

JST = timezone(timedelta(hours=9))
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "../../.env"))


class Notifier:
    """通知の送信を管理する"""

    def __init__(self):
        self.discord_url = os.getenv("DISCORD_WEBHOOK_URL", "")
        self.line_token = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "")
        self.line_user_id = os.getenv("LINE_USER_ID", "")
        self._line_quota_exhausted = False

        self.channels = []
        if self.discord_url:
            self.channels.append("discord")
        if self.line_token and self.line_user_id:
            self.channels.append("line")

    def is_configured(self):
        return len(self.channels) > 0

    def send(self, message, title=None):
        """全設定済みチャネルにメッセージを送信する"""
        results = {}
        for ch in self.channels:
            if ch == "discord":
                results["discord"] = self._send_discord(message, title)
            elif ch == "line":
                results["line"] = self._send_line(message)
        return results

    def _send_discord(self, message, title=None):
        """Discord Webhookに送信"""
        payload = {}
        if title:
            payload["embeds"] = [{
                "title": title,
                "description": message,
                "color": 0x26a69a,
                "timestamp": datetime.now(JST).isoformat(),
            }]
        else:
            payload["content"] = message

        try:
            resp = requests.post(self.discord_url, json=payload, timeout=10)
            resp.raise_for_status()
            return True
        except Exception as e:
            print(f"  [Discord] Send failed: {e}")
            return False

    def _send_line(self, message):
        """LINE Messaging APIで送信"""
        if self._line_quota_exhausted or self._is_line_quota_exhausted():
            print("  [LINE] Send skipped: monthly quota exhausted")
            return False

        url = "https://api.line.me/v2/bot/message/push"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.line_token}",
        }
        payload = {
            "to": self.line_user_id,
            "messages": [{"type": "text", "text": message}],
        }
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=10)
            resp.raise_for_status()
            return True
        except Exception as e:
            print(f"  [LINE] Send failed: {e}")
            return False

    def _is_line_quota_exhausted(self):
        """LINEの月間送信上限到達を事前確認する。確認失敗時は送信を試す。"""
        headers = {"Authorization": f"Bearer {self.line_token}"}
        try:
            quota_resp = requests.get(
                "https://api.line.me/v2/bot/message/quota",
                headers=headers,
                timeout=10,
            )
            usage_resp = requests.get(
                "https://api.line.me/v2/bot/message/quota/consumption",
                headers=headers,
                timeout=10,
            )
            quota_resp.raise_for_status()
            usage_resp.raise_for_status()
            quota = quota_resp.json()
            usage = usage_resp.json()
            if quota.get("type") == "limited":
                limit = int(quota.get("value", 0) or 0)
                used = int(usage.get("totalUsage", 0) or 0)
                if limit > 0 and used >= limit:
                    self._line_quota_exhausted = True
                    return True
        except Exception as e:
            print(f"  [LINE] Quota check failed: {e}")
        return False


def format_signal_alert(signal_data, quote_currency="USDT"):
    """シグナル検出時の通知メッセージを生成"""
    sym = signal_data["symbol"]
    price = signal_data["latest_price"]
    strategy = signal_data["strategy"]
    sl = strategy.get("stop_loss")
    tp = strategy.get("take_profit")
    hold = strategy.get("hold_bars")
    fmt = ",.0f" if quote_currency == "JPY" else ",.2f"

    lines = [
        f"🔔 シグナル検出: {sym}",
        f"",
        f"📈 パターン: {signal_data.get('pattern', 'N/A')}",
        f"💰 価格: {price:{fmt}} {quote_currency}",
    ]
    if sl:
        sl_price = price * (1 - sl)
        lines.append(f"🛑 SL: {sl_price:{fmt}} ({sl*100}%)")
    if tp:
        tp_price = price * (1 + tp)
        lines.append(f"🎯 TP: {tp_price:{fmt}} ({tp*100}%)")
    lines.append(f"⏱️ 保有期間: {hold}日")

    return "\n".join(lines)


def format_entry_alert(symbol, entry_price, amount, order_id, strategy, quote_currency="USDT"):
    """エントリー通知メッセージを生成"""
    sl = strategy.get("stop_loss")
    tp = strategy.get("take_profit")
    hold = strategy.get("hold_bars")
    fmt = ",.0f" if quote_currency == "JPY" else ",.2f"

    lines = [
        f"✅ エントリー実行: {symbol}",
        f"",
        f"💰 価格: {entry_price:{fmt}} {quote_currency}",
        f"📦 数量: {amount}",
        f"🆔 注文ID: {order_id}",
    ]
    if sl:
        lines.append(f"🛑 SL: {entry_price * (1 - sl):{fmt}} ({sl*100}%)")
    if tp:
        lines.append(f"🎯 TP: {entry_price * (1 + tp):{fmt}} ({tp*100}%)")
    lines.append(f"⏱️ 保有期間: {hold}日")

    return "\n".join(lines)


def format_exit_alert(position, quote_currency="USDT"):
    """決済通知メッセージを生成"""
    sym = position["symbol"]
    entry = position["entry_price"]
    exit_p = position["exit_price"]
    pnl = position.get("pnl", 0)
    pnl_pct = position.get("pnl_pct", 0)
    reason = position.get("close_reason", "unknown")
    fmt = ",.0f" if quote_currency == "JPY" else ",.2f"
    pnl_fmt = ",.0f" if quote_currency == "JPY" else ",.4f"

    reason_label = {
        "closed_sl": "損切り (SL)",
        "closed_tp": "利確 (TP)",
        "closed_hold": "保有期間満了",
        "closed_manual": "手動決済",
    }.get(reason, reason)

    emoji = "📉" if pnl < 0 else "📈"

    lines = [
        f"{emoji} 決済完了: {sym}",
        f"",
        f"📋 理由: {reason_label}",
        f"💰 エントリー: {entry:{fmt}}",
        f"💰 決済: {exit_p:{fmt}}",
        f"{'📉' if pnl < 0 else '📈'} PnL: {pnl:+{pnl_fmt}} {quote_currency} ({pnl_pct:+.2f}%)",
    ]

    return "\n".join(lines)


def format_daily_summary(positions, trade_history, balances=None, quote_currency="USDT"):
    """日次サマリーメッセージを生成"""
    now = datetime.now(JST).strftime("%Y-%m-%d")
    fmt = ",.0f" if quote_currency == "JPY" else ",.2f"
    pnl_fmt = ",.0f" if quote_currency == "JPY" else ",.4f"

    lines = [
        f"📊 日次レポート: {now}",
        f"{'='*30}",
    ]

    # オープンポジション
    if positions:
        lines.append(f"")
        lines.append(f"📂 オープンポジション: {len(positions)}件")
        for sym, pos in positions.items():
            lines.append(f"  • {sym}: {pos['entry_price']:{fmt}} | Day {pos['bars_held']}/{pos['hold_bars']}")
    else:
        lines.append(f"")
        lines.append(f"📂 オープンポジション: なし")

    # 本日のトレード
    today_trades = [
        t for t in trade_history
        if t.get("closed_at", "").startswith(now)
    ]
    if today_trades:
        wins = sum(1 for t in today_trades if t.get("pnl", 0) > 0)
        total_pnl = sum(t.get("pnl", 0) for t in today_trades)
        lines.append(f"")
        lines.append(f"📈 本日のトレード: {len(today_trades)}件 ({wins}W/{len(today_trades)-wins}L)")
        lines.append(f"💰 本日PnL: {total_pnl:+{pnl_fmt}} {quote_currency}")

    # 累計
    if trade_history:
        total_wins = sum(1 for t in trade_history if t.get("pnl", 0) > 0)
        cumulative_pnl = sum(t.get("pnl", 0) for t in trade_history)
        lines.append(f"")
        lines.append(f"📊 累計: {len(trade_history)}件 ({total_wins}W/{len(trade_history)-total_wins}L)")
        lines.append(f"💰 累計PnL: {cumulative_pnl:+{pnl_fmt}} {quote_currency}")

    # 残高
    if balances:
        bal = balances.get(quote_currency, {}).get("total", "N/A")
        lines.append(f"")
        lines.append(f"💳 残高: {bal} {quote_currency}")

    return "\n".join(lines)


def format_error_alert(error_message, context=""):
    """エラー通知メッセージを生成"""
    lines = [
        f"⚠️ エラー発生",
        f"",
        f"📋 {context}" if context else "",
        f"❌ {error_message}",
        f"⏰ {datetime.now(JST).strftime('%Y-%m-%d %H:%M:%S JST')}",
    ]
    return "\n".join(line for line in lines if line)
