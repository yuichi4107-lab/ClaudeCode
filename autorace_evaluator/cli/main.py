import argparse
import json
import logging
import re
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


def _parse_date(s: str) -> str:
    """'YYYYMMDD' または 'YYYY-MM-DD' を 'YYYY-MM-DD' に正規化する。"""
    s = s.replace("-", "")
    return f"{s[0:4]}-{s[4:6]}-{s[6:8]}"


def run_scrape(args) -> None:
    from autorace_evaluator.config import settings
    from autorace_evaluator.scraper.race_result import scrape_races

    if args.date:
        from_date = to_date = _parse_date(args.date)
    elif args.from_date and args.to_date:
        from_date = _parse_date(args.from_date)
        to_date = _parse_date(args.to_date)
    else:
        print("scrape: --date または --from-date/--to-date の両方を指定してください")
        sys.exit(1)
        return

    venues = settings.VENUE_SLUGS if args.venue == "all" else [args.venue]

    stats = scrape_races(
        from_date=from_date,
        to_date=to_date,
        venues=venues,
        use_cache=not args.no_cache,
        dump_dir=args.dump_html,
        progress=True,
    )

    print(
        "scrape done: "
        f"fetched={stats['fetched']} not_found={stats['not_found']} "
        f"cancelled={stats['cancelled']} skipped={stats['skipped']} "
        f"errors={stats['errors']}"
    )


def run_evaluate(args) -> None:
    import pandas as pd

    from autorace_evaluator.config import settings
    from autorace_evaluator.metrics import report as report_mod
    from autorace_evaluator.metrics.meeting import update_meeting_ids
    from autorace_evaluator.storage import database, repository

    db_path = Path(settings.DB_PATH)
    if not db_path.exists():
        print(
            f"evaluate: DBファイルが見つかりません ({settings.DB_PATH})。"
            "先に scrape または parse-json --save を実行してください"
        )
        sys.exit(1)
        return

    from_date = _parse_date(args.from_date)
    to_date = _parse_date(args.to_date)
    venue = None if args.venue == "all" else args.venue

    conn = database.get_connection(settings.DB_PATH)
    try:
        update_meeting_ids(conn)
        rows = repository.get_entries_with_race(conn, from_date, to_date, venue)
    finally:
        conn.close()

    if not rows:
        print(
            "evaluate: 対象期間にデータがありません "
            f"(from={from_date} to={to_date} venue={venue or 'all'})"
        )
        return

    entries_df = pd.DataFrame([dict(row) for row in rows])
    rep = report_mod.build_report(entries_df, include_retrial=args.include_retrial)
    report_mod.print_report(rep, top_n=args.top, player_no=args.player)

    csv_path = args.csv
    if not csv_path:
        suffix = f"_{venue}" if venue else ""
        csv_path = str(
            Path(settings.REPORT_DIR)
            / f"autorace_eval_{from_date}_{to_date}{suffix}.csv"
        )
    report_mod.to_csv(rep, csv_path)
    print(f"\nCSVを保存しました: {csv_path}")


_FILENAME_META_RE = re.compile(
    r"(kawaguchi2|kawaguchi|isesaki|hamamatsu|sanyou|iizuka)_(\d{4}-\d{2}-\d{2})_(\d+)"
)


def _resolve_url_meta(url_meta_arg: str | None, filename: str) -> tuple[dict, str | None]:
    """--url-meta 引数、なければファイル名から venue/date/race_no を推定する。

    どちらも解決できない場合は venue="unknown", date="1970-01-01", race_no=0 と
    警告メッセージを返す(warning は None でなければ呼び出し側で warnings に追加すること)。
    """
    if url_meta_arg:
        parts = url_meta_arg.split(",")
        if len(parts) == 3:
            venue, date, race_no_s = (p.strip() for p in parts)
            try:
                return {"venue": venue, "date": date, "race_no": int(race_no_s)}, None
            except ValueError:
                pass
        return (
            {"venue": "unknown", "date": "1970-01-01", "race_no": 0},
            f"--url-meta の指定が不正です({url_meta_arg!r})。venue=unknown で解析します。",
        )

    m = _FILENAME_META_RE.search(filename)
    if m:
        venue, date, race_no_s = m.groups()
        return {"venue": venue, "date": date, "race_no": int(race_no_s)}, None

    return (
        {"venue": "unknown", "date": "1970-01-01", "race_no": 0},
        f"ファイル名からメタ情報を推定できません({filename!r})。venue=unknown で解析します。",
    )


