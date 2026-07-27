# -*- coding: utf-8 -*-
"""②CMEベーシス + ファンディング監視 (ルートA: MBTショート+国内現物ロング)

- CME先物(BTC=F 期近)と現物(BTC-USD)のベーシスを年率換算
- Binance perpファンディング3日平均を算出
- エントリー/警戒/ロールの推奨を通知
"""
import calendar
import datetime as dt
import json
import urllib.request

import yfinance as yf

from common import load_config, load_state, save_state, append_ledger, notify


def last_friday(y, m):
    cal = calendar.Calendar()
    fridays = [d for d in cal.itermonthdates(y, m) if d.month == m and d.weekday() == 4]
    return fridays[-1]


def next_expiry(today):
    e = last_friday(today.year, today.month)
    if (e - today).days < 3:  # ロール期は翌限月
        nm = today.replace(day=1) + dt.timedelta(days=32)
        e = last_friday(nm.year, nm.month)
    return e


def binance_funding_3d():
    url = "https://fapi.binance.com/fapi/v1/fundingRate?symbol=BTCUSDT&limit=9"
    req = urllib.request.Request(url, headers={"User-Agent": "curl/8.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        d = json.loads(r.read())
    rates = [float(x["fundingRate"]) for x in d]
    avg8h = sum(rates) / len(rates)
    return avg8h * 3 * 365  # 年率換算


def run():
    cfg = load_config()
    p = cfg["basis"]
    today = dt.date.today()

    fut = yf.download("BTC=F", period="5d", progress=False, auto_adjust=False)["Close"]
    spot = yf.download("BTC-USD", period="5d", progress=False, auto_adjust=False)["Close"]
    f = float(fut.iloc[-1].iloc[0] if hasattr(fut.iloc[-1], "iloc") else fut.iloc[-1])
    s = float(spot.iloc[-1].iloc[0] if hasattr(spot.iloc[-1], "iloc") else spot.iloc[-1])

    expiry = next_expiry(today)
    days = max((expiry - today).days, 1)
    basis = f / s - 1
    basis_ann = basis * 365 / days

    alerts = 0
    try:
        funding_ann = binance_funding_3d()
    except Exception as e:
        funding_ann = float("nan")
        alerts += 1
        print("funding fetch error:", e)

    st = load_state(cfg, "basis_state.json", {"active": False})
    already_ran = st.get("last_run") == str(today)
    st["last_run"] = str(today)
    lines = [f"🏦 CMEベーシス監視 {today}",
             f"先物 {f:,.0f} / 現物 {s:,.0f}",
             f"ベーシス {basis*100:+.2f}% (満期{expiry}まで{days}日, 年率換算 {basis_ann*100:+.1f}%)",
             ("⚠️ Binanceファンディング取得失敗 — API障害の可能性。要確認"
              if funding_ann != funding_ann else
              f"Binanceファンディング3日平均: 年率 {funding_ann*100:+.1f}%")]

    reco = None
    if not st["active"]:
        if basis_ann >= p["entry_threshold_ann"] and funding_ann > 0:
            reco = (f"✅ エントリー検討: ベーシス年率{basis_ann*100:.1f}% ≥ 5%。"
                    f"MBT 1枚ショート + 現物{p['notional_btc']}BTC買いの組成条件を満たしています")
        else:
            lines.append("→ 待機（条件未達）")
    else:
        if days <= 5:
            reco = f"🔄 ロール推奨: 満期まで{days}日。翌限月への乗り換え時期です"
        elif basis_ann < 0:
            reco = "⚠️ ベーシスがマイナス転換。クローズ検討"
        elif funding_ann < 0:
            reco = "⚠️ ファンディング3日平均がマイナス。市場の需給反転に注意"
        else:
            lines.append("→ ポジション維持")

    if reco:
        lines.append(reco)
    if not already_ran:  # 同日再実行時は台帳の重複記録を防ぐ
        append_ledger(cfg, dict(date=str(today), strategy="BASIS", symbol="BTC",
                                action="MONITOR", price=round(basis_ann * 100, 2),
                                pnl_pct=round(funding_ann * 100, 2) if funding_ann == funding_ann else ""))
    save_state(cfg, "basis_state.json", st)

    is_heartbeat = today.weekday() == cfg["notify"]["heartbeat_weekday"]
    if reco or alerts or is_heartbeat or not cfg["notify"]["quiet_when_no_signal"]:
        notify("\n".join(lines))
    else:
        print("\n".join(lines))


if __name__ == "__main__":
    run()
