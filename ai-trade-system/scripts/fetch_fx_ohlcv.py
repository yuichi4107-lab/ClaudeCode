"""
工程2: 時間足データ取得拡張スクリプト

Saxo OpenAPI 経由で FX 通貨ペアの OHLCV データをページネーション取得し、
CSV/JSON 形式で保存する。

使用方法:
    python scripts/fetch_fx_ohlcv.py
    python scripts/fetch_fx_ohlcv.py --symbol "USD/JPY" --timeframe 1h --days 730
    python scripts/fetch_fx_ohlcv.py --symbol "EUR/JPY" --timeframe 4h --days 730 --exchange saxo_sim

引数:
    --symbol       通貨ペア（例: USD/JPY, EUR/JPY）  デフォルト: USD/JPY
    --timeframe    時間足（1h, 4h, 1d）              デフォルト: 1d
    --days         取得日数（過去N日分）               デフォルト: 730 (2年)
    --exchange     saxo_sim or saxo                 デフォルト: saxo_sim
    --resume       途中再開モード（取得済み範囲をスキップ）

出力先:
    data/fx/ohlcv/{SYMBOL}_{TF}.csv
    data/fx/ohlcv/{SYMBOL}_{TF}.json

ページネーション:
    Saxo Chart API の Count 上限は 1200 本。
    Mode=UpTo + Time={ISO8601} を使い、過去方向に遡って全期間を取得する。
"""

import argparse
import csv
import json
import logging
import os
import sys
import time as time_module
import base64
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional

# パス設定
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "src"))

from trading.saxo_client import SaxoAuthError, SaxoAPIError, SaxoClient

# ロギング設定
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

OUTPUT_DIR = os.path.join(PROJECT_ROOT, "data", "fx", "ohlcv")

# 時間足ごとの最大リクエスト本数（Saxo API 上限 1200）
MAX_PER_REQUEST = 1200

# ページング間のスリープ秒数（レート制限回避）
PAGE_SLEEP_SECONDS = 1.5


def check_token_expiry(token: str, min_hours: float = 1.0) -> float:
    """
    Token の残り有効時間を確認する。

    Args:
        token: JWT トークン文字列
        min_hours: 最低必要時間（時間）

    Returns:
        float: 残り有効時間（秒）。負の場合は失効済み。

    Raises:
        SystemExit: Token が失効済みまたは残り時間が min_hours 未満の場合
    """
    try:
        payload_b64 = token.split(".")[1]
        padded = payload_b64 + "=" * (4 - len(payload_b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded))
        exp = int(payload.get("exp", 0))
        remaining = exp - int(time_module.time())

        if remaining <= 0:
            print("\n[ERROR] Saxo Token が失効しています。")
            print("  Developer Portal で新しい PAT を取得し、.env の SAXO_SIM_TOKEN を更新してください。")
            print("  URL: https://www.developer.saxo/openapi/token")
            sys.exit(1)

        hours_remaining = remaining / 3600
        print(f"\nToken 残り有効時間: {hours_remaining:.1f} 時間")

        if hours_remaining < min_hours:
            print(f"\n[WARNING] Token 残り有効時間が {min_hours} 時間未満です（{hours_remaining:.1f}時間）。")
            print("  長時間の取得処理中に Token が失効する可能性があります。")
            print("  Developer Portal で新しい PAT を取得し、処理後に .env を更新することを推奨します。")
            print("  URL: https://www.developer.saxo/openapi/token")

        return float(remaining)

    except (IndexError, ValueError, KeyError) as e:
        logger.warning(f"Token 有効期限確認スキップ: {e}")
        return float("inf")


