"""CLIインターフェース

Usage:
    win5 collect --start 2020-01-01 --end 2025-12-31
    win5 train --start 2020-01-01 --end 2024-12-31
    win5 predict --date 2026-02-15 --budget 10000
    win5 backtest --start 2023-01-01 --end 2025-12-31
    win5 status
    win5 dashboard
"""

import sys
from datetime import date, datetime

import click
from rich.console import Console
from rich.table import Table

console = Console()


def _parse_date(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


@click.group()
@click.version_option(version="0.1.0", prog_name="win5-predictor")
def cli():
    """JRA Win5 予想ソフト - LightGBMベース"""
    pass


@cli.command()
@click.option("--start", required=True, help="開始日 (YYYY-MM-DD)")
@click.option("--end", required=True, help="終了日 (YYYY-MM-DD)")
@click.option("--no-profiles", is_flag=True, help="馬・騎手プロフィール収集をスキップ")
@click.option("--no-cache", is_flag=True, help="キャッシュを使用しない")
def collect(start: str, end: str, no_profiles: bool, no_cache: bool):
    """過去データを収集する"""
    _add_src_to_path()
    from app.workflow import collect_data

    s, e = _parse_date(start), _parse_date(end)
    console.print(f"[bold green]データ収集開始[/]: {s} → {e}")
    collect_data(s, e, profiles=not no_profiles, cache=not no_cache)
    console.print("[bold green]データ収集完了[/]")


@cli.command()
@click.option("--start", required=True, help="学習開始日 (YYYY-MM-DD)")
@click.option("--end", required=True, help="学習終了日 (YYYY-MM-DD)")
@click.option("--no-odds", is_flag=True, help="オッズ特徴量を除外する")
@click.option("--optimize", is_flag=True, help="Optunaでハイパラ最適化する")
@click.option("--n-trials", default=50, help="Optuna試行回数")
def train(start: str, end: str, no_odds: bool, optimize: bool, n_trials: int):
    """モデルを学習する"""
    _add_src_to_path()
    from app.workflow import train_model

    s, e = _parse_date(start), _parse_date(end)
    console.print(f"[bold green]モデル学習開始[/]: {s} → {e}")
    if optimize:
        console.print(f"  Optuna最適化: {n_trials}試行")

    model_id = train_model(
        s, e,
        include_odds=not no_odds,
        optimize_hyperparams=optimize,
        n_trials=n_trials,
    )
    console.print(f"[bold green]学習完了[/]: model_id={model_id}")


@cli.command()
@click.option("--date", "target_date", required=True, help="対象日 (YYYY-MM-DD)")
@click.option("--budget", default=10000, help="予算(円)", show_default=True)
@click.option("--model", "model_path", default=None, help="モデルファイルパス")
def predict(target_date: str, budget: int, model_path: str | None):
    """Win5予想を行う"""
    _add_src_to_path()
    from app.workflow import predict_win5

    td = _parse_date(target_date)
    console.print(f"[bold green]Win5予測[/]: {td}, 予算=¥{budget:,}")

    result = predict_win5(td, budget=budget, model_path=model_path)

    # レポート表示
    console.print()
    console.print(result["report"])

    # 詳細テーブル表示
    if result["ticket"]:
        _display_ticket(result)


@cli.command()
@click.option("--start", required=True, help="開始日 (YYYY-MM-DD)")
@click.option("--end", required=True, help="終了日 (YYYY-MM-DD)")
@click.option("--budget", default=10000, help="毎回の予算(円)", show_default=True)
@click.option("--model", "model_path", default=None, help="モデルファイルパス")
def backtest(start: str, end: str, budget: int, model_path: str | None):
    """バックテストを実行する"""
    _add_src_to_path()
    from app.workflow import run_backtest

    s, e = _parse_date(start), _parse_date(end)
    console.print(f"[bold green]バックテスト[/]: {s} → {e}, 予算=¥{budget:,}")

    result = run_backtest(s, e, budget=budget, model_path=model_path)

    console.print()
    console.print(result.get("report", ""))


@cli.command()
def status():
    """システムの状態を確認する"""
    _add_src_to_path()
    from app.workflow import get_system_status

    st = get_system_status()

    table = Table(title="Win5 Predictor Status")
    table.add_column("Item", style="cyan")
    table.add_column("Value", style="green")

    table.add_row("DB Path", st["db_path"])
    table.add_row("DB Exists", str(st["db_exists"]))
    table.add_row("Races", f"{st['races_count']:,}")
    table.add_row("Results", f"{st['results_count']:,}")

    if st["date_range"]:
        table.add_row("Date Range", f"{st['date_range'][0]} ~ {st['date_range'][1]}")
    else:
        table.add_row("Date Range", "N/A")

    if st["active_model"]:
        m = st["active_model"]
        table.add_row("Active Model", m["model_id"])
        table.add_row("Model AUC", f"{m['auc']:.4f}")
        table.add_row("Features", str(m["feature_count"]))
    else:
        table.add_row("Active Model", "None")

    console.print(table)


@cli.command()
@click.option("--port", default=8501, help="ポート番号")
def dashboard(port: int):
    """Streamlitダッシュボードを起動する"""
    import subprocess

    app_path = str(
        __import__("pathlib").Path(__file__).parent / "streamlit_app.py"
    )
    console.print(f"[bold green]Dashboard starting on port {port}...[/]")
    subprocess.run(
        [sys.executable, "-m", "streamlit", "run", app_path, "--server.port", str(port)],
    )


def _display_ticket(result: dict):
    """Win5チケットの詳細をリッチテーブルで表示する"""
    ticket = result["ticket"]
    if not ticket or not ticket.selections:
        return

    table = Table(title="Win5 推奨買い目")
    table.add_column("Race", style="cyan")
    table.add_column("馬番", style="green")
    table.add_column("馬名")
    table.add_column("予測勝率", justify="right")

    for sel in ticket.selections:
        for i, (num, name, prob) in enumerate(
            zip(sel.horse_numbers, sel.horse_names, sel.probabilities)
        ):
            race_label = f"R{sel.race_number}" if i == 0 else ""
            table.add_row(race_label, str(num), name, f"{prob:.1%}")
        table.add_section()

    console.print(table)

    ev = result.get("ev_info", {})
    if ev:
        console.print(
            f"\n  組合せ数: {ticket.num_combinations} | "
            f"購入金額: ¥{ticket.total_cost:,} | "
            f"的中確率: {ticket.total_hit_probability:.4%} | "
            f"期待値: ¥{ev.get('expected_value', 0):,.0f}"
        )


def _add_src_to_path():
    """srcディレクトリをsys.pathに追加する"""
    src_dir = str(__import__("pathlib").Path(__file__).resolve().parent.parent)
    if src_dir not in sys.path:
        sys.path.insert(0, src_dir)


if __name__ == "__main__":
    _add_src_to_path()
    cli()
