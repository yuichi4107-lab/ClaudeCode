"""人気が無くても出せるメタ分析（配当・難易度・キャリーオーバー）。"""

from __future__ import annotations

import numpy as np
import pandas as pd


def payout_summary(df: pd.DataFrame) -> dict:
    """払戻金の要約統計（不的中=払戻 NaN は除外）。"""
    pay = df["payout_yen"].dropna()
    return {
        "n": int(pay.shape[0]),
        "min": float(pay.min()) if len(pay) else float("nan"),
        "median": float(pay.median()) if len(pay) else float("nan"),
        "mean": float(pay.mean()) if len(pay) else float("nan"),
        "max": float(pay.max()) if len(pay) else float("nan"),
    }


def ticket_summary(df: pd.DataFrame) -> dict:
    tk = df["hit_tickets"].dropna()
    return {
        "n": int(tk.shape[0]),
        "min": float(tk.min()) if len(tk) else float("nan"),
        "median": float(tk.median()) if len(tk) else float("nan"),
        "mean": float(tk.mean()) if len(tk) else float("nan"),
        "max": float(tk.max()) if len(tk) else float("nan"),
    }


def carryover_rounds(df: pd.DataFrame) -> pd.DataFrame:
    """不的中（票数 0 もしくは払戻欠損）の回 = キャリーオーバー発生回。"""
    mask = (df["hit_tickets"].fillna(0) == 0) | df["payout_yen"].isna()
    return df[mask][["date", "race", "grade", "payout_yen", "hit_tickets"]]


def difficulty_correlation(df: pd.DataFrame) -> dict:
    """log(払戻) と log(的中票数) の相関。票数が少ない回ほど高配当（難）という関係を確認。"""
    sub = df.dropna(subset=["payout_yen", "hit_tickets"])
    sub = sub[(sub["payout_yen"] > 0) & (sub["hit_tickets"] > 0)]
    if len(sub) < 3:
        return {"n": len(sub), "corr_log": float("nan")}
    lp = np.log(sub["payout_yen"].to_numpy())
    lt = np.log(sub["hit_tickets"].to_numpy())
    corr = float(np.corrcoef(lp, lt)[0, 1])
    return {"n": int(len(sub)), "corr_log": corr}


def grade_counts(df: pd.DataFrame) -> pd.Series:
    return df["grade"].value_counts()
