"""整備力・スタート力・突っ込み度の3指標を統合した最終レポート。

build_report() は3指標をそれぞれ計算し、player_no で外部結合(全選手を
拾う。ある指標だけ min_races/min_pairs 未満で NaN になっている選手も
一覧には残す)した統合テーブルを作る。
"""

from pathlib import Path

import numpy as np
import pandas as pd
from colorama import Fore, Style
from colorama import init as colorama_init

from autorace_evaluator.metrics.attack import compute_attack
from autorace_evaluator.metrics.maintenance import compute_maintenance
from autorace_evaluator.metrics.start_power import compute_start_power

SCORE_COLS = ["maintenance_score", "start_score", "attack_score"]

COLUMN_ORDER = [
    "player_no", "player_name", "total_score", "n_valid_scores",
    "maintenance_score", "n_pairs", "improved_rate", "worsened_rate", "mean_diff",
    "start_score", "n_st", "mean_st", "flying_rate", "dash",
    "attack_score", "attack_a", "mean_passed", "pass_rate",
    "accident_rate", "violation_rate", "n_races",
]

_MAINTENANCE_COLS = ["player_no", "maintenance_score", "n_pairs",
                     "improved_rate", "worsened_rate", "mean_diff"]
_START_COLS = ["player_no", "start_score", "n_st", "mean_st", "flying_rate", "dash"]
_ATTACK_COLS = ["player_no", "attack_score", "attack_a", "mean_passed", "pass_rate",
                "accident_rate", "violation_rate", "n_races"]


def _ensure_cols(df: pd.DataFrame, cols: list) -> pd.DataFrame:
    """df を cols だけの列構成にする(欠けている列は NaN で補う)。"""
    df = df.copy()
    for c in cols:
        if c not in df.columns:
            df[c] = np.nan
    return df[cols]


def _players_master(entries_df: pd.DataFrame) -> pd.DataFrame:
    """entries_df から player_no -> player_name の対応表を作る(最新の非NULL名を採用)。"""
    having = entries_df.dropna(subset=["player_no"])
    if having.empty:
        return pd.DataFrame(columns=["player_no", "player_name"])

    def _last_name(s: pd.Series):
        s = s.dropna()
        return s.iloc[-1] if not s.empty else None

    players = (
        having.groupby("player_no")["player_name"]
        .apply(_last_name)
        .reset_index()
    )
    return players


def build_report(entries_df: pd.DataFrame, include_retrial: bool = False) -> dict:
    """entries_df から3指標を計算し、統合レポートを返す。

    Returns:
        {"table": DataFrame(total_score降順・NaNは末尾),
         "maintenance_overall": dict,
         "diagnostics": {"start": dict, "attack": dict}}
    """
    m_per_player, _pairs, m_overall = compute_maintenance(
        entries_df, include_retrial=include_retrial)
    s_per_player, s_diag = compute_start_power(entries_df)
    a_per_player, a_diag = compute_attack(entries_df)

    players = _players_master(entries_df)
    m = _ensure_cols(m_per_player, _MAINTENANCE_COLS)
    s = _ensure_cols(s_per_player, _START_COLS)
    a = _ensure_cols(a_per_player, _ATTACK_COLS)

    table = (
        players.merge(m, on="player_no", how="outer")
               .merge(s, on="player_no", how="outer")
               .merge(a, on="player_no", how="outer")
    )

    table["n_valid_scores"] = table[SCORE_COLS].notna().sum(axis=1)
    table["total_score"] = table[SCORE_COLS].mean(axis=1, skipna=True)

    table = _ensure_cols(table, COLUMN_ORDER)
    table = table.sort_values(
        "total_score", ascending=False, na_position="last"
    ).reset_index(drop=True)

    return {
        "table": table,
        "maintenance_overall": m_overall,
        "diagnostics": {"start": s_diag, "attack": a_diag},
    }


def to_csv(report: dict, path: str) -> None:
    """report["table"] を CSV に書き出す。親ディレクトリは自動作成する。"""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    report["table"].to_csv(p, index=False)


def _fmt_float(x) -> str:
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return ""
    return f"{x:.3f}"


def _print_overall(report: dict) -> None:
    overall = report.get("maintenance_overall", {})
    print("\n--- 整備力: 全体分布 ---")
    if not overall or overall.get("n_pairs", 0) == 0:
        print("  ペアデータなし")
    else:
        print(
            f"  mean={overall['mean']:.3f} sd={overall['sd']:.3f} "
            f"p10={overall['p10']:.3f} p25={overall['p25']:.3f} "
            f"p50={overall['p50']:.3f} p75={overall['p75']:.3f} "
            f"p90={overall['p90']:.3f} improved_rate={overall['improved_rate']:.3f}"
        )

    diag = report.get("diagnostics", {})

    start_diag = diag.get("start") or {}
    print("\n--- スタート力: ダッシュ力モデル診断 ---")
    if start_diag:
        print(f"  n_samples={start_diag.get('n_samples')} "
              f"n_races={start_diag.get('n_races')}")
        print(f"  betas={start_diag.get('betas')}")
        print(f"  beta_st_positive={start_diag.get('beta_st_positive')}")
    else:
        print("  診断データなし")

    attack_diag = diag.get("attack") or {}
    print("\n--- 突っ込み度: 期待着順モデル診断 ---")
    if attack_diag:
        print(f"  n_samples={attack_diag.get('n_samples')}")
        print(f"  betas={attack_diag.get('betas')}")
    else:
        print("  診断データなし")


def _print_player_detail(table: pd.DataFrame, player_no: int) -> None:
    row = table[table["player_no"] == player_no]
    if row.empty:
        print(f"選手番号 {player_no} のデータが見つかりません")
        return
    row = row.iloc[0]

    print(f"=== 選手 {player_no} {row.get('player_name') or '-'} ===")
    for col in table.columns:
        val = row[col]
        if isinstance(val, float) and pd.isna(val):
            val = "-"
        elif isinstance(val, float):
            val = f"{val:.3f}"
        print(f"  {col}: {val}")

    print("\n--- 全体内百分位 ---")
    for score_col in SCORE_COLS:
        val = row[score_col]
        if isinstance(val, float) and pd.isna(val):
            print(f"  {score_col}: NaN (参考外)")
            continue
        valid = table[score_col].dropna()
        rank = int((valid > val).sum()) + 1
        pct = float((valid <= val).mean()) * 100
        print(f"  {score_col}: value={val:.3f} rank={rank}/{len(valid)} pct={pct:.1f}")


def print_report(report: dict, top_n: int = 30, player_no: int | None = None) -> None:
    """統合レポートを整形して表示する。player_no 指定時はその選手の詳細のみ表示。"""
    colorama_init(autoreset=True)
    table = report["table"]

    if player_no is not None:
        _print_player_detail(table, player_no)
        _print_overall(report)
        return

    top = table.head(top_n).reset_index(drop=True)
    float_cols = [c for c in top.columns if top[c].dtype.kind == "f"]
    formatters = {c: _fmt_float for c in float_cols}
    text = top.to_string(index=False, formatters=formatters)
    lines = text.splitlines()

    print(f"=== 総合レポート (上位{len(top)}件 / 全{len(table)}選手) ===")
    if lines:
        print(lines[0])
        for i, line in enumerate(lines[1:]):
            score = top.loc[i, "total_score"]
            if pd.isna(score) or score == 0:
                print(line)
            elif score > 0:
                print(Fore.GREEN + line + Style.RESET_ALL)
            else:
                print(Fore.RED + line + Style.RESET_ALL)

    _print_overall(report)
