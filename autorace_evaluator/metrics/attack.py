"""突っ込み度: 前の車に日和らず突っ込めているかの統計プロキシ。

(a) 混戦時パフォーマンス: 試走タイム・ハンデから期待される着順との残差を
    「前に車がいる展開」(front_cars >= 1) に限定して集計。
    STを説明変数に入れないのは意図的 — スタートで稼ぐ成分ではなく
    「突っ込んで抜く」成分を残差に残すため。
(b) 重ハン時の追い抜き量: passed = 前にいた車数 − 先着された車数。
    後ろから差されるとマイナスに寄与するのは仕様(日和って抜かれる選手を
    低評価にする)。

参考指標として事故率・違反率も集計する。
"""

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler

from autorace_evaluator.config import settings
from autorace_evaluator.metrics.common import center_within_race, shrink, zscore

MIN_VALID_PER_RACE = 3


def add_front_cars(entries_df: pd.DataFrame) -> pd.DataFrame:
    """front_cars 列(自分よりハンデ位置が前=handicap が小さい車数、
    同ハンデは含めない、欠車除く)を追加して返す。"""
    df = entries_df.copy()
    df["front_cars"] = np.nan

    active = df["status"] != settings.STATUS_SCRATCHED
    for race_id, group in df[active & df["handicap"].notna()].groupby("race_id"):
        h = group["handicap"].to_numpy()
        front = (h[None, :] < h[:, None]).sum(axis=1)
        df.loc[group.index, "front_cars"] = front
    return df


def fit_expected_finish_model(entries_df: pd.DataFrame,
                              ridge_alpha: float = settings.RIDGE_ALPHA):
    """レース内センタリングした finish_pos ~ trial + handicap の Ridge を学習し、
    残差列 attack_residual を付けたサンプルdfと診断dictを返す。"""
    df = entries_df.copy()
    mask = (
        (df["track_status"] == settings.TRACK_GOOD)
        & (df["status"] == settings.STATUS_FINISHED)
        & df["finish_pos"].notna()
        & df["trial_time"].notna() & df["handicap"].notna()
        & df["player_no"].notna()
    )
    df = df[mask].copy()
    if df.empty:
        return df.assign(attack_residual=np.nan), {}

    counts = df.groupby("race_id")["car_no"].transform("size")
    df = df[counts >= MIN_VALID_PER_RACE]
    if df.empty:
        return df.assign(attack_residual=np.nan), {}

    df = center_within_race(df, ["finish_pos", "trial_time", "handicap"])
    X = df[["trial_time_c", "handicap_c"]].to_numpy(dtype=float)
    y = df["finish_pos_c"].to_numpy(dtype=float)

    scaler = StandardScaler()
    Xs = np.nan_to_num(scaler.fit_transform(X), nan=0.0, posinf=0.0, neginf=0.0)
    model = Ridge(alpha=ridge_alpha)
    model.fit(Xs, y)
    df["attack_residual"] = y - model.predict(Xs)

    scales = np.where(scaler.scale_ == 0, 1.0, scaler.scale_)
    diagnostics = {
        "n_samples": int(len(df)),
        "betas": dict(zip(["trial_time_c", "handicap_c"],
                          (model.coef_ / scales).tolist())),
    }
    return df, diagnostics


