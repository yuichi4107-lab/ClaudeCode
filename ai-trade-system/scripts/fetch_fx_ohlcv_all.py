"""
工程2: FX OHLCV データ全組み合わせ一括取得スクリプト

USD/JPY と EUR/JPY の 1h / 4h / 1d の全6組み合わせを順次取得し、
data/fx/ohlcv/ に保存する。

取得対象:
    USD/JPY: 1h, 4h, 1d
    EUR/JPY: 1h, 4h, 1d

合計: 6データセット

使用方法:
    python scripts/fetch_fx_ohlcv_all.py
    python scripts/fetch_fx_ohlcv_all.py --days 730 --exchange saxo_sim
    python scripts/fetch_fx_ohlcv_all.py --resume  # 途中再開
    python scripts/fetch_fx_ohlcv_all.py --dry-run  # 実行計画の確認のみ

引数:
    --days      取得日数（デフォルト: 730日 = 2年）
    --exchange  saxo_sim or saxo（デフォルト: saxo_sim）
    --resume    再開モード（既存ファイルの範囲をスキップ）
    --dry-run   実行計画を表示して終了（実際の取得は行わない）
    --symbols   対象通貨ペア（デフォルト: USD/JPY,EUR/JPY）
    --timeframes 対象時間足（デフォルト: 1h,4h,1d）
"""

import argparse
import json
import logging
import os
import sys
import time as time_module
import base64
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

# パス設定
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "src"))

# fetch_fx_ohlcv の関数を再利用
sys.path.insert(0, SCRIPT_DIR)
from fetch_fx_ohlcv import (
    check_token_expiry,
    fetch_ohlcv_paginated,
    validate_candles,
    load_existing_data,
    merge_candles,
    save_csv,
    save_json,
    OUTPUT_DIR,
)
from trading.saxo_client import SaxoAuthError, SaxoAPIError, SaxoClient

# ロギング設定
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

# デフォルト取得対象
DEFAULT_SYMBOLS = ["USD/JPY", "EUR/JPY"]
DEFAULT_TIMEFRAMES = ["1h", "4h", "1d"]

# 時間足ごとの期待本数（目安）
EXPECTED_COUNTS = {
    "1h": 17500,
    "4h": 4400,
    "1d": 520,
}


def print_execution_plan(
    symbols: List[str],
    timeframes: List[str],
    days: int,
    exchange: str,
    resume: bool,
) -> None:
    """実行計画を表示する。"""
    print("\n" + "=" * 70)
    print("  FX OHLCV データ取得計画")
    print("=" * 70)
    print(f"  取得期間  : 過去{days}日分（約{days * 5 // 7}営業日）")
    print(f"  Exchange  : {exchange}")
    print(f"  再開モード: {'有効' if resume else '無効'}")
    print()
    print(f"  {'No.':<4} {'Symbol':<12} {'TF':<6} {'期待本数':<10} {'ファイル名'}")
    print(f"  {'-'*60}")

    for i, (sym, tf) in enumerate(
        [(s, t) for s in symbols for t in timeframes], 1
    ):
        saxo_sym = sym.replace("/", "").replace("-", "").upper()
        filename = f"{saxo_sym}_{tf}.csv"
        expected = EXPECTED_COUNTS.get(tf, "?")
        print(f"  {i:<4} {sym:<12} {tf:<6} {expected:<10} {filename}")

    print()
    total = len(symbols) * len(timeframes)
    est_minutes = total * 1.5  # 各データセット約1.5分（ページネーション込み）
    print(f"  合計: {total}データセット（推定{est_minutes:.0f}分）")
    print("=" * 70)


