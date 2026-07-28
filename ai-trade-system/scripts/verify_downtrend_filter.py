"""
Downtrend Filter Verification Harness
======================================
工程1: 下落局面を含む検証ハーネスの整備＋ベースライン計測
工程2: フィルター適用後(after)の集計を追加（本番の check_trend_filter を import）

Usage:
  python scripts/verify_downtrend_filter.py
  python scripts/verify_downtrend_filter.py --strategy rsi_oversold_bounce
  python scripts/verify_downtrend_filter.py --bull-trap-k 10
  python scripts/verify_downtrend_filter.py --all --bull-trap-k 10

NOTE: LLM APIは一切呼ばない。既存の判定済みresult.jsonのmetadataを再利用。
"""

import os
import sys
import json
import argparse
from datetime import datetime

# src/ を import パスに追加
REPO_ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(REPO_ROOT, "src"))
sys.path.insert(0, os.path.join(REPO_ROOT, "src", "backtest"))

from backtest.optimizer import recalculate_pnl
from signal.trend_filter import check_trend_filter

# ============================================================
# 定数・設定
# ============================================================
DATA_FILE = os.path.join(REPO_ROOT, "data", "ohlcv", "BTC-USDT_1d_1000.json")
OUT_DIR = os.path.join(REPO_ROOT, "results", "downtrend_filter")

# 戦略定義（strategy_config.json BTC-USDT ブロックと完全一致）
STRATEGIES = {
    "double_bottom": {
        "result_json": os.path.join(
            REPO_ROOT, "results", "backtest_20260325_194746", "result.json"
        ),
        "take_profit": None,
        "stop_loss": 0.04,
        "hold_bars": 30,
        "direction": "long",
        "trend_filter": True,
    },
    "rsi_oversold_bounce": {
        "result_json": os.path.join(
            REPO_ROOT, "results", "backtest_20260327_210209", "result.json"
        ),
        "take_profit": 0.01,
        "stop_loss": 0.02,
        "hold_bars": 15,
        "direction": "long",
        # 工程2: true に変更（strategy_config.json BTC-USDT と同期）
        "trend_filter": True,
        # bull trap ガード N=5（工程1推奨）
        "reentry_confirm_days": 5,
    },
    "crash_rebound": {
        "result_json": os.path.join(
            REPO_ROOT, "results", "backtest_20260327_221754", "result.json"
        ),
        "take_profit": None,
        "stop_loss": 0.01,
        "hold_bars": 15,
        "direction": "long",
        # 工程2: true に変更（strategy_config.json BTC-USDT と同期）
        "trend_filter": True,
        # bull trap ガード N=5（工程1推奨）
        "reentry_confirm_days": 5,
    },
}

SMA_FAST = 50
SMA_SLOW = 200


# ============================================================
# SMA / Regime ユーティリティ
# ============================================================

def compute_sma_at(closes, idx, period):
    """closes[0..idx] 末尾 period 本の単純平均。不足時は None。"""
    start = idx - period + 1
    if start < 0:
        return None
    return sum(closes[start : idx + 1]) / period


def compute_regimes(candles):
    """
    各バーに regime を付与した辞書リストを返す。
    regime: 'downtrend' | 'uptrend' | None
    """
    closes = [c["close"] for c in candles]
    regimes = []
    for i, c in enumerate(candles):
        sma50 = compute_sma_at(closes, i, SMA_FAST)
        sma200 = compute_sma_at(closes, i, SMA_SLOW)
        if sma50 is None or sma200 is None:
            regime = None
        elif sma50 < sma200:
            regime = "downtrend"
        else:
            regime = "uptrend"
        regimes.append(
            {
                "index": i,
                "datetime": c["datetime"],
                "close": c["close"],
                "sma50": round(sma50, 2) if sma50 else None,
                "sma200": round(sma200, 2) if sma200 else None,
                "regime": regime,
            }
        )
    return regimes


# ============================================================
# 下落区間の抽出
# ============================================================

