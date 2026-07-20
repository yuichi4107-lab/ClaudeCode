"""新人(デビュー直後)選手の2級車成績指標。

2級車期間 = bike_class == "2級車" の出走行(全選手が2級車でデビューし、
昇級で1級車に乗り換えるため、新人期間の操作的定義として最も頑健)。

新人ロースターは次のいずれかを満たす選手:
- graduation_code がデータ内最大値から settings.ROOKIE_RECENT_TERMS 期以内
  (期別が取れているときの正攻法)
- DB内初出走から settings.ROOKIE_MAX_RACES 走以内
  (DBが1年分しかない現状で期別欠損に対する防御)
判定根拠は definition 列に残す。

指標:
- rookie_attack: 全選手・良走路で fit 済みの期待着順残差
  (attack.fit_expected_finish_model)を新人×2級車行に絞って平均→符号反転→縮約。
  新人の少数サンプルで fit し直さない(安定性・既存関数の再利用)
- mean_st_rookie / st_gap_vs_field: 2級車行の平均STと全体平均STとの差
- trial_trend: 出走順に並べた試走タイムの回帰傾き(負 = 機材・乗り手が
  仕上がってきている)。整備力の前日ペアは新人には母数不足のための代替
- rookie_score: 新人母集団内の zscore(rookie_attack, -st)の平均

母集団が小さいため本表(report.build_report)には混ぜず、別レポート
(build_rookie_report → 別CSV)として出力する。
"""

import numpy as np
import pandas as pd

from autorace_evaluator.config import settings
from autorace_evaluator.metrics.attack import fit_expected_finish_model
from autorace_evaluator.metrics.common import shrink, zscore

ROOKIE_BIKE_CLASS = "2級車"

COLUMN_ORDER = [
    "player_no", "player_name", "rookie_score", "definition",
    "graduation_code", "age", "n_rookie", "first_date", "last_date",
    "win_rate", "top3_rate", "rookie_attack", "n_attack",
    "mean_st_rookie", "st_gap_vs_field", "trial_trend",
]


def _has_program_data(entries_df: pd.DataFrame) -> bool:
    return (
        "bike_class" in entries_df.columns
        and entries_df["bike_class"].notna().any()
    )


def rookie_roster(entries_df: pd.DataFrame,
                  recent_terms: int = settings.ROOKIE_RECENT_TERMS,
                  max_debut_races: int = settings.ROOKIE_MAX_RACES) -> pd.DataFrame:
    """新人判定。player_no, graduation_code, first_date, n_career_rows,
    definition(term/debut/term+debut)を返す。Program未収集なら空DF。"""
    cols = ["player_no", "graduation_code", "first_date", "n_career_rows",
            "definition"]
    if not _has_program_data(entries_df):
        return pd.DataFrame(columns=cols)

    df = entries_df[entries_df["player_no"].notna()].copy()
    grad = (
        df.dropna(subset=["graduation_code"])
        .groupby("player_no")["graduation_code"].max()
    )
    career = df.groupby("player_no").agg(
        first_date=("race_date", "min"),
        n_career_rows=("race_id", "size"),
    )

    max_term = grad.max() if not grad.empty else None
    rows = []
    for player_no, c in career.iterrows():
        g = grad.get(player_no)
        by_term = (
            max_term is not None and pd.notna(g)
            and g >= max_term - recent_terms
        )
        by_debut = c["n_career_rows"] <= max_debut_races
        if not (by_term or by_debut):
            continue
        definition = "+".join(
            [d for d, hit in (("term", by_term), ("debut", by_debut)) if hit])
        rows.append({
            "player_no": player_no,
            "graduation_code": g if pd.notna(g) else None,
            "first_date": c["first_date"],
            "n_career_rows": int(c["n_career_rows"]),
            "definition": definition,
        })
    return pd.DataFrame(rows, columns=cols)