def run_all(
    symbols: List[str],
    timeframes: List[str],
    days: int,
    exchange: str,
    resume: bool,
    client: SaxoClient,
) -> List[Dict[str, Any]]:
    """
    全組み合わせのデータ取得を順次実行する。

    Args:
        symbols: 取得対象の通貨ペアリスト
        timeframes: 取得対象の時間足リスト
        days: 取得日数
        exchange: 取引所ID
        resume: 再開モード
        client: SaxoClient インスタンス

    Returns:
        list: 各データセットの結果サマリー
    """
    results = []
    total = len(symbols) * len(timeframes)
    current = 0

    for symbol in symbols:
        for timeframe in timeframes:
            current += 1
            saxo_sym = symbol.replace("/", "").replace("-", "").upper()
            base_name = f"{saxo_sym}_{timeframe}"
            csv_path = os.path.join(OUTPUT_DIR, f"{base_name}.csv")
            json_path = os.path.join(OUTPUT_DIR, f"{base_name}.json")

            print()
            print(f"{'=' * 70}")
            print(f"  [{current}/{total}] {symbol} {timeframe}")
            print(f"{'=' * 70}")

            start_time = time_module.time()

            # 再開モード: 既存データを読み込む
            existing_candles = []
            if resume:
                existing_candles = load_existing_data(csv_path)
                if existing_candles:
                    logger.info(
                        f"再開モード: 既存{len(existing_candles)}本 "
                        f"({existing_candles[0]['datetime']} 〜 {existing_candles[-1]['datetime']})"
                    )

            # データ取得
            try:
                new_candles = fetch_ohlcv_paginated(
                    client,
                    symbol,
                    timeframe,
                    days,
                    resume_from_timestamp=(
                        existing_candles[0]["timestamp"] if existing_candles else None
                    ),
                )
            except SaxoAuthError as e:
                print(f"\n[ERROR] Token 認証エラー: {e}")
                print("  Developer Portal で PAT を再取得し、.env を更新してください。")
                print("  URL: https://www.developer.saxo/openapi/token")
                # 既存結果を保存して中断
                results.append({
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "status": "failed_auth",
                    "error": str(e),
                })
                break  # Token エラーは全体を中断
            except SaxoAPIError as e:
                print(f"\n[ERROR] API エラー [{symbol} {timeframe}]: {e}")
                results.append({
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "status": "failed_api",
                    "error": str(e),
                })
                continue  # 次の組み合わせへ
            except Exception as e:
                print(f"\n[ERROR] 取得失敗 [{symbol} {timeframe}]: {e}")
                import traceback
                traceback.print_exc()
                results.append({
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "status": "failed_unknown",
                    "error": str(e),
                })
                continue

            # マージ
            if resume and existing_candles:
                final_candles = merge_candles(existing_candles, new_candles)
                logger.info(
                    f"マージ後: {len(final_candles)}本"
                    f"（既存: {len(existing_candles)}, 新規: {len(new_candles)}）"
                )
            else:
                final_candles = new_candles

            if not final_candles:
                print(f"\n[WARNING] データが空です: {symbol} {timeframe}")
                results.append({
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "status": "empty",
                    "count": 0,
                })
                continue

            # 検証
            validation = validate_candles(final_candles, symbol, timeframe)

            # 保存
            os.makedirs(OUTPUT_DIR, exist_ok=True)
            save_csv(final_candles, csv_path)
            save_json(final_candles, json_path)

            elapsed = time_module.time() - start_time

            result = {
                "symbol": symbol,
                "timeframe": timeframe,
                "status": "success" if validation["valid"] else "warning",
                "count": validation["count"],
                "first_datetime": validation["first_datetime"],
                "last_datetime": validation["last_datetime"],
                "missing_rate_pct": validation["missing_rate_pct"],
                "duplicates": validation["duplicates"],
                "invalid_prices": validation["invalid_prices"],
                "invalid_hl": validation["invalid_hl"],
                "significant_gaps": validation["significant_gaps"],
                "gap_details": validation.get("gap_details", []),
                "elapsed_seconds": round(elapsed, 1),
                "csv_path": csv_path,
                "json_path": json_path,
            }
            results.append(result)

            print(f"\n  完了: {validation['count']}本, {elapsed:.1f}秒")
            if not validation["valid"]:
                print(f"  [WARNING] 検証に問題があります")

        else:
            continue
        break  # SaxoAuthError で内側ループを break した場合、外側も break

    return results


