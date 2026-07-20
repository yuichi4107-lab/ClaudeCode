"""autorace_evaluator.metrics.report と cli.main.run_evaluate の結線テスト。"""

import argparse
import json
from pathlib import Path

import pandas as pd
import pytest

from autorace_evaluator.cli import main as cli_main
from autorace_evaluator.config import settings
from autorace_evaluator.metrics import report as report_mod
from autorace_evaluator.parsers import result_parser
from autorace_evaluator.storage import database, repository
from tests.conftest import synthetic_league

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "autorace"
SYNTHETIC_RESULT_PATH = FIXTURES_DIR / "synthetic_result_api.json"
SYNTHETIC_OTHER_PATH = FIXTURES_DIR / "synthetic_other_api.json"


# ------------------------------------------------------------- build_report

def test_build_report_columns_and_ordering():
    entries, _truth = synthetic_league(seed=1, n_players=20, n_races=100)
    report = report_mod.build_report(entries)
    table = report["table"]

    assert list(table.columns) == report_mod.COLUMN_ORDER
    assert set(table["player_no"]) == set(range(1, 21))

    scores = table["total_score"].tolist()
    non_null = [s for s in scores if pd.notna(s)]
    assert non_null == sorted(non_null, reverse=True)
    nan_positions = [i for i, s in enumerate(scores) if pd.isna(s)]
    if nan_positions:
        assert min(nan_positions) >= len(non_null)  # NaN は末尾

    assert "maintenance_overall" in report
    assert set(report["diagnostics"]) == {"start", "attack", "wet"}


def test_n_valid_scores_counts_present_metrics():
    entries, _truth = synthetic_league(seed=2, n_players=15, n_races=60)
    table = report_mod.build_report(entries)["table"]
    for _, row in table.iterrows():
        expected = sum(pd.notna(row[c]) for c in report_mod.SCORE_COLS)
        assert row["n_valid_scores"] == expected


def test_total_score_is_average_of_valid_scores(league):
    entries, _truth = league
    table = report_mod.build_report(entries)["table"]
    have_all = table[table["n_valid_scores"] == 3]
    assert not have_all.empty
    row = have_all.iloc[0]
    expected = sum(row[c] for c in report_mod.SCORE_COLS) / 3
    assert abs(row["total_score"] - expected) < 1e-9


# --------------------------------------------------------------- print_report

def test_print_report_runs_without_error(capsys):
    entries, _truth = synthetic_league(seed=4, n_players=15, n_races=60)
    report = report_mod.build_report(entries)

    report_mod.print_report(report, top_n=5)
    out = capsys.readouterr().out
    assert "総合レポート" in out
    assert "整備力: 全体分布" in out

    report_mod.print_report(report, top_n=5, player_no=1)
    out = capsys.readouterr().out
    assert "選手 1" in out
    assert "全体内百分位" in out


def test_print_report_handles_unknown_player(capsys):
    entries, _truth = synthetic_league(seed=5, n_players=10, n_races=20)
    report = report_mod.build_report(entries)
    report_mod.print_report(report, player_no=999999)
    out = capsys.readouterr().out
    assert "見つかりません" in out


# -------------------------------------------------------------------- to_csv

def test_to_csv_creates_directory(tmp_path):
    entries, _truth = synthetic_league(seed=6, n_players=10, n_races=40)
    report = report_mod.build_report(entries)
    csv_path = tmp_path / "nested" / "out.csv"
    report_mod.to_csv(report, str(csv_path))
    assert csv_path.exists()
    saved = pd.read_csv(csv_path)
    assert list(saved.columns) == report_mod.COLUMN_ORDER


# --------------------------------------------------------- run_evaluate (E2E)

def _insert_result_html(conn, venue, date, race_no):
    result_json = json.loads(SYNTHETIC_RESULT_PATH.read_text(encoding="utf-8"))
    other_json = json.loads(SYNTHETIC_OTHER_PATH.read_text(encoding="utf-8"))
    url_meta = {"venue": venue, "date": date, "race_no": race_no}
    result = result_parser.parse_api_race_result(result_json, other_json, url_meta)
    assert "error" not in result
    for entry in result["entries"]:
        if entry.get("player_no") is not None and entry.get("player_name"):
            repository.upsert_player(conn, entry["player_no"], entry["player_name"])
    repository.upsert_race(conn, result["race"])
    repository.upsert_entries(conn, result["race"]["race_id"], result["entries"])
    if result["payouts"]:
        repository.upsert_payouts(conn, result["race"]["race_id"], result["payouts"])
    return result["race"]["race_id"]


def _base_args(**overrides):
    args = dict(
        from_date="2026-07-18", to_date="2026-07-19", venue="all",
        player=None, csv=None, top=20, include_retrial=False,
    )
    args.update(overrides)
    return argparse.Namespace(**args)


def test_run_evaluate_produces_csv(tmp_path, monkeypatch, capsys):
    db_path = tmp_path / "autorace.db"
    report_dir = tmp_path / "reports"
    monkeypatch.setattr(settings, "DB_PATH", str(db_path))
    monkeypatch.setattr(settings, "REPORT_DIR", str(report_dir))

    conn = database.get_connection(str(db_path))
    try:
        database.init_db(conn)
        _insert_result_html(conn, "kawaguchi", "2026-07-18", 3)
        _insert_result_html(conn, "kawaguchi", "2026-07-19", 3)
    finally:
        conn.close()

    cli_main.run_evaluate(_base_args())

    out = capsys.readouterr().out
    assert "総合レポート" in out
    assert "CSVを保存しました" in out

    expected_csv = report_dir / "autorace_eval_2026-07-18_2026-07-19.csv"
    assert expected_csv.exists()
    saved = pd.read_csv(expected_csv)
    assert list(saved.columns) == report_mod.COLUMN_ORDER
    assert len(saved) > 0


def test_run_evaluate_custom_csv_path(tmp_path, monkeypatch):
    db_path = tmp_path / "autorace.db"
    monkeypatch.setattr(settings, "DB_PATH", str(db_path))
    monkeypatch.setattr(settings, "REPORT_DIR", str(tmp_path / "reports"))

    conn = database.get_connection(str(db_path))
    try:
        database.init_db(conn)
        _insert_result_html(conn, "kawaguchi", "2026-07-18", 3)
    finally:
        conn.close()

    custom_csv = tmp_path / "custom" / "my_report.csv"
    cli_main.run_evaluate(_base_args(
        from_date="2026-07-18", to_date="2026-07-18", csv=str(custom_csv)))
    assert custom_csv.exists()


def test_run_evaluate_missing_db_exits(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(settings, "DB_PATH", str(tmp_path / "does_not_exist.db"))
    with pytest.raises(SystemExit):
        cli_main.run_evaluate(_base_args())
    out = capsys.readouterr().out
    assert "先に scrape または parse-json --save" in out


def test_run_evaluate_no_rows_in_range(tmp_path, monkeypatch, capsys):
    db_path = tmp_path / "autorace.db"
    monkeypatch.setattr(settings, "DB_PATH", str(db_path))
    monkeypatch.setattr(settings, "REPORT_DIR", str(tmp_path / "reports"))

    conn = database.get_connection(str(db_path))
    try:
        database.init_db(conn)
        _insert_result_html(conn, "kawaguchi", "2026-07-18", 3)
    finally:
        conn.close()

    cli_main.run_evaluate(_base_args(from_date="2020-01-01", to_date="2020-01-02"))
    out = capsys.readouterr().out
    assert "対象期間にデータがありません" in out
