"""WIN5 当選馬の傾向クロス集計。

- 横軸: 人気順バケット（1-3 / 4-6 / 7-9 / 10人気〜）
- 縦軸: 単勝オッズバケット（〜5倍 / 〜10倍 / 〜20倍 / 20倍〜）※オッズがある場合
- レース順（1〜5レース目）ごとの堅さ／荒れ傾向

人気順は p1..p5（1〜5レース目）として CSV に入っている。オッズは o1..o5 があれば使う。
"""

from __future__ import annotations

from typing import List, Optional

import numpy as np
import pandas as pd

POP_BUCKETS = ["1-3人気", "4-6人気", "7-9人気", "10人気〜"]
ODDS_BUCKETS = ["〜5倍", "5-10倍", "10-20倍", "20倍〜"]
POS_COLS = ["p1", "p2", "p3", "p4", "p5"]
ODDS_COLS = ["o1", "o2", "o3", "o4", "o5"]


def pop_bucket(rank: float) -> Optional[str]:
    if pd.isna(rank):
        return None
    r = int(rank)
    if r <= 3:
        return POP_BUCKETS[0]
    if r <= 6:
        return POP_BUCKETS[1]
    if r <= 9:
        return POP_BUCKETS[2]
    return POP_BUCKETS[3]


def odds_bucket(odds: float) -> Optional[str]:
    if pd.isna(odds):
        return None
    o = float(odds)
    if o < 5:
        return ODDS_BUCKETS[0]
    if o < 10:
        return ODDS_BUCKETS[1]
    if o < 20:
        return ODDS_BUCKETS[2]
    return ODDS_BUCKETS[3]


def _long_form(df: pd.DataFrame) -> pd.DataFrame:
    """各 (回, レース順) を1行に展開した縦持ちを返す。列: race_pos, pop, pop_bucket, odds, odds_bucket。"""
    has_odds = all(c in df.columns for c in ODDS_COLS)
    recs = []
    for _, row in df.iterrows():
        for i, pc in enumerate(POS_COLS, start=1):
            rank = row[pc]
            if pd.isna(rank):
                continue
            rec = {
                "race_pos": i,
                "pop": int(rank),
                "pop_bucket": pop_bucket(rank),
            }
            if has_odds:
                od = row[ODDS_COLS[i - 1]]
                rec["odds"] = float(od) if pd.notna(od) else np.nan
                rec["odds_bucket"] = odds_bucket(od)
            recs.append(rec)
    return pd.DataFrame(recs)


def position_by_popbucket(df: pd.DataFrame, normalize: bool = False) -> pd.DataFrame:
    """行=レース順(1〜5)、列=人気バケットのクロス集計（件数 or 行方向%）。"""
    lf = _long_form(df)
    ct = pd.crosstab(lf["race_pos"], lf["pop_bucket"])
    ct = ct.reindex(columns=POP_BUCKETS, fill_value=0)
    ct.index = [f"{i}R目" for i in ct.index]
    if normalize:
        ct = ct.div(ct.sum(axis=1), axis=0) * 100
    return ct


def position_summary(df: pd.DataFrame) -> pd.DataFrame:
    """レース順ごとの堅さ指標。"""
    lf = _long_form(df)
    rows = []
    for pos in range(1, 6):
        sub = lf[lf["race_pos"] == pos]
        n = len(sub)
        fav = (sub["pop"] <= 3).sum()
        rows.append(
            {
                "レース順": f"{pos}R目",
                "n": n,
                "1-3人気%": fav / n * 100 if n else np.nan,
                "平均人気": sub["pop"].mean() if n else np.nan,
                "中央人気": sub["pop"].median() if n else np.nan,
                "最大人気": int(sub["pop"].max()) if n else np.nan,
            }
        )
    out = pd.DataFrame(rows)
    return out


def odds_by_pop_crosstab(df: pd.DataFrame) -> Optional[pd.DataFrame]:
    """縦=オッズバケット、横=人気バケットの2次元集計。オッズ列が無ければ None。"""
    if not all(c in df.columns for c in ODDS_COLS):
        return None
    lf = _long_form(df)
    if "odds_bucket" not in lf.columns or lf["odds_bucket"].isna().all():
        return None
    ct = pd.crosstab(lf["odds_bucket"], lf["pop_bucket"])
    return ct.reindex(index=ODDS_BUCKETS, columns=POP_BUCKETS, fill_value=0)


def favorites_per_week(df: pd.DataFrame, thresh: int = 3) -> pd.Series:
    """1回(5レース)あたり『thresh番人気以内の勝ち馬』が何頭出たかの分布。"""
    counts = []
    for _, row in df.iterrows():
        ranks = [row[c] for c in POS_COLS]
        if any(pd.isna(ranks)):
            continue
        counts.append(int(sum(1 for r in ranks if r <= thresh)))
    s = pd.Series(counts).value_counts().sort_index()
    s.index = [f"{k}頭" for k in s.index]
    return s