def _print_human_readable(result: dict) -> None:
    if "error" in result:
        print(f"[ERROR] {result['error']}")
        for w in result.get("warnings", []):
            print(f"  !! {w}")
        return

    race = result["race"]
    entries = result["entries"]
    payouts = result["payouts"]
    warnings = result.get("warnings", [])

    print("=== レース情報 ===")
    for key in (
        "race_id", "venue", "race_date", "race_no", "race_name", "distance",
        "weather", "track_status", "trial_track_status", "temperature",
        "track_temp", "meeting_id", "field_size",
    ):
        print(f"  {key}: {race.get(key)}")

    print(f"\n=== 出走表 ({len(entries)}件) ===")
    for e in entries:
        print(
            "  車{car_no} 着{finish} [{status}] "
            "選手{player_no} {player_name} ハンデ{handicap} "
            "試走{trial}(再{retrial}) 競走{race_time} "
            "ST{st}(F{flying}) {note}".format(
                car_no=e["car_no"], finish=e["finish_pos"], status=e["status"],
                player_no=e["player_no"], player_name=e["player_name"] or "-",
                handicap=e["handicap"], trial=e["trial_time"], retrial=e["is_retrial"],
                race_time=e["race_time"], st=e["st"],
                flying=e["is_flying"], note=e["violation_note"] or "",
            )
        )

    print(f"\n=== 払戻 ({len(payouts)}件) ===")
    for p in payouts:
        print(f"  {p['bet_type']}: {p['combination']} -> {p['payout']}")

    if warnings:
        print(f"\n*** 警告 ({len(warnings)}件) ***")
        for w in warnings:
            print(f"  !! {w}")
    else:
        print("\n警告なし")


def _load_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def run_parse_json(args) -> None:
    """dump された RaceResult API 応答(*.result.json)をパースして確認する。

    同じディレクトリに {stem}.other.json があれば OtherRaceInfo として読む。
    """
    from autorace_evaluator.parsers import result_parser
    from autorace_evaluator.storage import database, repository

    path = Path(args.file)
    result_json = _load_json(path)
    if result_json is None:
        print(f"ファイル読み込みエラー: {path}")
        sys.exit(1)
        return

    other_path = Path(str(path).replace(".result.json", ".other.json"))
    other_json = _load_json(other_path) if other_path != path else None

    url_meta, meta_warning = _resolve_url_meta(args.url_meta, path.name)

    result = result_parser.parse_api_race_result(result_json, other_json, url_meta)
    if meta_warning:
        result.setdefault("warnings", []).insert(0, meta_warning)

    if args.as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        _print_human_readable(result)

    if "error" in result:
        sys.exit(1)
        return

    if args.save:
        conn = database.get_connection()
        try:
            database.init_db(conn)
            for entry in result["entries"]:
                if entry.get("player_no") is not None and entry.get("player_name"):
                    repository.upsert_player(conn, entry["player_no"], entry["player_name"])
            repository.upsert_race(conn, result["race"])
            repository.upsert_entries(conn, result["race"]["race_id"], result["entries"])
            if result["payouts"]:
                repository.upsert_payouts(conn, result["race"]["race_id"], result["payouts"])
        finally:
            conn.close()
        print(f"\nDBへ保存しました: {result['race']['race_id']}")


def main():
    parser = argparse.ArgumentParser(
        prog="autorace",
        description="オートレース選手能力評価システム",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # scrape
    p_scrape = sub.add_parser("scrape", help="レース結果を収集する")
    p_scrape.add_argument("--from-date", dest="from_date", help="開始日")
    p_scrape.add_argument("--to-date", dest="to_date", help="終了日")
    p_scrape.add_argument("--date", help="特定日付 YYYYMMDD または YYYY-MM-DD")
    p_scrape.add_argument(
        "--venue",
        choices=["all", "kawaguchi", "isesaki", "hamamatsu", "sanyou", "iizuka"],
        default="all",
    )
    p_scrape.add_argument("--no-cache", action="store_true", dest="no_cache")
    p_scrape.add_argument(
        "--dump-html", dest="dump_html", metavar="DIR",
        help="取得したAPI応答JSONを可読名で保存するディレクトリ",
    )

    # evaluate
    p_eval = sub.add_parser("evaluate", help="選手能力評価指標を算出する")
    p_eval.add_argument("--from-date", required=True, dest="from_date")
    p_eval.add_argument("--to-date", required=True, dest="to_date")
    p_eval.add_argument(
        "--venue",
        choices=["all", "kawaguchi", "isesaki", "hamamatsu", "sanyou", "iizuka"],
        default="all",
    )
    p_eval.add_argument("--player", dest="player", type=int, help="選手登録番号で絞り込み")
    p_eval.add_argument("--csv", dest="csv", help="結果をCSV出力するパス")
    p_eval.add_argument(
        "--top", dest="top", type=int, default=20,
        help="上位N件を表示(デフォルト: 20)",
    )
    p_eval.add_argument(
        "--include-retrial", action="store_true", dest="include_retrial",
        help="再試走レコードを集計に含める",
    )

    # parse-json
    p_parse = sub.add_parser(
        "parse-json", help="dumpされたAPI応答JSONをパースして確認する")
    p_parse.add_argument("file", help="RaceResult API応答(*.result.json)のパス")
    p_parse.add_argument(
        "--url-meta", dest="url_meta", metavar="VENUE,DATE,RACE_NO",
        help="URLから得られるはずのメタ情報(会場,日付,レース番号)を手動指定",
    )
    p_parse.add_argument("--json", action="store_true", dest="as_json", help="結果をJSONで出力する")
    p_parse.add_argument("--save", action="store_true", help="パース結果をDBへ保存する")

    args = parser.parse_args()

    if args.command == "scrape":
        run_scrape(args)
    elif args.command == "evaluate":
        run_evaluate(args)
    elif args.command == "parse-json":
        run_parse_json(args)


if __name__ == "__main__":
    main()
