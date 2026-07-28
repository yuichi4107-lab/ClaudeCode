from datetime import date

from etl.win5_results_csv import load_win5_results


def test_load_skips_comments_and_parses(tmp_path):
    p = tmp_path / "w.csv"
    p.write_text(
        "# JRA WIN5 results 2026 -- comment\n"
        "# another comment\n"
        "date,race,grade,payout_yen,hit_tickets,p1,p2,p3,p4,p5,pops_verified\n"
        "2026-01-04,日刊スポーツ賞中山金杯,G3,2775800,184,5,2,1,4,7,True\n"
        "2026-01-11,キャリーオーバー回,G3,,0,1,1,1,1,1,False\n",
        encoding="utf-8",
    )
    rows = load_win5_results(p)
    assert rows[0] == {"date": date(2026, 1, 4), "payout_yen": 2775800.0}
    assert rows[1]["date"] == date(2026, 1, 11)
    assert rows[1]["payout_yen"] is None