def compute_rookie(entries_df: pd.DataFrame,
                   min_races: int = settings.ROOKIE_MIN_RACES,
                   k: int = settings.ROOKIE_SHRINKAGE_K):
    """新人×2級車期間の成績指標テーブルと診断情報を返す。"""
    empty = pd.DataFrame(columns=COLUMN_ORDER)
    if not _has_program_data(entries_df):
        return empty, {}

    roster = rookie_roster(entries_df)
    if roster.empty:
        return empty, {}

    df = entries_df[entries_df["player_no"].notna()].copy()
    rookie_rows = df[
        df["player_no"].isin(roster["player_no"])
        & (df["bike_class"] == ROOKIE_BIKE_CLASS)
        & (df["status"] != settings.STATUS_SCRATCHED)
    ].copy()
    if rookie_rows.empty:
        return empty, {}
    if "age" not in rookie_rows.columns:
        rookie_rows["age"] = np.nan

    # 基本成績(2級車行ベース)
    base = rookie_rows.groupby("player_no").agg(
        player_name=("player_name", "last"),
        age=("age", "last"),
        n_rookie=("race_id", "size"),
        first_date=("race_date", "min"),
        last_date=("race_date", "max"),
        win_rate=("finish_pos", lambda s: (s == 1).mean()),
        top3_rate=("finish_pos", lambda s: (s <= 3).mean()),
    ).reset_index()

    # 期待着順残差(全選手・良走路で fit → 新人×2級車行に絞る)
    sample, diagnostics = fit_expected_finish_model(df)
    if sample.empty:
        attack = pd.DataFrame(columns=["player_no", "n_attack", "rookie_attack"])
    else:
        rookie_sample = sample[
            sample["player_no"].isin(roster["player_no"])
            & (sample["bike_class"] == ROOKIE_BIKE_CLASS)
        ] if "bike_class" in sample.columns else sample.iloc[0:0]
        if rookie_sample.empty:
            attack = pd.DataFrame(columns=["player_no", "n_attack", "rookie_attack"])
        else:
            grouped = rookie_sample.groupby("player_no")["attack_residual"]
            attack = pd.DataFrame({
                "player_no": grouped.mean().index,
                "n_attack": grouped.size().to_numpy(),
                "attack_raw": (-grouped.mean()).to_numpy(),
            })
            attack["rookie_attack"] = shrink(
                attack["attack_raw"], attack["n_attack"], k=k, center=0.0)
            attack = attack[["player_no", "n_attack", "rookie_attack"]]

    # ST: 2級車行の平均を全体平均へ縮約
    field_st = df.loc[df["status"] != settings.STATUS_SCRATCHED, "st"].dropna().mean()
    st = rookie_rows.dropna(subset=["st"]).groupby("player_no").agg(
        n_st=("st", "size"), mean_st_raw=("st", "mean")).reset_index()
    if not st.empty:
        st["mean_st_rookie"] = shrink(
            st["mean_st_raw"], st["n_st"], k=k, center=field_st)
        st["st_gap_vs_field"] = st["mean_st_rookie"] - field_st
        st = st[["player_no", "mean_st_rookie", "st_gap_vs_field"]]
    else:
        st = pd.DataFrame(columns=["player_no", "mean_st_rookie", "st_gap_vs_field"])

    # 試走タイム推移の傾き(日付・レース番号順、n>=min_races)
    trends = []
    for player_no, g in rookie_rows.dropna(subset=["trial_time"]).groupby("player_no"):
        g = g.sort_values(["race_date", "race_no"])
        if len(g) < min_races:
            continue
        slope = float(np.polyfit(np.arange(len(g)), g["trial_time"].to_numpy(), 1)[0])
        trends.append({"player_no": player_no, "trial_trend": slope})
    trend = pd.DataFrame(trends, columns=["player_no", "trial_trend"])

    per_player = (
        base.merge(roster[["player_no", "graduation_code", "definition"]],
                   on="player_no", how="left")
            .merge(attack, on="player_no", how="left")
            .merge(st, on="player_no", how="left")
            .merge(trend, on="player_no", how="left")
    )

    eligible = per_player["n_rookie"] >= min_races
    z_attack = zscore(per_player["rookie_attack"].where(eligible))
    z_st = zscore((-per_player["mean_st_rookie"]).where(eligible))
    score = pd.concat([z_attack, z_st], axis=1).mean(axis=1)
    per_player["rookie_score"] = np.where(eligible, score, np.nan)

    for c in COLUMN_ORDER:
        if c not in per_player.columns:
            per_player[c] = np.nan
    per_player = per_player[COLUMN_ORDER].sort_values(
        "rookie_score", ascending=False, na_position="last").reset_index(drop=True)

    return per_player, diagnostics


def build_rookie_report(entries_df: pd.DataFrame) -> dict:
    """report.build_report と同じ形({"table": ..., "diagnostics": ...})を返す。"""
    table, diagnostics = compute_rookie(entries_df)
    return {"table": table, "diagnostics": diagnostics}
