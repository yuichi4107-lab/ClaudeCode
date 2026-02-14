import logging

import numpy as np
import pandas as pd

from nankan_predictor.features.builder import NUMERIC_FEATURES
from nankan_predictor.model.registry import load_model, load_meta

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

    # Search common wrapper attributes
    for attr in ("estimator_", "base_estimator_", "named_steps", "steps"):
        if not hasattr(model, attr):
            continue
        try:
            inner = getattr(model, attr)
        except Exception:
            continue
        
        # Check if inner has feature_names_in_
        if hasattr(inner, "feature_names_in_"):
            return list(getattr(inner, "feature_names_in_"))
        
        # If it's a dict (named_steps), search values
        if isinstance(inner, dict):
            for v in inner.values():
                if hasattr(v, "feature_names_in_"):
                    return list(getattr(v, "feature_names_in_"))
        
        # If it's a list/tuple (steps), each is (name, estimator)
        if isinstance(inner, (list, tuple)):
            for item in inner:
                est = item[1] if isinstance(item, (list, tuple)) and len(item) > 1 else item
                if hasattr(est, "feature_names_in_"):
                    return list(getattr(est, "feature_names_in_"))
    
    return None


class ModelPredictor:
    """
    馬単予想のための2モデルプレディクター。
    - win_model:   P(1着) を予測
    - place_model: P(2着) を予測

    馬単確率の近似:
        P(i→j) ≈ P_win(i) * P_place(j) / (1 - P_win(i))
    分母で「iが1着のとき残りの馬でjが2着になる確率」を近似する。
    """

    def __init__(self, model_name: str = "nankan_v1"):
        self.win_model = load_model(f"{model_name}_win")
        self.place_model = load_model(f"{model_name}_place")
        self.model_name = model_name
        win_meta = load_meta(f"{model_name}_win")
        place_meta = load_meta(f"{model_name}_place")
        # Prefer features extracted from the fitted model (robust), fallback to meta then global list
        win_features = _extract_feature_names_from_model(self.win_model)
        place_features = _extract_feature_names_from_model(self.place_model)
        self.win_features = win_features or win_meta.get("features", NUMERIC_FEATURES)
        self.place_features = place_features or place_meta.get("features", NUMERIC_FEATURES)

    def predict_win_probs(self, X: pd.DataFrame) -> np.ndarray:
        Xf = _fill_and_select(X, self.win_features)
        return self.win_model.predict_proba(Xf)[:, 1]

    def predict_place_probs(self, X: pd.DataFrame) -> np.ndarray:
        Xf = _fill_and_select(X, self.place_features)
        return self.place_model.predict_proba(Xf)[:, 1]

    def predict_exacta(
        self, entries_df: pd.DataFrame, top_n: int = 5
    ) -> pd.DataFrame:
        """
        全 (1着, 2着) 組み合わせの確率を計算し、上位 top_n 件を返す。

        Returns DataFrame:
            first_horse_number, first_horse_name,
            second_horse_number, second_horse_name,
            exacta_prob
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
                # P(i→j) ≈ P_win(i) * P_place(j) / (1 - P_win(i))
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
