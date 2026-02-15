import logging
from itertools import combinations

import numpy as np
import pandas as pd

from jra_predictor.features.builder import NUMERIC_FEATURES
from jra_predictor.model.registry import load_model, load_meta

logger = logging.getLogger(__name__)


def _fill_and_select(df: pd.DataFrame, features: list[str]) -> pd.DataFrame:
    df = df.copy()
    for col in features:
        if col not in df.columns:
            df[col] = np.nan
    return df[features].astype(float)


def _extract_feature_names_from_model(model) -> list[str] | None:
    """
    Try to extract actual feature_names_in_ from fitted model.
    Searches through Pipeline, CalibratedClassifierCV, and other wrapper layers.
    """
    if hasattr(model, "feature_names_in_"):
        return list(getattr(model, "feature_names_in_"))

    for attr in ("estimator_", "base_estimator_", "named_steps", "steps"):
        if not hasattr(model, attr):
            continue
        try:
            inner = getattr(model, attr)
        except Exception:
            continue

        if hasattr(inner, "feature_names_in_"):
            return list(getattr(inner, "feature_names_in_"))

        if isinstance(inner, dict):
            for v in inner.values():
                if hasattr(v, "feature_names_in_"):
                    return list(getattr(v, "feature_names_in_"))

        if isinstance(inner, (list, tuple)):
            for item in inner:
                est = item[1] if isinstance(item, (list, tuple)) and len(item) > 1 else item
                if hasattr(est, "feature_names_in_"):
                    return list(getattr(est, "feature_names_in_"))

    return None