def compute_overtakes(entries_df: pd.DataFrame) -> pd.DataFrame:
    """自分が完走したレースについて passed = front_cars − 先着された車数 を計算。

    同着は「先着」に数えない。front_cars >= 1 のレースのみ返す。"""
    df = add_front_cars(entries_df)
    rows = []
    for race_id, group in df[df["status"] != settings.STATUS_SCRATCHED].groupby("race_id"):
        finished = group[(group["status"] == settings.STATUS_FINISHED)
                         & group["finish_pos"].notna()]
        pos = finished["finish_pos"].to_numpy()
        for idx, row in finished.iterrows():
            if pd.isna(row["front_cars"]) or row["front_cars"] < 1:
                continue
            finished_ahead = int((pos < row["finish_pos"]).sum())
            passed = int(row["front_cars"]) - finished_ahead
            rows.append({
                "race_id": race_id,
                "player_no": row["player_no"],
                "player_name": row["player_name"],
                "front_cars": int(row["front_cars"]),
                "finished_ahead": finished_ahead,
                "passed": passed,
                "pass_ratio": passed / row["front_cars"],
            })
    cols = ["race_id", "player_no", "player_name", "front_cars",
            "finished_ahead", "passed", "pass_ratio"]
    return pd.DataFrame(rows, columns=cols)


def compute_attack(entries_df: pd.DataFrame,
                   min_races: int = settings.MIN_RACES,
                   k: int = settings.SHRINKAGE_K):
    """選手別突っ込み度テーブルと診断情報を返す。

    Returns:
        per_player: player_no, player_name, n_attack_a, attack_a,
                    n_overtake, mean_passed, pass_rate, pass_rate_shrunk,
                    accident_rate, violation_rate, attack_score
        diagnostics: 期待着順モデルの係数等
    """
    df = add_front_cars(entries_df)
    df = df[df["player_no"].notna()]

    # (a) 混戦時パフォーマンス
    sample, diagnostics = fit_expected_finish_model(df)
    if not sample.empty:
        sample = sample[sample["front_cars"].fillna(0) >= 1]
    if sample.empty:
        attack_a = pd.DataFrame(columns=["player_no", "n_attack_a", "attack_a"])
    else:
        grouped = sample.groupby("player_no")["attack_residual"]
        attack_a = pd.DataFrame({
            "player_no": grouped.mean().index,
            "n_attack_a": grouped.size().to_numpy(),
            # 残差が負 = 期待より前で着 = プラス評価 → 符号反転して縮約
            "attack_a_raw": (-grouped.mean()).to_numpy(),
        })
        attack_a["attack_a"] = shrink(
            attack_a["attack_a_raw"], attack_a["n_attack_a"], k=k, center=0.0)

    # (b) 重ハン時の追い抜き量
    overtakes = compute_overtakes(df)
    if overtakes.empty:
        ot = pd.DataFrame(columns=["player_no", "n_overtake", "mean_passed", "pass_rate"])
    else:
        ot = overtakes.groupby("player_no").agg(
            n_overtake=("passed", "size"),
            mean_passed=("passed", "mean"),
            pass_rate=("pass_ratio", "mean"),
        ).reset_index()
        ot["pass_rate_shrunk"] = shrink(ot["pass_rate"], ot["n_overtake"], k=k, center=0.0)

    # 参考: 事故率・違反率(分母は欠車除く出走数)
    active = df[df["status"] != settings.STATUS_SCRATCHED]
    rates = active.groupby("player_no").agg(
        player_name=("player_name", "last"),
        n_races=("race_id", "size"),
        accident_rate=("status", lambda s: (s == settings.STATUS_ACCIDENT).mean()),
        violation_rate=("status", lambda s: (s == settings.STATUS_VIOLATION).mean()),
    ).reset_index()

    per_player = rates.merge(attack_a, on="player_no", how="left") \
                      .merge(ot, on="player_no", how="left")
    if per_player.empty:
        per_player["attack_score"] = np.nan
        return per_player, diagnostics

    eligible = (per_player[["n_attack_a", "n_overtake"]].fillna(0).max(axis=1)
                >= min_races)
    z_a = zscore(per_player["attack_a"].where(eligible))
    if "pass_rate_shrunk" not in per_player.columns:
        per_player["pass_rate_shrunk"] = np.nan
    z_b = zscore(per_player["pass_rate_shrunk"].where(eligible))
    score = pd.concat([z_a, z_b], axis=1).mean(axis=1)
    per_player["attack_score"] = np.where(eligible, score, np.nan)
    return per_player, diagnostics