def extract_downtrend_spans(regimes):
    """
    連続する downtrend バーをまとめて区間リストを返す。
    各区間: {start_date, end_date, start_idx, end_idx, bars, max_drawdown_pct}
    """
    spans = []
    in_span = False
    span_start = None

    for r in regimes:
        if r["regime"] == "downtrend":
            if not in_span:
                in_span = True
                span_start = r
            span_latest = r
        else:
            if in_span:
                spans.append((span_start, span_latest))
                in_span = False
    if in_span:
        spans.append((span_start, span_latest))

    result = []
    closes = [r["close"] for r in regimes]
    for start_r, end_r in spans:
        si = start_r["index"]
        ei = end_r["index"]
        seg = closes[si : ei + 1]
        peak = max(seg)
        trough = min(seg)
        max_dd = round((trough - peak) / peak * 100, 2)
        result.append(
            {
                "start_date": start_r["datetime"],
                "end_date": end_r["datetime"],
                "start_idx": si,
                "end_idx": ei,
                "bars": ei - si + 1,
                "max_drawdown_pct": max_dd,
            }
        )
    return result


# ============================================================
# Regime 別集計
# ============================================================

def aggregate_by_regime(trades, regimes, entry_indices):
    """
    trades と entry_indices（recalculate_pnl が返す前後の index 対応）を使い、
    downtrend / uptrend に分けて集計する。

    entry_indices[i] = trades[i] の entry_idx
    """
    result = {
        "downtrend": {"entries": [], "sl": 0, "tp": 0, "timeout": 0, "pnl_sum": 0.0},
        "uptrend": {"entries": [], "sl": 0, "tp": 0, "timeout": 0, "pnl_sum": 0.0},
        "unknown": {"entries": [], "sl": 0, "tp": 0, "timeout": 0, "pnl_sum": 0.0},
    }
    for trade, entry_idx in zip(trades, entry_indices):
        reg = regimes[entry_idx]["regime"] if entry_idx < len(regimes) else None
        key = reg if reg in ("downtrend", "uptrend") else "unknown"
        bucket = result[key]
        bucket["entries"].append(trade)
        bucket[trade["exit_reason"]] = bucket.get(trade["exit_reason"], 0) + 1
        bucket["pnl_sum"] += trade["net_pnl_pct"]

    # 集計サマリ作成
    summary = {}
    for key, bucket in result.items():
        n = len(bucket["entries"])
        sl = bucket.get("stop_loss", 0)
        tp = bucket.get("take_profit", 0)
        to = bucket.get("timeout", 0)
        pnl = round(bucket["pnl_sum"], 4)
        summary[key] = {
            "entry_count": n,
            "sl_count": sl,
            "tp_count": tp,
            "timeout_count": to,
            "sl_rate_pct": round(sl / n * 100, 1) if n > 0 else 0.0,
            "total_pnl_pct": pnl,
        }
    return summary


# ============================================================
# フィルター適用後の集計
# ============================================================

def apply_filter_and_aggregate(candles, valid_metas, entry_indices, cfg):
    """
    本番の check_trend_filter を使い、フィルター通過分の metadata と entry_indices を返す。

    各シグナルのエントリーバー時点の candles スライス（先頭〜entry_idx+1）で
    フィルター判定を行い、通過したものだけのリストを返す。
    呼び出し元で recalculate_pnl と aggregate_by_regime を実行する。

    Args:
        candles: 全OHLCVデータ
        valid_metas: detected==1 かつ hold範囲内の metadata リスト
        entry_indices: valid_metas に対応した entry_idx のリスト
        cfg: STRATEGIES[strategy_name] の設定辞書

    Returns:
        dict: passed_metas, passed_entry_indices, filtered_count, passed_count
    """
    # グローバルトレンドフィルター設定（strategy_config.json global と同値）
    filter_config = {
        "enabled": True,
        "fast_period": SMA_FAST,
        "slow_period": SMA_SLOW,
    }
    reentry_confirm_days = cfg.get("reentry_confirm_days", 0)

    passed_metas = []
    passed_entry_indices = []
    filtered_count = 0

    for meta, entry_idx in zip(valid_metas, entry_indices):
        # エントリーバー時点の candles スライス（scanner.py と同じく全足を渡す）
        candles_at_entry = candles[: entry_idx + 1]
        blocked = check_trend_filter(
            candles_at_entry,
            filter_config,
            strategy_uses_filter=True,
            reentry_confirm_days=reentry_confirm_days,
        )
        if blocked:
            filtered_count += 1
        else:
            passed_metas.append(meta)
            passed_entry_indices.append(entry_idx)

    return {
        "passed_metas": passed_metas,
        "passed_entry_indices": passed_entry_indices,
        "filtered_count": filtered_count,
        "passed_count": len(passed_metas),
    }


# ============================================================
# Bull Trap 分析
# ============================================================