def fetch_ohlcv_paginated(
    client: SaxoClient,
    symbol: str,
    timeframe: str,
    days: int,
    resume_from_timestamp: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """
    Saxo API からページネーションで OHLCV データを取得する。

    Saxo Chart API の Count 上限（1200本）を考慮し、
    Mode=UpTo + Time パラメータで過去方向に遡って全期間を取得する。

    Args:
        client: SaxoClient インスタンス
        symbol: 通貨ペア（例: "USD/JPY"）
        timeframe: タイムフレーム（例: "1h", "4h", "1d"）
        days: 取得日数（過去N日分）
        resume_from_timestamp: 再開用タイムスタンプ（ms）。これより新しいデータはスキップ

    Returns:
        list: OHLCV データのリスト（重複排除済み、時系列昇順）
    """
    uic = client._get_uic(symbol)
    horizon = client.TIMEFRAME_MAP.get(timeframe, 1440)

    # 取得期間の計算
    end_dt = datetime.now(timezone.utc)
    start_dt = end_dt - timedelta(days=days)
    start_ts = int(start_dt.timestamp() * 1000)

    logger.info(f"取得期間: {start_dt.strftime('%Y-%m-%d')} 〜 {end_dt.strftime('%Y-%m-%d')}")
    logger.info(f"通貨ペア: {symbol}, 時間足: {timeframe}, 期間: {days}日")

    all_candles: List[Dict[str, Any]] = []
    seen_timestamps: set = set()

    # ページング: end_dt から過去に向かって遡る
    current_end_dt = end_dt
    page_num = 0

    while True:
        page_num += 1
        time_param = current_end_dt.strftime("%Y-%m-%dT%H:%M:%S.000000Z")

        logger.info(
            f"[ページ {page_num}] 取得中: {symbol} {timeframe} UpTo={time_param}"
        )

        params = {
            "AssetType": "FxSpot",
            "Uic": uic,
            "Horizon": horizon,
            "Count": MAX_PER_REQUEST,
            "Mode": "UpTo",
            "Time": time_param,
        }

        try:
            data = client._request("GET", "/chart/v3/charts", params=params)
        except SaxoAuthError:
            logger.error("Token 認証エラー。取得を中断します。")
            raise
        except SaxoAPIError as e:
            logger.error(f"API エラー: {e}。取得を中断します。")
            raise

        page_candles = []
        for c in data.get("Data", []):
            # Mid = (Bid + Ask) / 2
            open_mid = (c.get("OpenBid", 0) + c.get("OpenAsk", 0)) / 2
            high_mid = (c.get("HighBid", 0) + c.get("HighAsk", 0)) / 2
            low_mid = (c.get("LowBid", 0) + c.get("LowAsk", 0)) / 2
            close_mid = (c.get("CloseBid", 0) + c.get("CloseAsk", 0)) / 2

            time_str = c.get("Time", "")
            try:
                dt = datetime.fromisoformat(time_str.replace("Z", "+00:00"))
                ts = int(dt.timestamp() * 1000)
                dt_str = dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            except (ValueError, AttributeError):
                ts = 0
                dt_str = time_str

            page_candles.append({
                "timestamp": ts,
                "datetime": dt_str,
                "open": round(open_mid, 5),
                "high": round(high_mid, 5),
                "low": round(low_mid, 5),
                "close": round(close_mid, 5),
                "volume": 0,
            })

        if not page_candles:
            logger.info(f"[ページ {page_num}] データなし。取得完了。")
            break

        # 時系列昇順にソート
        page_candles.sort(key=lambda c: c["timestamp"])

        oldest_ts = page_candles[0]["timestamp"]
        newest_ts = page_candles[-1]["timestamp"]
        oldest_dt = datetime.fromtimestamp(oldest_ts / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
        newest_dt = datetime.fromtimestamp(newest_ts / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")

        logger.info(
            f"[ページ {page_num}] 取得: {len(page_candles)}本 "
            f"({oldest_dt} 〜 {newest_dt})"
        )

        # 重複排除しながら追加
        new_count = 0
        for candle in page_candles:
            if candle["timestamp"] not in seen_timestamps:
                seen_timestamps.add(candle["timestamp"])
                all_candles.append(candle)
                new_count += 1

        logger.info(f"[ページ {page_num}] 新規追加: {new_count}本 (累計: {len(all_candles)}本)")

        # 取得期間の始端に到達したか確認
        if oldest_ts <= start_ts:
            logger.info(f"開始日時に到達。取得完了。")
            break

        # 次のページ: 今ページの最古の時刻を新しい終端とする（1本前に遡る）
        # ちょうど同じ時刻だと同じデータを取得するため、1ミリ秒引く
        next_end_ts = oldest_ts - 1
        current_end_dt = datetime.fromtimestamp(next_end_ts / 1000, tz=timezone.utc)

        # レート制限配慮のスリープ
        logger.debug(f"次ページまで {PAGE_SLEEP_SECONDS}秒 待機...")
        time_module.sleep(PAGE_SLEEP_SECONDS)

    # 取得期間外のデータを除去
    all_candles = [c for c in all_candles if c["timestamp"] >= start_ts]

    # 時系列昇順にソート
    all_candles.sort(key=lambda c: c["timestamp"])

    logger.info(f"取得完了: {len(all_candles)}本（ページ数: {page_num}）")
    return all_candles


def validate_candles(candles: List[Dict[str, Any]], symbol: str, timeframe: str) -> Dict[str, Any]:
    """
    取得データの品質検証。

    Args:
        candles: OHLCV データリスト
        symbol: 通貨ペア
        timeframe: 時間足

    Returns:
        dict: 検証結果
    """
    if not candles:
        return {
            "valid": False,
            "reason": "データなし",
            "count": 0,
            "symbol": symbol,
            "timeframe": timeframe,
        }

    count = len(candles)
    first_dt = candles[0]["datetime"]
    last_dt = candles[-1]["datetime"]
    first_ts = candles[0]["timestamp"]
    last_ts = candles[-1]["timestamp"]

    # タイムスタンプの単調増加チェック
    out_of_order = 0
    for i in range(1, len(candles)):
        if candles[i]["timestamp"] <= candles[i-1]["timestamp"]:
            out_of_order += 1

    # 重複タイムスタンプチェック
    timestamps = [c["timestamp"] for c in candles]
    duplicates = len(timestamps) - len(set(timestamps))

    # 異常価格チェック（ゼロ・負の値）
    invalid_prices = [
        c for c in candles
        if c["open"] <= 0 or c["high"] <= 0 or c["low"] <= 0 or c["close"] <= 0
    ]

    # OHLC 整合性チェック（High >= Open/Close/Low, Low <= Open/Close/High）
    invalid_hl = [c for c in candles if c["high"] < c["low"]]
    invalid_high = [
        c for c in candles
        if c["high"] < c["open"] or c["high"] < c["close"]
    ]
    invalid_low = [
        c for c in candles
        if c["low"] > c["open"] or c["low"] > c["close"]
    ]

    # ギャップ検出（時間足ごとの期待間隔の4倍以上）
    tf_seconds = {
        "1h": 3600,
        "4h": 14400,
        "1d": 86400,
    }
    expected_interval_ms = tf_seconds.get(timeframe, 86400) * 1000
    gap_threshold_ms = expected_interval_ms * 4  # 期待間隔の4倍

    gaps = []
    for i in range(1, len(candles)):
        ts_diff = candles[i]["timestamp"] - candles[i-1]["timestamp"]
        if ts_diff > gap_threshold_ms:
            # 週末・祝日を考慮（1d足の場合は3日以上、1h/4h足は週末2日分）
            from_dt = datetime.fromtimestamp(candles[i-1]["timestamp"] / 1000, tz=timezone.utc)
            to_dt = datetime.fromtimestamp(candles[i]["timestamp"] / 1000, tz=timezone.utc)
            # 週末跨ぎは許容（金曜夜→月曜朝）
            is_weekend_gap = (
                from_dt.weekday() == 4 and  # 金曜
                (to_dt - from_dt).total_seconds() < 86400 * 3.5  # 3.5日以内
            )
            if not is_weekend_gap:
                gaps.append({
                    "from": candles[i-1]["datetime"],
                    "to": candles[i]["datetime"],
                    "gap_hours": round(ts_diff / (1000 * 3600), 1),
                })

    # 欠損率計算（取引日ベース）
    total_span_days = (last_ts - first_ts) / (1000 * 86400)
    if timeframe == "1d":
        # 週5日 × 期間
        expected_count = total_span_days * 5 / 7
    elif timeframe == "4h":
        expected_count = total_span_days * 5 / 7 * 6  # 1日6本（24h/4h）
    elif timeframe == "1h":
        expected_count = total_span_days * 5 / 7 * 24  # 1日24本
    else:
        expected_count = count

    missing_rate = max(0, (expected_count - count) / expected_count * 100) if expected_count > 0 else 0

    result = {
        "valid": (
            len(invalid_prices) == 0
            and len(invalid_hl) == 0
            and duplicates == 0
            and out_of_order == 0
            and missing_rate <= 10  # 10%以内（週末・祝日等の許容）
        ),
        "symbol": symbol,
        "timeframe": timeframe,
        "count": count,
        "first_datetime": first_dt,
        "last_datetime": last_dt,
        "expected_count_approx": round(expected_count),
        "missing_rate_pct": round(missing_rate, 2),
        "duplicates": duplicates,
        "out_of_order": out_of_order,
        "invalid_prices": len(invalid_prices),
        "invalid_hl": len(invalid_hl),
        "invalid_high_consistency": len(invalid_high),
        "invalid_low_consistency": len(invalid_low),
        "significant_gaps": len(gaps),
        "gap_details": gaps[:10],  # 先頭10件のみ
    }

    # ログ出力
    logger.info(
        f"検証結果 [{symbol} {timeframe}]: "
        f"{count}本, {first_dt} 〜 {last_dt}, "
        f"欠損率={missing_rate:.1f}%, "
        f"重複={duplicates}, "
        f"異常価格={len(invalid_prices)}, "
        f"HL異常={len(invalid_hl)}, "
        f"ギャップ={len(gaps)}"
    )

    if duplicates > 0:
        logger.warning(f"重複タイムスタンプ: {duplicates}件")
    if len(invalid_prices) > 0:
        logger.warning(f"異常価格（ゼロ・負）: {len(invalid_prices)}件")
    if len(invalid_hl) > 0:
        logger.warning(f"High < Low 異常: {len(invalid_hl)}件")

    return result


def load_existing_data(filepath: str) -> List[Dict[str, Any]]:
    """
    既存の CSV ファイルからデータを読み込む（再開機能用）。

    Args:
        filepath: CSV ファイルパス

    Returns:
        list: 既存の OHLCV データ
    """
    if not os.path.exists(filepath):
        return []

    candles = []
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                candles.append({
                    "timestamp": int(row["timestamp"]),
                    "datetime": row["datetime"],
                    "open": float(row["open"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "close": float(row["close"]),
                    "volume": int(row.get("volume", 0)),
                })
        logger.info(f"既存データ読み込み: {len(candles)}本 ({filepath})")
    except Exception as e:
        logger.warning(f"既存データ読み込み失敗: {e}")
        return []

    return candles


def merge_candles(
    existing: List[Dict[str, Any]],
    new_candles: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    既存データと新規データをマージする（重複除去・時系列昇順）。

    Args:
        existing: 既存のローソク足リスト
        new_candles: 新規取得のローソク足リスト

    Returns:
        list: マージ後のローソク足リスト（重複なし・時系列昇順）
    """
    seen = set()
    merged = []

    for c in existing + new_candles:
        if c["timestamp"] not in seen:
            seen.add(c["timestamp"])
            merged.append(c)

    merged.sort(key=lambda c: c["timestamp"])
    return merged


def save_csv(candles: List[Dict[str, Any]], filepath: str) -> None:
    """
    OHLCV データを CSV に保存する。

    Args:
        candles: OHLCV データリスト
        filepath: 出力先ファイルパス
    """
    fieldnames = ["timestamp", "datetime", "open", "high", "low", "close", "volume"]
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for c in candles:
            writer.writerow({k: c.get(k, 0) for k in fieldnames})
    logger.info(f"CSV 保存: {filepath} ({len(candles)}行)")


def save_json(candles: List[Dict[str, Any]], filepath: str) -> None:
    """
    OHLCV データを JSON に保存する（既存バックテストエンジン互換フォーマット）。

    Args:
        candles: OHLCV データリスト
        filepath: 出力先ファイルパス
    """
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(candles, f, indent=2, ensure_ascii=False)
    logger.info(f"JSON 保存: {filepath} ({len(candles)}件)")


def main():
    parser = argparse.ArgumentParser(
        description="Saxo API から FX OHLCV データをページネーション取得して保存"
    )
    parser.add_argument("--symbol", default="USD/JPY", help="通貨ペア（例: USD/JPY, EUR/JPY）")
    parser.add_argument(
        "--timeframe", default="1d",
        help="時間足（1h, 4h, 1d）",
        choices=["1h", "4h", "1d", "1m", "5m", "15m", "30m", "1w"],
    )
    parser.add_argument("--days", type=int, default=730, help="取得日数（過去N日分）。デフォルト: 730（2年）")
    parser.add_argument("--exchange", default="saxo_sim", help="saxo_sim or saxo")
    parser.add_argument(
        "--resume", action="store_true",
        help="再開モード: 既存ファイルの範囲をスキップして不足分のみ取得"
    )
    args = parser.parse_args()

    print("=" * 60)
    print("  Saxo FX OHLCV データ取得（ページネーション対応）")
    print(f"  Symbol   : {args.symbol}")
    print(f"  Timeframe: {args.timeframe}")
    print(f"  Days     : {args.days}日分（約{args.days * 5 // 7}営業日）")
    print(f"  Exchange : {args.exchange}")
    print(f"  Resume   : {'有効' if args.resume else '無効'}")
    print("=" * 60)

    # Token 有効期限チェック
    import os as _os
    from dotenv import load_dotenv
    load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

    token = _os.getenv("SAXO_SIM_TOKEN", "") if args.exchange == "saxo_sim" else _os.getenv("SAXO_TOKEN", "")
    if token:
        check_token_expiry(token, min_hours=1.0)
    else:
        print(f"\n[ERROR] Token が未設定です。.env の SAXO_SIM_TOKEN を確認してください。")
        sys.exit(1)

    # 出力ファイルパス
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    saxo_sym = args.symbol.replace("/", "").replace("-", "").upper()
    base_name = f"{saxo_sym}_{args.timeframe}"
    csv_path = os.path.join(OUTPUT_DIR, f"{base_name}.csv")
    json_path = os.path.join(OUTPUT_DIR, f"{base_name}.json")

    # 再開モード: 既存データを読み込む
    existing_candles = []
    resume_from_timestamp = None
    if args.resume:
        existing_candles = load_existing_data(csv_path)
        if existing_candles:
            # 既存データの最古のタイムスタンプより前のデータのみ取得
            resume_from_timestamp = existing_candles[0]["timestamp"]
            existing_newest = existing_candles[-1]["datetime"]
            existing_oldest = existing_candles[0]["datetime"]
            logger.info(
                f"再開モード: 既存{len(existing_candles)}本 "
                f"({existing_oldest} 〜 {existing_newest})"
            )

    # クライアント初期化
    try:
        client = SaxoClient(args.exchange)
    except ValueError as e:
        print(f"\n[ERROR] SaxoClient 初期化失敗: {e}")
        sys.exit(1)

    # データ取得
    start_time = time_module.time()
    try:
        new_candles = fetch_ohlcv_paginated(
            client,
            args.symbol,
            args.timeframe,
            args.days,
            resume_from_timestamp=resume_from_timestamp,
        )
    except SaxoAuthError as e:
        print(f"\n[ERROR] Token 認証エラー: {e}")
        print("  Developer Portal で新しい PAT を取得し、.env の SAXO_SIM_TOKEN を更新してください。")
        print("  URL: https://www.developer.saxo/openapi/token")
        sys.exit(1)
    except SaxoAPIError as e:
        print(f"\n[ERROR] API エラー: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n[ERROR] データ取得失敗: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    elapsed = time_module.time() - start_time

    if not new_candles and not existing_candles:
        print("\n[ERROR] 取得データが空です。")
        sys.exit(1)

    # 既存データとマージ
    if args.resume and existing_candles:
        final_candles = merge_candles(existing_candles, new_candles)
        logger.info(f"マージ後: {len(final_candles)}本（既存: {len(existing_candles)}, 新規: {len(new_candles)}）")
    else:
        final_candles = new_candles

    # データ検証
    validation = validate_candles(final_candles, args.symbol, args.timeframe)

    # 保存
    save_csv(final_candles, csv_path)
    save_json(final_candles, json_path)

    # サマリー出力
    print("\n" + "=" * 60)
    print("  データ取得完了")
    print(f"  CSV  : {csv_path}")
    print(f"  JSON : {json_path}")
    print(f"  本数 : {validation['count']}本")
    print(f"  期間 : {validation['first_datetime']} 〜 {validation['last_datetime']}")
    print(f"  欠損率: {validation['missing_rate_pct']:.1f}%")
    print(f"  重複 : {validation['duplicates']}件")
    print(f"  異常価格: {validation['invalid_prices']}件")
    print(f"  HL異常: {validation['invalid_hl']}件")
    print(f"  ギャップ: {validation['significant_gaps']}件")
    print(f"  実行時間: {elapsed:.1f}秒")
    print("=" * 60)

    return final_candles, validation


if __name__ == "__main__":
    main()
