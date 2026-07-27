# -*- coding: utf-8 -*-
"""①RSI(2)平均回帰シグナルエンジン (SPY/QQQ, ペーパートレード)

買い: 終値>200SMA かつ RSI(2)<10 → 当日終値でエントリー
決済: RSI(2)>70 または 終値>前日高値 → 当日終値でクローズ
"""
import datetime as dt

import pandas as pd
import yfinance as yf

from common import load_config, load_state, save_state, append_ledger, notify


def rsi(series: pd.Series, n: int) -> pd.Series:
    delta = series.diff()
    up = delta.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-delta.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / (dn + 1e-12))


def fetch_daily(symbol: str) -> pd.DataFrame:
    df = yf.download(symbol, period="400d", interval="1d",
                     progress=False, auto_adjust=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] for c in df.columns]
    return df.dropna()


def run():
    cfg = load_config()
    p = cfg["rsi2"]
    state = load_state(cfg, "positions.json", {})
    lines = []
    signals = 0
    alerts = 0
    for sym in p["symbols"]:
        df = fetch_daily(sym)
        if len(df) < p["ma_filter"] + 5:
            lines.append(f"⚠️ {sym}: データ不足({len(df)}本) — yfinance障害の可能性。要確認")
            alerts += 1
            continue
        c = df["Close"]
        r2 = rsi(c, p["rsi_period"])
        ma = c.rolling(p["ma_filter"]).mean()
        bar_date = str(df.index[-1].date())
        close = float(c.iloc[-1])
        r2_now = float(r2.iloc[-1])
        above_ma = close > float(ma.iloc[-1])
        prev_high = float(df["High"].iloc[-2])

        st = state.get(sym, {"pos": False, "last_bar": ""})
        if st.get("last_bar") == bar_date:
            lines.append(f"{sym}: 処理済み({bar_date})")
            continue
        st["last_bar"] = bar_date

        if not st["pos"]:
            if r2_now < p["buy_below"] and above_ma:
                st.update(pos=True, entry_price=close, entry_date=bar_date)
                append_ledger(cfg, dict(date=bar_date, strategy="RSI2", symbol=sym,
                                        action="BUY", price=round(close, 2), pnl_pct=""))
                lines.append(f"🟢 {sym} 買いシグナル @ {close:.2f} (RSI2={r2_now:.1f})")
                signals += 1
            else:
                lines.append(f"{sym}: ノーポジ待機 (RSI2={r2_now:.1f}, "
                             f"{'MA上' if above_ma else 'MA下'})")
        else:
            exit_sig = r2_now > p["exit_above"] or close > prev_high
            if exit_sig:
                pnl = (close / st["entry_price"] - 1) * 100 - p["cost_bp"] / 100
                st.update(pos=False)
                append_ledger(cfg, dict(date=bar_date, strategy="RSI2", symbol=sym,
                                        action="SELL", price=round(close, 2),
                                        pnl_pct=round(pnl, 3)))
                lines.append(f"🔴 {sym} 決済シグナル @ {close:.2f} "
                             f"(損益 {pnl:+.2f}%, RSI2={r2_now:.1f})")
                signals += 1
            else:
                held = (dt.date.fromisoformat(bar_date)
                        - dt.date.fromisoformat(st["entry_date"])).days
                lines.append(f"🟡 {sym} 保有中 {held}日目 "
                             f"(建値{st['entry_price']:.2f}→{close:.2f}, RSI2={r2_now:.1f})")
        state[sym] = st

    save_state(cfg, "positions.json", state)
    body = "📈 RSI2シグナル " + str(dt.date.today()) + "\n" + "\n".join(lines)
    holding = any(state.get(s, {}).get("pos") for s in p["symbols"])
    is_heartbeat = dt.date.today().weekday() == cfg["notify"]["heartbeat_weekday"]
    if signals or alerts or holding or is_heartbeat or not cfg["notify"]["quiet_when_no_signal"]:
        notify(body)
    else:
        print(body)


if __name__ == "__main__":
    run()