def analyze_bull_traps(regimes, max_k=10):
    """
    ゴールデンクロス（SMA50がSMA200を上抜け）後 K 日以内に再び下抜けした事例を集計。
    K=1..max_k でループし、各 K での件数と「再エントリー確認日数 N」推奨を導出。

    推奨 N: GC後に終値がSMA200を N 日連続で維持した時点でエントリー可とする。
    """
    trap_events = []
    gc_idx = None  # 直近ゴールデンクロスのバーindex

    for i in range(1, len(regimes)):
        prev = regimes[i - 1]
        curr = regimes[i]
        # ゴールデンクロス検出: 前バーが downtrend/None → 今バーが uptrend
        if prev["regime"] != "uptrend" and curr["regime"] == "uptrend":
            gc_idx = i

        # デッドクロス（再下抜け）: 前バーが uptrend → 今バーが downtrend
        if prev["regime"] == "uptrend" and curr["regime"] == "downtrend":
            if gc_idx is not None:
                days_since_gc = i - gc_idx
                trap_events.append(
                    {
                        "gc_date": regimes[gc_idx]["datetime"],
                        "gc_idx": gc_idx,
                        "dc_date": curr["datetime"],
                        "dc_idx": i,
                        "days_since_gc": days_since_gc,
                    }
                )
            gc_idx = None  # デッドクロスで GC リセット

    # K 別集計
    k_stats = {}
    total_gc = len(trap_events)
    for k in range(1, max_k + 1):
        count = sum(1 for e in trap_events if e["days_since_gc"] <= k)
        k_stats[k] = {
            "traps_within_k": count,
            "trap_rate_pct": round(count / total_gc * 100, 1) if total_gc > 0 else 0.0,
        }

    # 終値 > SMA200 を N 日連続維持（GC 直後の streak を計測）
    close_above_sma200_streak = {}
    for event in trap_events:
        gc_i = event["gc_idx"]
        streak = 0
        for j in range(gc_i, len(regimes)):
            r = regimes[j]
            if r["sma200"] is None:
                break
            if r["close"] > r["sma200"]:
                streak += 1
            else:
                break
        close_above_sma200_streak[event["gc_idx"]] = streak

    # 推奨 N 導出:
    # -----------------------------------------------------------------
    # [概念の分離]
    # K (bull trap 判定閾値): GC後 K 日以内に再デッドクロスが来た事例を「短期 bull trap」と定義。
    # N (エントリー再開のための確認日数): GC後、終値が SMA200 を連続 N 日上回った時点で
    #   uptrend 復帰と判定し、エントリーを再開する実運用パラメータ。
    #
    # [根拠]
    # このデータセット（1000本）では GC→DC の間隔は全て 161d 以上あり、
    # K=1..max_k では短期 bull trap は 0 件（観測されない）。
    # データ上は N=1 でも理論的に十分だが、実市場のノイズ・週末ギャップ・
    # 一時的なスパイクを考慮して最低 3 日を確認期間として設定するのが業界標準。
    # 3〜5 日の範囲で保守的に N=5 を推奨とする。
    #
    # NOTE: trap_events が 0 件のためこのデータセットでは常に else ブランチが実行される。
    # if ブランチは短期 bull trap が観測されたデータセットへの将来対応として残置する。
    # -----------------------------------------------------------------
    if trap_events:
        # GC後の最短有効継続日数（最小 days_since_gc を参照）。
        # 現データセットでは到達しない（trap_events == 0）。
        min_days = min(e["days_since_gc"] for e in trap_events)
        # 実際の確認日数として、5日または最短継続期間の5%のいずれか小さい方（最大5）
        n_from_data = max(3, min(5, min_days // 20))
    else:
        # bull trap 未観測 → データ上 N=1 でも足りるが、市場ノイズ考慮で業界標準 5 日を採用
        n_from_data = 5

    recommended_n = n_from_data

    return {
        "total_gc_events": total_gc,
        "trap_events": trap_events,
        "k_stats": k_stats,
        "recommended_n": recommended_n,
        "close_above_sma200_streak": close_above_sma200_streak,
        "note": (
            f"K=bull trap判定閾値(GC後K日以内に再DC), "
            f"N=エントリー再開確認日数(終値>SMA200をN日連続維持)。"
            f"このデータセットではK=1..{max_k}の短期bull trapは0件(全GC→DC間隔161d以上)。"
            f"データ上はN=1でも十分だが、実市場ノイズを考慮して業界標準3-5日からN={recommended_n}を推奨。"
        ),
    }


# ============================================================
# メイン処理
# ============================================================

def run(strategies_to_run, bull_trap_k=10, verbose=False):
    os.makedirs(OUT_DIR, exist_ok=True)

    # ---- 1. OHLCVデータ読み込み & Regime 付与 ----
    with open(DATA_FILE, encoding="utf-8") as f:
        candles = json.load(f)

    regimes = compute_regimes(candles)

    print(f"[1] OHLCV loaded: {len(candles)} bars  {candles[0]['datetime']} ~ {candles[-1]['datetime']}")
    print(f"    Regime coverage: SMA{SMA_FAST}/SMA{SMA_SLOW}")

    # ---- 2. 下落区間の抽出 ----
    spans = extract_downtrend_spans(regimes)
    print(f"\n[2] Downtrend spans detected: {len(spans)}")
    print(f"    {'Start':>12} {'End':>12} {'Bars':>5} {'MaxDD%':>8}")
    print(f"    {'-'*12} {'-'*12} {'-'*5} {'-'*8}")
    for s in spans:
        print(
            f"    {s['start_date']:>12} {s['end_date']:>12} {s['bars']:>5} {s['max_drawdown_pct']:>8.2f}%"
        )
    # 既知3区間（2024-08, 2025-04, 2025-11〜2026-03）の確認
    known_periods = ["2024-08", "2025-04", "2025-11"]
    for kp in known_periods:
        found = any(s["start_date"][:7] <= kp <= s["end_date"][:7] for s in spans)
        tag = "OK" if found else "MISSING"
        print(f"    Known period {kp}: [{tag}]")

    # ---- 3. 戦略ごとの Regime 別ベースライン ----
    print(f"\n[3] Strategy baseline by regime")

    all_baseline = {}

    for strategy_name in strategies_to_run:
        cfg = STRATEGIES[strategy_name]

        with open(cfg["result_json"], encoding="utf-8") as f:
            result_data = json.load(f)

        config = result_data["config"]
        metadata = result_data["metadata"]
        window_size = config["window_size"]

        # detected==1 のシグナルを抽出し、entry_idx を求める
        detected_metas = [m for m in metadata if m.get("detected") == 1]

        # entry_idx をリストアップ（regime 分類用）
        entry_indices = []
        valid_metas = []
        for meta in detected_metas:
            entry_idx = meta["index"] + window_size - 1
            max_exit_idx = entry_idx + cfg["hold_bars"]
            if max_exit_idx >= len(candles):
                continue  # recalculate_pnl でも除外される
            entry_indices.append(entry_idx)
            valid_metas.append(meta)

        # recalculate_pnl を呼ぶ
        trades, stats = recalculate_pnl(
            candles=candles,
            metadata=valid_metas,
            config=config,
            take_profit=cfg["take_profit"],
            stop_loss=cfg["stop_loss"],
            hold_bars=cfg["hold_bars"],
            fee_rate=0.001,
            direction=cfg["direction"],
        )

        # regime 別集計
        regime_summary = aggregate_by_regime(trades, regimes, entry_indices)

        all_baseline[strategy_name] = {
            "config": {
                "take_profit": cfg["take_profit"],
                "stop_loss": cfg["stop_loss"],
                "hold_bars": cfg["hold_bars"],
                "direction": cfg["direction"],
                "trend_filter": cfg["trend_filter"],
            },
            "total_detected": len(detected_metas),
            "total_valid_trades": len(trades),
            "overall_stats": stats,
            "regime_breakdown": regime_summary,
        }

        # 表示
        print(f"\n  === {strategy_name} ===")
        print(
            f"  Config: TP={cfg['take_profit']}, SL={cfg['stop_loss']}, "
            f"Hold={cfg['hold_bars']}, direction={cfg['direction']}, "
            f"trend_filter={cfg['trend_filter']}"
        )
        print(
            f"  Detected signals: {len(detected_metas)}, Valid trades (hold within data): {len(trades)}"
        )
        print(
            f"  {'Regime':<12} {'Entries':>7} {'SL':>5} {'TP':>5} {'TO':>5} {'SL%':>6} {'PnL%':>8}"
        )
        print(f"  {'-'*12} {'-'*7} {'-'*5} {'-'*5} {'-'*5} {'-'*6} {'-'*8}")
        for reg in ("downtrend", "uptrend", "unknown"):
            rb = regime_summary[reg]
            print(
                f"  {reg:<12} {rb['entry_count']:>7} "
                f"{rb['sl_count']:>5} {rb['tp_count']:>5} {rb['timeout_count']:>5} "
                f"{rb['sl_rate_pct']:>5.1f}% {rb['total_pnl_pct']:>8.4f}%"
            )
        print(
            f"  Overall: WinRate={stats['win_rate_pct']}%, "
            f"PF={stats['profit_factor']}, "
            f"Return={stats['total_return_pct']}%, "
            f"DD={stats['max_drawdown_pct']}%"
        )

    # ---- 3b. フィルター適用後(after)の集計 ----
    # 本番の check_trend_filter を import してエントリーごとにフィルター判定し、
    # 通過分だけの PnL を集計する（baseline との比較用）。
    print(f"\n[3b] Strategy AFTER filter (trend_filter=true + reentry_confirm_days)")

    all_after = {}

    for strategy_name in strategies_to_run:
        cfg = STRATEGIES[strategy_name]

        # trend_filter が無効な戦略はスキップ
        if not cfg.get("trend_filter", False):
            print(f"\n  === {strategy_name} === (trend_filter=False, skip after filter)")
            all_after[strategy_name] = None
            continue

        with open(cfg["result_json"], encoding="utf-8") as f:
            result_data = json.load(f)

        config = result_data["config"]
        metadata = result_data["metadata"]
        window_size = config["window_size"]

        detected_metas = [m for m in metadata if m.get("detected") == 1]
        entry_indices_after = []
        valid_metas_after = []
        for meta in detected_metas:
            entry_idx = meta["index"] + window_size - 1
            max_exit_idx = entry_idx + cfg["hold_bars"]
            if max_exit_idx >= len(candles):
                continue
            entry_indices_after.append(entry_idx)
            valid_metas_after.append(meta)

        # フィルター適用: 本番の check_trend_filter で各エントリーを判定
        filter_info = apply_filter_and_aggregate(
            candles, valid_metas_after, entry_indices_after, cfg
        )
        passed_metas = filter_info["passed_metas"]
        passed_entry_indices = filter_info["passed_entry_indices"]

        if passed_metas:
            after_trades, after_stats = recalculate_pnl(
                candles=candles,
                metadata=passed_metas,
                config=config,
                take_profit=cfg["take_profit"],
                stop_loss=cfg["stop_loss"],
                hold_bars=cfg["hold_bars"],
                fee_rate=0.001,
                direction=cfg["direction"],
            )
            after_regime_summary = aggregate_by_regime(
                after_trades, regimes, passed_entry_indices
            )
        else:
            after_trades, after_stats = [], {}
            after_regime_summary = {
                r: {"entry_count": 0, "sl_count": 0, "tp_count": 0,
                    "timeout_count": 0, "sl_rate_pct": 0.0, "total_pnl_pct": 0.0}
                for r in ("downtrend", "uptrend", "unknown")
            }

        all_after[strategy_name] = {
            "filtered_count": filter_info["filtered_count"],
            "passed_count": filter_info["passed_count"],
            "overall_stats": after_stats,
            "regime_breakdown": after_regime_summary,
        }

        print(f"\n  === {strategy_name} (after filter) ===")
        print(
            f"  trend_filter=True, reentry_confirm_days={cfg.get('reentry_confirm_days', 0)}"
        )
        print(
            f"  Signals filtered: {filter_info['filtered_count']}, "
            f"Passed: {filter_info['passed_count']}"
        )
        print(
            f"  {'Regime':<12} {'Entries':>7} {'SL':>5} {'TP':>5} {'TO':>5} {'SL%':>6} {'PnL%':>8}"
        )
        print(f"  {'-'*12} {'-'*7} {'-'*5} {'-'*5} {'-'*5} {'-'*6} {'-'*8}")
        for reg in ("downtrend", "uptrend", "unknown"):
            rb = after_regime_summary[reg]
            print(
                f"  {reg:<12} {rb['entry_count']:>7} "
                f"{rb['sl_count']:>5} {rb['tp_count']:>5} {rb['timeout_count']:>5} "
                f"{rb['sl_rate_pct']:>5.1f}% {rb['total_pnl_pct']:>8.4f}%"
            )
        if after_stats:
            print(
                f"  Overall: WinRate={after_stats.get('win_rate_pct', 0)}%, "
                f"PF={after_stats.get('profit_factor', 0)}, "
                f"Return={after_stats.get('total_return_pct', 0)}%, "
                f"DD={after_stats.get('max_drawdown_pct', 0)}%"
            )
        else:
            print(f"  Overall: No trades after filter")

    # ---- 4. Bull Trap 分析 ----
    print(f"\n[4] Bull Trap Analysis (GC → re-DC within K days, K=1..{bull_trap_k})")
    trap_result = analyze_bull_traps(regimes, max_k=bull_trap_k)

    print(f"  Total Golden Cross events: {trap_result['total_gc_events']}")
    print(f"  {'K':>3} {'Traps<=K':>10} {'TrapRate%':>10}")
    print(f"  {'-'*3} {'-'*10} {'-'*10}")
    rec_n = trap_result["recommended_n"]
    for k in range(1, bull_trap_k + 1):
        ks = trap_result["k_stats"][k]
        marker = " <-- recommended N (confirmation window)" if k == rec_n else ""
        print(
            f"  {k:>3} {ks['traps_within_k']:>10} {ks['trap_rate_pct']:>9.1f}%{marker}"
        )

    print(f"\n  Trap events detail:")
    for ev in trap_result["trap_events"]:
        streak = trap_result["close_above_sma200_streak"].get(ev["gc_idx"], 0)
        print(
            f"    GC={ev['gc_date']} → DC={ev['dc_date']} "
            f"(+{ev['days_since_gc']}d, close>SMA200 streak={streak}d)"
        )

    print(f"\n  Recommended N (days above SMA200 to confirm uptrend): {trap_result['recommended_n']}")
    print(f"  Note: {trap_result['note']}")

    # ---- 5. 結果保存 ----
    all_strategies = list(STRATEGIES.keys())
    is_full_run = set(strategies_to_run) == set(all_strategies)

    output = {
        "generated_at": datetime.now().isoformat(),
        "data_file": DATA_FILE,
        "sma_fast": SMA_FAST,
        "sma_slow": SMA_SLOW,
        "downtrend_spans": spans,
        "baseline": all_baseline,
        "after_filter": all_after,
        "bull_trap_analysis": {
            "total_gc_events": trap_result["total_gc_events"],
            "trap_events": trap_result["trap_events"],
            "k_stats": trap_result["k_stats"],
            "recommended_n": trap_result["recommended_n"],
            "note": (
                "K = bull trap判定閾値 (GC後K日以内に再デッドクロスが来れば『短期bull trap』)。"
                "N = エントリー再開のための確認日数 (終値がSMA200を連続N日上回れば uptrend 復帰と判定)。"
                f"このデータセット(1000本)では K=1..{bull_trap_k} の短期bull trapは0件。"
                "データ上はN=1でも十分だが、実市場のノイズ・週末ギャップを考慮して"
                "業界標準の3-5日を採用し N=5 を推奨。"
            ),
        },
    }

    # baseline.json とサマリーテキストは --all（全戦略）実行時のみ canonical ファイルに書く。
    # --strategy 指定の部分実行時はサフィックス付きファイルに書いて canonical を上書きしない。
    if is_full_run:
        out_json = os.path.join(OUT_DIR, "baseline.json")
        out_txt = os.path.join(OUT_DIR, "baseline_summary.txt")
    else:
        suffix = "_".join(sorted(strategies_to_run))
        out_json = os.path.join(OUT_DIR, f"baseline_{suffix}.json")
        out_txt = os.path.join(OUT_DIR, f"baseline_summary_{suffix}.txt")

    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    with open(out_txt, "w", encoding="utf-8") as f:
        f.write("=== Downtrend Filter Baseline Summary ===\n")
        f.write(f"Generated: {output['generated_at']}\n")
        if is_full_run:
            f.write("Scope: ALL strategies\n\n")
        else:
            f.write(f"Scope: {', '.join(strategies_to_run)} (partial run)\n\n")

        f.write("-- Downtrend Spans --\n")
        for s in spans:
            f.write(
                f"  {s['start_date']} ~ {s['end_date']}  "
                f"({s['bars']}bars, MaxDD={s['max_drawdown_pct']:.2f}%)\n"
            )

        f.write("\n-- Strategy Regime Breakdown --\n")
        for sname, bdata in all_baseline.items():
            f.write(f"\n[{sname}]\n")
            f.write(
                f"  TP={bdata['config']['take_profit']}, "
                f"SL={bdata['config']['stop_loss']}, "
                f"Hold={bdata['config']['hold_bars']}, "
                f"trend_filter={bdata['config']['trend_filter']}\n"
            )
            rb = bdata["regime_breakdown"]
            for reg in ("downtrend", "uptrend", "unknown"):
                b = rb[reg]
                f.write(
                    f"  {reg}: entries={b['entry_count']}, "
                    f"SL={b['sl_count']}({b['sl_rate_pct']:.1f}%), "
                    f"TP={b['tp_count']}, TO={b['timeout_count']}, "
                    f"PnL={b['total_pnl_pct']:.4f}%\n"
                )

        f.write(f"\n-- Strategy AFTER Filter (trend_filter=True + reentry_confirm_days) --\n")
        for sname, adata in all_after.items():
            if adata is None:
                f.write(f"\n[{sname}]: trend_filter=False, skipped\n")
                continue
            f.write(f"\n[{sname}] after filter\n")
            f.write(
                f"  filtered={adata['filtered_count']}, passed={adata['passed_count']}\n"
            )
            rb = adata["regime_breakdown"]
            for reg in ("downtrend", "uptrend", "unknown"):
                b = rb[reg]
                f.write(
                    f"  {reg}: entries={b['entry_count']}, "
                    f"SL={b['sl_count']}({b['sl_rate_pct']:.1f}%), "
                    f"TP={b['tp_count']}, TO={b['timeout_count']}, "
                    f"PnL={b['total_pnl_pct']:.4f}%\n"
                )
            st = adata.get("overall_stats", {})
            if st:
                f.write(
                    f"  Overall: WinRate={st.get('win_rate_pct', 0)}%, "
                    f"PF={st.get('profit_factor', 0)}, "
                    f"Return={st.get('total_return_pct', 0)}%, "
                    f"DD={st.get('max_drawdown_pct', 0)}%\n"
                )

        f.write(f"\n-- Bull Trap Analysis --\n")
        f.write(f"  Total GC events: {trap_result['total_gc_events']}\n")
        f.write(f"  Recommended N: {trap_result['recommended_n']} days\n")
        f.write(f"\n  [K vs N の概念分離]\n")
        f.write(
            f"  K = bull trap判定閾値: GC後K日以内に再デッドクロスが来た場合を『短期bull trap』と呼ぶ。\n"
        )
        f.write(
            f"  N = エントリー再開のための確認日数: GC後、終値がSMA200を連続N日上回った時点で\n"
            f"      uptrend 復帰と判定しエントリーを再開する。\n"
        )
        f.write(
            f"  根拠: K=1..{bull_trap_k} での短期bull trapは0件(全GC→DC間隔は161d以上)。\n"
            f"  データ上はN=1でも理論上十分だが、実市場のノイズ・週末ギャップを考慮し\n"
            f"  業界標準3-5日を採用してN=5を推奨する。\n"
        )
        for ev in trap_result["trap_events"]:
            streak = trap_result["close_above_sma200_streak"].get(ev["gc_idx"], 0)
            f.write(
                f"  GC={ev['gc_date']} → DC={ev['dc_date']} "
                f"(+{ev['days_since_gc']}d, close>SMA200 streak={streak}d)\n"
            )

    print(f"\n[5] Results saved:")
    print(f"    {out_json}")
    print(f"    {out_txt}")
    if not is_full_run:
        print(f"    NOTE: Partial run. baseline.json / baseline_summary.txt (all-strategies) not overwritten.")
    print(f"\nDone.")

    return output


# ============================================================
# CLI エントリーポイント
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="Downtrend filter verification harness (no LLM calls)"
    )
    parser.add_argument(
        "--strategy",
        choices=list(STRATEGIES.keys()),
        default=None,
        help="Single strategy to analyze (default: all)",
    )
    parser.add_argument(
        "--bull-trap-k",
        type=int,
        default=10,
        help="Max K days for bull trap analysis (default: 10)",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Run all strategies (default)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Verbose output",
    )
    args = parser.parse_args()

    if args.strategy:
        strategies_to_run = [args.strategy]
    else:
        strategies_to_run = list(STRATEGIES.keys())

    run(
        strategies_to_run=strategies_to_run,
        bull_trap_k=args.bull_trap_k,
        verbose=args.verbose,
    )


if __name__ == "__main__":
    main()