def generate_quality_report(results: List[Dict[str, Any]], output_path: str) -> None:
    """
    データ品質レポートを Markdown 形式で出力する。

    Args:
        results: 各データセットの結果サマリー
        output_path: 出力ファイルパス
    """
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    lines = [
        "# FX OHLCV データ品質レポート",
        "",
        f"**生成日時**: {now}",
        "",
        "---",
        "",
        "## 取得結果サマリー",
        "",
        "| 通貨ペア | 時間足 | ステータス | 本数 | 期間 | 欠損率 | 重複 | 異常価格 | HL異常 | ギャップ |",
        "|---------|-------|----------|------|------|-------|------|---------|-------|---------|",
    ]

    for r in results:
        status_icon = {
            "success": "OK",
            "warning": "WARN",
            "failed_auth": "ERROR(auth)",
            "failed_api": "ERROR(api)",
            "failed_unknown": "ERROR",
            "empty": "EMPTY",
        }.get(r.get("status", "unknown"), "?")

        period = (
            f"{r.get('first_datetime', '-')[:10]} 〜 {r.get('last_datetime', '-')[:10]}"
            if r.get("first_datetime") and r.get("last_datetime")
            else "-"
        )

        lines.append(
            f"| {r.get('symbol', '-')} "
            f"| {r.get('timeframe', '-')} "
            f"| {status_icon} "
            f"| {r.get('count', 0):,} "
            f"| {period} "
            f"| {r.get('missing_rate_pct', '-')}% "
            f"| {r.get('duplicates', '-')} "
            f"| {r.get('invalid_prices', '-')} "
            f"| {r.get('invalid_hl', '-')} "
            f"| {r.get('significant_gaps', '-')} |"
        )

    # 合格/警告/失敗の集計
    success_count = sum(1 for r in results if r.get("status") == "success")
    warning_count = sum(1 for r in results if r.get("status") == "warning")
    failed_count = sum(1 for r in results if r.get("status", "").startswith("failed"))
    total_candles = sum(r.get("count", 0) for r in results)

    lines.extend([
        "",
        "---",
        "",
        "## 品質チェック詳細",
        "",
        f"- **成功**: {success_count}データセット",
        f"- **警告**: {warning_count}データセット",
        f"- **失敗**: {failed_count}データセット",
        f"- **総取得本数**: {total_candles:,}本",
        "",
        "### 品質基準",
        "",
        "| チェック項目 | 基準 |",
        "|------------|------|",
        "| 欠損率 | 5%以下（土日・祝日のギャップを除く） |",
        "| 重複タイムスタンプ | 0件 |",
        "| 異常価格（ゼロ・負） | 0件 |",
        "| High < Low | 0件 |",
        "| volume | 0（Saxo FX API は提供なし）|",
        "",
        "### 重要ギャップ詳細",
        "",
    ])

    for r in results:
        gap_details = r.get("gap_details", [])
        if gap_details:
            lines.append(f"**{r.get('symbol')} {r.get('timeframe')}**:")
            for g in gap_details[:5]:
                lines.append(f"  - {g.get('from', '?')} 〜 {g.get('to', '?')} ({g.get('gap_hours', '?')}時間)")
            lines.append("")

    lines.extend([
        "---",
        "",
        "## 工程3以降への引き継ぎ",
        "",
        "### ファイルパス",
        "",
        "```",
        f"data/fx/ohlcv/",
        "  USDJPY_1h.csv / .json",
        "  USDJPY_4h.csv / .json",
        "  USDJPY_1d.csv / .json",
        "  EURJPY_1h.csv / .json",
        "  EURJPY_4h.csv / .json",
        "  EURJPY_1d.csv / .json",
        "```",
        "",
        "### データ形式",
        "",
        "```csv",
        "timestamp,datetime,open,high,low,close,volume",
        "1727654400000,2024-09-30 00:00:00,142.233,143.919,141.646,143.625,0",
        "```",
        "",
        "- `timestamp`: UNIX タイムスタンプ（ミリ秒・UTC）",
        "- `datetime`: ISO形式日時文字列（UTC）",
        "- `open/high/low/close`: Mid 価格（Bid/Ask 平均）",
        "- `volume`: 常に 0（Saxo FX API はボリューム非提供）",
        "",
    ])

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    logger.info(f"品質レポート保存: {output_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Saxo FX OHLCV データ全組み合わせ一括取得"
    )
    parser.add_argument("--days", type=int, default=730, help="取得日数（デフォルト: 730日 = 2年）")
    parser.add_argument("--exchange", default="saxo_sim", help="saxo_sim or saxo")
    parser.add_argument("--resume", action="store_true", help="再開モード（既存ファイルの範囲をスキップ）")
    parser.add_argument("--dry-run", action="store_true", help="実行計画を表示して終了")
    parser.add_argument(
        "--symbols",
        default="USD/JPY,EUR/JPY",
        help="対象通貨ペア（カンマ区切り）。デフォルト: USD/JPY,EUR/JPY",
    )
    parser.add_argument(
        "--timeframes",
        default="1h,4h,1d",
        help="対象時間足（カンマ区切り）。デフォルト: 1h,4h,1d",
    )
    args = parser.parse_args()

    symbols = [s.strip() for s in args.symbols.split(",")]
    timeframes = [t.strip() for t in args.timeframes.split(",")]

    print_execution_plan(symbols, timeframes, args.days, args.exchange, args.resume)

    if args.dry_run:
        print("\n[DRY RUN] 実行計画のみ表示。実際の取得は行いません。")
        return

    # Token チェック
    from dotenv import load_dotenv
    load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

    import os as _os
    token = (
        _os.getenv("SAXO_SIM_TOKEN", "")
        if args.exchange == "saxo_sim"
        else _os.getenv("SAXO_TOKEN", "")
    )
    if token:
        check_token_expiry(token, min_hours=1.0)
    else:
        print(f"\n[ERROR] Token が未設定です。.env の SAXO_SIM_TOKEN を確認してください。")
        sys.exit(1)

    # クライアント初期化
    try:
        client = SaxoClient(args.exchange)
    except ValueError as e:
        print(f"\n[ERROR] SaxoClient 初期化失敗: {e}")
        sys.exit(1)

    # 全組み合わせ取得
    all_start = time_module.time()
    results = run_all(
        symbols=symbols,
        timeframes=timeframes,
        days=args.days,
        exchange=args.exchange,
        resume=args.resume,
        client=client,
    )
    total_elapsed = time_module.time() - all_start

    # 品質レポート生成
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    report_path = os.path.join(OUTPUT_DIR, "data_quality_report.md")
    generate_quality_report(results, report_path)

    # 最終サマリー
    print()
    print("=" * 70)
    print("  全データ取得完了")
    print("=" * 70)
    print()

    success = [r for r in results if r.get("status") == "success"]
    warning = [r for r in results if r.get("status") == "warning"]
    failed = [r for r in results if r.get("status", "").startswith("failed") or r.get("status") == "empty"]
    total_candles = sum(r.get("count", 0) for r in results)

    print(f"  成功   : {len(success)} / {len(results)} データセット")
    print(f"  警告   : {len(warning)} データセット")
    print(f"  失敗   : {len(failed)} データセット")
    print(f"  総本数 : {total_candles:,}本")
    print(f"  実行時間: {total_elapsed:.1f}秒 ({total_elapsed/60:.1f}分)")
    print()
    print(f"  品質レポート: {report_path}")
    print()

    for r in results:
        status_str = {
            "success": "[OK]   ",
            "warning": "[WARN] ",
            "empty": "[EMPTY]",
        }.get(r.get("status", ""), "[ERROR]")
        print(
            f"  {status_str} {r.get('symbol', '-'):<10} {r.get('timeframe', '-'):<5} "
            f"{r.get('count', 0):>7,}本  {r.get('missing_rate_pct', '-')}%欠損"
        )

    print("=" * 70)

    # Token 残り時間を最後に再表示
    if token:
        try:
            payload_b64 = token.split(".")[1]
            padded = payload_b64 + "=" * (4 - len(payload_b64) % 4)
            payload = json.loads(base64.urlsafe_b64decode(padded))
            exp = int(payload.get("exp", 0))
            remaining = exp - int(time_module.time())
            if remaining > 0:
                print(f"\n  Token 残り有効時間: {remaining / 3600:.1f} 時間")
        except Exception:
            pass

    # 失敗があれば非ゼロ終了
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
