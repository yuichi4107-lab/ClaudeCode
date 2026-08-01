"""着順予想モデル: ランキング学習 → レース内確率化 → 2連単確率合成。

- 学習: LightGBM LGBMRanker(lambdarank, group=race_id)。関連度は
  relevance = max(0, 8 − finish_pos)(1着=7 … 8着以下・未完走=0)。
  LightGBM が無い環境では HistGradientBoostingRegressor(-finish_pos 回帰)に
  フォールバックする(スコアの意味は同じ「大きいほど上位」)。
- 勝率: レース内 softmax P(win_i) = exp(s_i/T) / Σ exp(s_j/T)。
  温度 T は検証データの1着対数尤度を最大化する値をグリッドで選ぶ。
- 2連単: Harville 近似 P(i→j) = P(i) × P(j) / (1 − P(i))。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from autorace_evaluator.model.features import FEATURE_COLS

logger = logging.getLogger(__name__)

MODEL_PATH = "data/models/autorace_rank_model.joblib"

_TEMPERATURE_GRID = np.concatenate([
    np.arange(0.2, 2.05, 0.1), np.arange(2.5, 6.5, 0.5)])


def make_relevance(finish_pos: pd.Series) -> np.ndarray:
    """着順 → lambdarank の関連度(1着=7 … 8着=0、未完走(NaN)=0)。"""
    pos = pd.to_numeric(finish_pos, errors="coerce")
    rel = (8 - pos).clip(lower=0)
    return rel.fillna(0).astype(int).to_numpy()


def _make_ranker():
    try:
        from lightgbm import LGBMRanker

        return LGBMRanker(
            objective="lambdarank",
            n_estimators=400,
            learning_rate=0.05,
            num_leaves=31,
            min_child_samples=30,
            random_state=0,
            verbosity=-1,
        ), "lightgbm"
    except ImportError:
        from sklearn.ensemble import HistGradientBoostingRegressor

        logger.warning("lightgbm 未インストール: HGBT回帰にフォールバックします")
        return HistGradientBoostingRegressor(random_state=0), "sklearn"


@dataclass
class RankModel:
    """学習済みランカー+確率化温度のコンテナ(joblib で保存)。"""

    model: object
    backend: str
    temperature: float = 1.0
    feature_cols: list = field(default_factory=lambda: list(FEATURE_COLS))

    def scores(self, feat_df: pd.DataFrame) -> np.ndarray:
        X = feat_df[self.feature_cols].to_numpy(dtype=float)
        return np.asarray(self.model.predict(X), dtype=float)

    def win_probabilities(self, feat_df: pd.DataFrame) -> pd.Series:
        """レース内 softmax による勝率(feat_df は race_id 列必須)。"""
        s = pd.Series(self.scores(feat_df), index=feat_df.index)
        return _softmax_by_race(s, feat_df["race_id"], self.temperature)


def _softmax_by_race(scores: pd.Series, race_ids: pd.Series,
                     temperature: float) -> pd.Series:
    z = scores / max(temperature, 1e-6)
    z = z - z.groupby(race_ids).transform("max")
    e = np.exp(z)
    return e / e.groupby(race_ids).transform("sum")


def _fit_temperature(scores: pd.Series, race_ids: pd.Series,
                     finish_pos: pd.Series) -> float:
    """1着馬(車)の対数尤度を最大化する softmax 温度を選ぶ。"""
    winners = pd.to_numeric(finish_pos, errors="coerce") == 1
    if winners.sum() == 0:
        return 1.0
    best_t, best_ll = 1.0, -np.inf
    for t in _TEMPERATURE_GRID:
        p = _softmax_by_race(scores, race_ids, float(t))
        ll = np.log(p[winners].clip(lower=1e-12)).sum()
        if ll > best_ll:
            best_t, best_ll = float(t), ll
    return best_t


def train(feat_df: pd.DataFrame, valid_frac: float = 0.15) -> RankModel:
    """特徴量表(features.build_features の出力+finish_pos)から学習する。

    直近 valid_frac のレース(日付順)を温度較正用に使い、モデル自体は
    全データで最終学習する(サンプル効率優先。ハイパラ探索はしない)。
    """
    df = feat_df.sort_values(["race_date", "race_id", "car_no"]).reset_index(drop=True)
    y = make_relevance(df["finish_pos"])
    X = df[list(FEATURE_COLS)].to_numpy(dtype=float)
    groups = df.groupby("race_id", sort=False).size().to_numpy()

    model, backend = _make_ranker()

    # 温度較正: 末尾 valid_frac レースを除いて学習 → 検証スコアで T を選ぶ
    race_order = df["race_id"].drop_duplicates().tolist()
    n_valid = max(int(len(race_order) * valid_frac), 30)
    if len(race_order) > n_valid * 2:
        valid_races = set(race_order[-n_valid:])
        tr = ~df["race_id"].isin(valid_races)
        Xt, yt = X[tr.to_numpy()], y[tr.to_numpy()]
        gt = df[tr].groupby("race_id", sort=False).size().to_numpy()
        cal_model, _ = _make_ranker()
        if backend == "lightgbm":
            cal_model.fit(Xt, yt, group=gt)
        else:
            cal_model.fit(Xt, yt)
        va = df[~tr]
        va_scores = pd.Series(
            np.asarray(cal_model.predict(X[(~tr).to_numpy()]), dtype=float),
            index=va.index)
        temperature = _fit_temperature(va_scores, va["race_id"], va["finish_pos"])
    else:
        temperature = 1.0

    if backend == "lightgbm":
        model.fit(X, y, group=groups)
    else:
        model.fit(X, y)

    logger.info("train done: backend=%s n=%d races=%d T=%.2f",
                backend, len(df), len(groups), temperature)
    return RankModel(model=model, backend=backend, temperature=temperature)


def save_model(rank_model: RankModel, path: str = MODEL_PATH) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(rank_model, p)


def load_model(path: str = MODEL_PATH) -> RankModel | None:
    p = Path(path)
    if not p.exists():
        return None
    return joblib.load(p)


# ------------------------------------------------------------ 2連単確率

def exacta_probabilities(win_probs: pd.DataFrame) -> pd.DataFrame:
    """勝率から Harville 近似で 2連単(1着i→2着j)確率を組む。

    win_probs: 列 [race_id, car_no, p_win] の DataFrame。
    返り値: [race_id, first, second, prob] を prob 降順(レース内)で返す。
    """
    rows = []
    for race_id, g in win_probs.groupby("race_id"):
        cars = g["car_no"].to_numpy()
        p = g["p_win"].to_numpy(dtype=float)
        for i in range(len(cars)):
            denom = 1.0 - p[i]
            if denom <= 0:
                continue
            for j in range(len(cars)):
                if i == j:
                    continue
                rows.append({
                    "race_id": race_id,
                    "first": int(cars[i]),
                    "second": int(cars[j]),
                    "prob": float(p[i] * p[j] / denom),
                })
    out = pd.DataFrame(rows, columns=["race_id", "first", "second", "prob"])
    if out.empty:
        return out
    return out.sort_values(["race_id", "prob"], ascending=[True, False]).reset_index(drop=True)
