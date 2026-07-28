"""
トレンドフィルター

移動平均線（SMA）を用いて相場のトレンド方向を判定する。
下落トレンド中にロング系シグナル（ダブルボトム等）をブロックし、
ダマシを防止する。
また、上昇トレンド中にショート系シグナルをブロックする
逆トレンドフィルター機能も提供する。
"""


def compute_sma(candles, period):
    """終値のSMA（単純移動平均）を計算する。"""
    closes = [c["close"] for c in candles]
    if len(closes) < period:
        return None
    return sum(closes[-period:]) / period


def is_downtrend(candles, fast_period=50, slow_period=200):
    """
    下落トレンドかどうかを判定する。

    SMA(fast) < SMA(slow) → 下落トレンド

    Returns:
        True: 下落トレンド
        False: 上昇トレンド
        None: データ不足で判定不可
    """
    sma_fast = compute_sma(candles, fast_period)
    sma_slow = compute_sma(candles, slow_period)
    if sma_fast is None or sma_slow is None:
        return None
    return sma_fast < sma_slow


def is_uptrend(candles, fast_period=50, slow_period=200):
    """
    上昇トレンドかどうかを判定する。

    SMA(fast) > SMA(slow) → 上昇トレンド

    Returns:
        True: 上昇トレンド
        False: 下落トレンド
        None: データ不足で判定不可
    """
    sma_fast = compute_sma(candles, fast_period)
    sma_slow = compute_sma(candles, slow_period)
    if sma_fast is None or sma_slow is None:
        return None
    return sma_fast > sma_slow


def check_short_trend_filter(candles, filter_config, strategy_uses_filter=True):
    """
    ショート戦略用トレンドフィルターを適用する。

    Args:
        candles: OHLCVデータのリスト
        filter_config: グローバルトレンドフィルター設定
        strategy_uses_filter: この戦略がフィルターを使うか

    Returns:
        True: シグナルをブロック（却下）
        False: シグナルを許可
    """
    if not strategy_uses_filter:
        return False

    if not filter_config or not filter_config.get("enabled"):
        return False

    fast = filter_config.get("fast_period", 50)
    slow = filter_config.get("slow_period", 200)

    uptrend = is_uptrend(candles, fast, slow)
    if uptrend is None:
        return False  # データ不足時はフィルターなし

    return uptrend  # 上昇トレンド → ブロック


def check_trend_filter(candles, filter_config, strategy_uses_filter=True,
                       reentry_confirm_days=0):
    """
    トレンドフィルターを適用する。

    Args:
        candles: OHLCVデータのリスト
        filter_config: グローバルトレンドフィルター設定
        strategy_uses_filter: この戦略がフィルターを使うか
        reentry_confirm_days: bull trap ガード（BTC限定・デフォルト0=無効）。
            0 のとき現状と完全に同一挙動（後方互換）。
            N > 0 のとき、直近 N 日間の終値が「全て SMA200 を上回っている」
            ことを確認してからエントリーを許可する。
            これにより、GC直後の偽ブレイクアウト（bull trap）を防ぐ。
            推奨 N=5（工程1分析より: K=1..10での短期bull trapは0件だが、
            実市場のノイズ・週末ギャップを考慮して業界標準3-5日から N=5 を採用）。

    Returns:
        True: シグナルをブロック（却下）
        False: シグナルを許可
    """
    if not strategy_uses_filter:
        return False

    if not filter_config or not filter_config.get("enabled"):
        return False

    fast = filter_config.get("fast_period", 50)
    slow = filter_config.get("slow_period", 200)

    downtrend = is_downtrend(candles, fast, slow)
    if downtrend is None:
        return False  # データ不足時はフィルターなし

    if downtrend:
        return True  # 下落トレンド中 → ブロック

    # --- bull trap ガード（reentry_confirm_days > 0 のときのみ適用） ---
    # 上昇トレンド（SMA50 >= SMA200）でも、直近 N 日間が全て SMA200 を上回って
    # いない場合はまだブロックする。GC直後の一時的な上抜けに乗るのを防ぐ。
    if reentry_confirm_days > 0:
        sma_slow = compute_sma(candles, slow)
        if sma_slow is None:
            return False  # データ不足時は許可
        # 直近 reentry_confirm_days 本の終値を取得
        closes = [c["close"] for c in candles]
        recent_closes = closes[-reentry_confirm_days:]
        # N 本に満たない場合（データ不足）は許可
        if len(recent_closes) < reentry_confirm_days:
            return False
        # 直近 N 日間が全て SMA200 を上回っていない → まだブロック
        if not all(cl > sma_slow for cl in recent_closes):
            return True

    return False  # 上昇トレンド確認済み → 許可
