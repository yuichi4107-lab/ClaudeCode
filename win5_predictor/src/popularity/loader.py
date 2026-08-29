"""WIN5 結果 CSV の読み込みユーティリティ。"""

from __future__ import annotations

from pathlib import Path
from typing import List, Tuple

import pandas as pd

POP_COLS = ["p1", "p2", "p3", "p4", "p5"]


def load_results(path: str | Path) -> pd.DataFrame:
    """WIN5 結果 CSV を読み込み、型を正規化して返す。

    `#` で始まる行はコメントとして無視する。
    payout_yen / hit_tickets / p1..p5 は数値化（空欄は NaN）。
    pops_verified は bool 化。
    """
    df = pd.read_csv(path, comment="#")
    df["payout_yen"] = pd.to_numeric(df["payout_yen"], errors="coerce")
    df["hit_tickets"] = pd.to_numeric(df["hit_tickets"], errors="coerce")
    for c in POP_COLS:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    if "pops_verified" in df.columns:
        df["pops_verified"] = (
            df["pops_verified"].astype(str).str.strip().str.lower().isin(["true", "1", "yes"])
        )
    else:
        df["pops_verified"] = False
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    return df.sort_values("date").reset_index(drop=True)


def _row_has_pops(row) -> bool:
    return all(pd.notna(row[c]) for c in POP_COLS)


def winning_popularities(df: pd.DataFrame, require_verified: bool = False) -> List[int]:
    """人気が全て揃っている回について、当選馬の人気を1次元リストで返す。

    各回 5 レース分なので、N 回ぶんで最大 5*N 個。
    """
    rows = df[df["pops_verified"]] if require_verified else df
    pops: List[int] = []
    for _, r in rows.iterrows():
        if _row_has_pops(r):
            pops.extend(int(r[c]) for c in POP_COLS)
    return pops


def rounds_with_pops(
    df: pd.DataFrame, require_verified: bool = False
) -> List[Tuple[pd.Timestamp, List[int]]]:
    """人気が揃っている回の (日付, [p1..p5]) のリストを返す。"""
    rows = df[df["pops_verified"]] if require_verified else df
    out: List[Tuple[pd.Timestamp, List[int]]] = []
    for _, r in rows.iterrows():
        if _row_has_pops(r):
            out.append((r["date"], [int(r[c]) for c in POP_COLS]))
    return out


def load_target_races(path: str | Path, beta: float = 1.0):
    """対象 5 レースの単勝オッズ CSV を読み込み、Race のリストを返す。

    CSV 列: race(1..5), umaban, odds, horse(任意), pop(任意=人気順)
    `#` 始まりはコメント。
    """
    from .odds import Horse, Race  # 遅延 import で循環回避

    df = pd.read_csv(path, comment="#")
    df["race"] = pd.to_numeric(df["race"], errors="coerce")
    df["umaban"] = pd.to_numeric(df["umaban"], errors="coerce")
    df["odds"] = pd.to_numeric(df["odds"], errors="coerce")
    if "pop" in df.columns:
        df["pop"] = pd.to_numeric(df["pop"], errors="coerce")
    races = []
    for race_no in sorted(df["race"].dropna().unique()):
        sub = df[df["race"] == race_no]
        horses = [
            Horse(
                umaban=int(r["umaban"]),
                odds=float(r["odds"]),
                name=str(r["horse"]) if "horse" in df.columns and pd.notna(r.get("horse")) else "",
                pop=(int(r["pop"]) if "pop" in df.columns and pd.notna(r.get("pop")) else None),
            )
            for _, r in sub.iterrows()
        ]
        races.append(Race(horses, beta=beta, name=f"R{int(race_no)}"))
    return races


def data_coverage(df: pd.DataFrame) -> dict:
    """データの埋まり具合を返す（人気が何回ぶん入っているか等）。"""
    n_total = len(df)
    n_pops = sum(_row_has_pops(r) for _, r in df.iterrows())
    n_verified = int(df["pops_verified"].sum())
    return {
        "rounds_total": n_total,
        "rounds_with_pops": n_pops,
        "rounds_verified": n_verified,
        "races_with_pops": n_pops * 5,
    }
