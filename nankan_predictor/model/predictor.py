import logging

import numpy as np
import pandas as pd

from nankan_predictor.features.builder import NUMERIC_FEATURES
from nankan_predictor.model.registry import load_model

logger = logging.getLogger(__name__)


def _prepare_X(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for col in NUMERIC_FEATURES:
        if col not in df.columns:
            df[col] = np.nan
    return df[NUMERIC_FEATURES].astype(float)


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

    def predict_win_probs(self, X: pd.DataFrame) -> np.ndarray:
        return self.win_model.predict_proba(_prepare_X(X))[:, 1]

    def predict_place_probs(self, X: pd.DataFrame) -> np.ndarray:
        return self.place_model.predict_proba(_prepare_X(X))[:, 1]

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