class ModelPredictor:
    """
    馬単・三連複予想のためのマルチモデルプレディクター。

    馬単 (exacta):
      - win_model:   P(1着) を予測
      - place_model: P(2着) を予測
      - P(i→j) ≈ P_win(i) * P_place(j) / (1 - P_win(i))

    三連複 (trio):
      - top3_model:  P(3着以内) を予測
      - P(i,j,k) ≈ P_top3(i) * P_top3(j) * P_top3(k)  (順不同)
    """

    def __init__(self, model_name: str = "jra_v1", bet_types: list[str] = None):
        self.model_name = model_name
        bet_types = bet_types or ["exacta", "trio"]

        # 馬単用モデル
        if "exacta" in bet_types:
            self.win_model = load_model(f"{model_name}_win")
            self.place_model = load_model(f"{model_name}_place")
            win_meta = load_meta(f"{model_name}_win")
            place_meta = load_meta(f"{model_name}_place")
            self.win_features = (
                _extract_feature_names_from_model(self.win_model)
                or win_meta.get("features", NUMERIC_FEATURES)
            )
            self.place_features = (
                _extract_feature_names_from_model(self.place_model)
                or place_meta.get("features", NUMERIC_FEATURES)
            )
        else:
            self.win_model = None
            self.place_model = None

        # 三連複用モデル
        if "trio" in bet_types:
            self.top3_model = load_model(f"{model_name}_top3")
            top3_meta = load_meta(f"{model_name}_top3")
            self.top3_features = (
                _extract_feature_names_from_model(self.top3_model)
                or top3_meta.get("features", NUMERIC_FEATURES)
            )
        else:
            self.top3_model = None

    def predict_win_probs(self, X: pd.DataFrame) -> np.ndarray:
        Xf = _fill_and_select(X, self.win_features)
        return self.win_model.predict_proba(Xf)[:, 1]

    def predict_place_probs(self, X: pd.DataFrame) -> np.ndarray:
        Xf = _fill_and_select(X, self.place_features)
        return self.place_model.predict_proba(Xf)[:, 1]

    def predict_top3_probs(self, X: pd.DataFrame) -> np.ndarray:
        Xf = _fill_and_select(X, self.top3_features)
        return self.top3_model.predict_proba(Xf)[:, 1]

    # ---------------------------------------------------------------- 馬単

    def predict_exacta(
        self, entries_df: pd.DataFrame, top_n: int = 5
    ) -> pd.DataFrame:
        """
        全 (1着, 2着) 組み合わせの確率を計算し、上位 top_n 件を返す。
        """
        win_probs = self.predict_win_probs(entries_df)
        place_probs = self.predict_place_probs(entries_df)

        n = len(entries_df)
        combos = []
        for i in range(n):
            p_win_i = win_probs[i]
            denom = max(1 - p_win_i, 1e-6)
            for j in range(n):
                if i == j:
                    continue
                prob = p_win_i * place_probs[j] / denom
                combos.append(
                    {
                        "first_horse_number": entries_df.iloc[i].get("horse_number"),
                        "first_horse_name": entries_df.iloc[i].get("horse_name", ""),
                        "first_win_prob": round(p_win_i, 4),
                        "second_horse_number": entries_df.iloc[j].get("horse_number"),
                        "second_horse_name": entries_df.iloc[j].get("horse_name", ""),
                        "second_place_prob": round(place_probs[j], 4),
                        "exacta_prob": round(prob, 6),
                    }
                )

        result = (
            pd.DataFrame(combos)
            .sort_values("exacta_prob", ascending=False)
            .head(top_n)
            .reset_index(drop=True)
        )
        result.index += 1
        return result

    # ---------------------------------------------------------------- 三連複

    def predict_trio(
        self, entries_df: pd.DataFrame, top_n: int = 5
    ) -> pd.DataFrame:
        """
        3頭の3着以内組み合わせ（順不同）の確率を計算し、上位 top_n 件を返す。

        三連複確率の近似:
            P(i,j,k all in top3) ≈ P_top3(i) * P_top3(j) * P_top3(k)
        """
        top3_probs = self.predict_top3_probs(entries_df)

        n = len(entries_df)
        combos = []
        for i, j, k in combinations(range(n), 3):
            prob = top3_probs[i] * top3_probs[j] * top3_probs[k]
            combos.append(
                {
                    "horse1_number": entries_df.iloc[i].get("horse_number"),
                    "horse1_name": entries_df.iloc[i].get("horse_name", ""),
                    "horse1_top3_prob": round(top3_probs[i], 4),
                    "horse2_number": entries_df.iloc[j].get("horse_number"),
                    "horse2_name": entries_df.iloc[j].get("horse_name", ""),
                    "horse2_top3_prob": round(top3_probs[j], 4),
                    "horse3_number": entries_df.iloc[k].get("horse_number"),
                    "horse3_name": entries_df.iloc[k].get("horse_name", ""),
                    "horse3_top3_prob": round(top3_probs[k], 4),
                    "trio_prob": round(prob, 6),
                }
            )

        result = (
            pd.DataFrame(combos)
            .sort_values("trio_prob", ascending=False)
            .head(top_n)
            .reset_index(drop=True)
        )
        result.index += 1
        return result

    # ----------------------------------------------------------- 三連複ボックス

    def predict_trio_box(
        self, entries_df: pd.DataFrame, box_size: int = 4
    ) -> dict:
        """
        P(3着以内) 上位 box_size 頭を選び、その全組み合わせをボックス購入する。

        4頭ボックス: C(4,3) =  4 点
        5頭ボックス: C(5,3) = 10 点

        Returns dict:
            selected_horses: list[dict]  - 選出馬 (馬番, 馬名, P_top3)
            box_combos: pd.DataFrame     - 購入する全組み合わせ
            n_tickets: int               - 購入点数
        """
        top3_probs = self.predict_top3_probs(entries_df)

        # P(top3) でソートし上位 box_size 頭を選出
        indices = np.argsort(top3_probs)[::-1][:box_size]
        indices = sorted(indices)  # 馬番順に並べ直す

        selected_horses = []
        for idx in indices:
            selected_horses.append({
                "horse_number": entries_df.iloc[idx].get("horse_number"),
                "horse_name": entries_df.iloc[idx].get("horse_name", ""),
                "top3_prob": round(top3_probs[idx], 4),
            })

        # 選出馬の全3頭組み合わせ
        combos = []
        for ci, cj, ck in combinations(range(len(indices)), 3):
            i, j, k = indices[ci], indices[cj], indices[ck]
            prob = top3_probs[i] * top3_probs[j] * top3_probs[k]
            combos.append({
                "horse1_number": entries_df.iloc[i].get("horse_number"),
                "horse1_name": entries_df.iloc[i].get("horse_name", ""),
                "horse2_number": entries_df.iloc[j].get("horse_number"),
                "horse2_name": entries_df.iloc[j].get("horse_name", ""),
                "horse3_number": entries_df.iloc[k].get("horse_number"),
                "horse3_name": entries_df.iloc[k].get("horse_name", ""),
                "trio_prob": round(prob, 6),
            })

        box_df = pd.DataFrame(combos)
        if not box_df.empty:
            box_df = box_df.sort_values("trio_prob", ascending=False).reset_index(drop=True)
            box_df.index += 1

        return {
            "selected_horses": selected_horses,
            "box_combos": box_df,
            "n_tickets": len(combos),
            "box_size": box_size,
        }
