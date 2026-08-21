"""人気ベースライン: P(win | 人気順) を学習データから推定し各馬へ付与する。

機械学習モデルがOOSでこのベースラインを上回れるかが採用可否の判断基準。
内部で popularity.model.PopularityModel（1着馬がk番人気である確率）を使う。
"""

import numpy as np
import pandas as pd

from popularity.model import PopularityModel


class PopularityBaseline:
    def __init__(self, max_rank: int = 18):
        self.model = PopularityModel(max_rank=max_rank)

    def fit(self, train_df: pd.DataFrame, pop_col: str = "popularity",
            target_col: str = "target") -> "PopularityBaseline":
        winners = train_df[train_df[target_col] == 1.0]
        pops = [int(p) for p in winners[pop_col].dropna().tolist()]
        self.model.fit(pops)
        return self

    def predict(self, df: pd.DataFrame, pop_col: str = "popularity") -> np.ndarray:
        out = []
        for p in df[pop_col].tolist():
            if pd.isna(p):
                out.append(0.0)
            else:
                out.append(float(self.model.win_prob(int(p))))
        return np.asarray(out)
