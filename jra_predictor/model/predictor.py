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
    result = df[features].astype(float)
    result.columns = features  # feature name を明示的に保持
    return result


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
    馬連・三連複予想のためのマルチモデルプレディクター。

    馬連 (quinella):
      - win_model:   P(1着) を予測
      - place_model: P(2着) を予測
      - P(i,j) ≈ P_win(i)*P_place(j)/(1-P_win(i)) + P_win(j)*P_place(i)/(1-P_win(j))  (順不同)

    三連複 (trio):
      - top3_model:  P(3着以内) を予測
      - P(i,j,k) ≈ P_top3(i) * P_top3(j) * P_top3(k)  (順不同)
    """

    def __init__(self, model_name: str = "jra_v1", bet_types: list[str] = None):
        self.model_name = model_name
        bet_types = bet_types or ["quinella", "trio"]

        # 馬連用モデル
        if "quinella" in bet_types:
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

        # 三連複・ワイド用モデル
        if "trio" in bet_types or "wide" in bet_types:
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

    # ---------------------------------------------------------------- 馬連

    def predict_quinella(
        self, entries_df: pd.DataFrame, top_n: int = 5
    ) -> pd.DataFrame:
        """
        全 (i, j) 順不同組み合わせの確率を計算し、上位 top_n 件を返す。
        P(i,j) ≈ P_win(i)*P_place(j)/(1-P_win(i)) + P_win(j)*P_place(i)/(1-P_win(j))
        """
        win_probs = self.predict_win_probs(entries_df)
        place_probs = self.predict_place_probs(entries_df)

        n = len(entries_df)
        combos = []
        for i, j in combinations(range(n), 2):
            p_win_i = win_probs[i]
            p_win_j = win_probs[j]
            denom_i = max(1 - p_win_i, 1e-6)
            denom_j = max(1 - p_win_j, 1e-6)
            # 順不同: i→j の確率 + j→i の確率
            prob = (p_win_i * place_probs[j] / denom_i
                    + p_win_j * place_probs[i] / denom_j)
            combos.append(
                {
                    "horse1_number": entries_df.iloc[i].get("horse_number"),
                    "horse1_name": entries_df.iloc[i].get("horse_name", ""),
                    "horse1_win_prob": round(p_win_i, 4),
                    "horse2_number": entries_df.iloc[j].get("horse_number"),
                    "horse2_name": entries_df.iloc[j].get("horse_name", ""),
                    "horse2_win_prob": round(p_win_j, 4),
                    "quinella_prob": round(prob, 6),
                }
            )

        result = (
            pd.DataFrame(combos)
            .sort_values("quinella_prob", ascending=False)
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

    # ----------------------------------------------------------- 馬連ボックス

    def predict_quinella_box(
        self, entries_df: pd.DataFrame, box_size: int = 3
    ) -> dict:
        """
        P(win) + P(place) のスコア上位 box_size 頭を選び、
        その全2頭組み合わせを馬連ボックス購入する。

        3頭ボックス: C(3,2) =  3 点
        4頭ボックス: C(4,2) =  6 点
        5頭ボックス: C(5,2) = 10 点

        Returns dict:
            selected_horses: list[dict]  - 選出馬 (馬番, 馬名, win_prob, place_prob, score)
            box_combos: pd.DataFrame     - 購入する全組み合わせ
            n_tickets: int               - 購入点数
        """
        win_probs = self.predict_win_probs(entries_df)
        place_probs = self.predict_place_probs(entries_df)

        # 選出スコア: P(win) + P(place) で総合力を評価
        scores = win_probs + place_probs

        # スコア上位 box_size 頭を選出
        indices = np.argsort(scores)[::-1][:box_size]
        indices = sorted(indices)  # 馬番順に並べ直す

        selected_horses = []
        for idx in indices:
            selected_horses.append({
                "horse_number": entries_df.iloc[idx].get("horse_number"),
                "horse_name": entries_df.iloc[idx].get("horse_name", ""),
                "win_prob": round(float(win_probs[idx]), 4),
                "place_prob": round(float(place_probs[idx]), 4),
                "score": round(float(scores[idx]), 4),
            })

        # 選出馬の全2頭組み合わせ
        combos = []
        for ci, cj in combinations(range(len(indices)), 2):
            i, j = indices[ci], indices[cj]
            p_win_i = win_probs[i]
            p_win_j = win_probs[j]
            denom_i = max(1 - p_win_i, 1e-6)
            denom_j = max(1 - p_win_j, 1e-6)
            prob = (p_win_i * place_probs[j] / denom_i
                    + p_win_j * place_probs[i] / denom_j)
            combos.append({
                "horse1_number": entries_df.iloc[i].get("horse_number"),
                "horse1_name": entries_df.iloc[i].get("horse_name", ""),
                "horse2_number": entries_df.iloc[j].get("horse_number"),
                "horse2_name": entries_df.iloc[j].get("horse_name", ""),
                "quinella_prob": round(float(prob), 6),
            })

        box_df = pd.DataFrame(combos)
        if not box_df.empty:
            box_df = box_df.sort_values("quinella_prob", ascending=False).reset_index(drop=True)
            box_df.index += 1

        return {
            "selected_horses": selected_horses,
            "box_combos": box_df,
            "n_tickets": len(combos),
            "box_size": box_size,
        }

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

    # ----------------------------------------------------------- ワイド

    def predict_wide(
        self, entries_df: pd.DataFrame, top_n: int = 5
    ) -> pd.DataFrame:
        """
        ワイド（2頭が共に3着以内）の確率を計算し、上位 top_n 件を返す。
        P_wide(i,j) ≈ P_top3(i) * P_top3(j)
        """
        top3_probs = self.predict_top3_probs(entries_df)

        n = len(entries_df)
        combos = []
        for i, j in combinations(range(n), 2):
            prob = top3_probs[i] * top3_probs[j]
            combos.append({
                "horse1_number": entries_df.iloc[i].get("horse_number"),
                "horse1_name": entries_df.iloc[i].get("horse_name", ""),
                "horse1_top3_prob": round(top3_probs[i], 4),
                "horse2_number": entries_df.iloc[j].get("horse_number"),
                "horse2_name": entries_df.iloc[j].get("horse_name", ""),
                "horse2_top3_prob": round(top3_probs[j], 4),
                "wide_prob": round(float(prob), 6),
            })

        result = (
            pd.DataFrame(combos)
            .sort_values("wide_prob", ascending=False)
            .head(top_n)
            .reset_index(drop=True)
        )
        result.index += 1
        return result

    # ----------------------------------------------------------- ワイドボックス

    def predict_wide_box(
        self, entries_df: pd.DataFrame, box_size: int = 5
    ) -> dict:
        """
        P(top3) 上位 box_size 頭を選び、全2頭組み合わせをワイドボックス購入する。

        ワイドは1レースで最大3組が的中（3着以内の馬同士の全ペア）。
        box=5 なら C(5,2)=10 点で、最大3点が的中する可能性がある。

        Returns dict:
            selected_horses: list[dict]
            box_combos: pd.DataFrame
            n_tickets: int
            box_size: int
        """
        top3_probs = self.predict_top3_probs(entries_df)

        indices = np.argsort(top3_probs)[::-1][:box_size]
        indices = sorted(indices)

        selected_horses = []
        for idx in indices:
            selected_horses.append({
                "horse_number": entries_df.iloc[idx].get("horse_number"),
                "horse_name": entries_df.iloc[idx].get("horse_name", ""),
                "top3_prob": round(float(top3_probs[idx]), 4),
            })

        combos = []
        for ci, cj in combinations(range(len(indices)), 2):
            i, j = indices[ci], indices[cj]
            prob = top3_probs[i] * top3_probs[j]
            combos.append({
                "horse1_number": entries_df.iloc[i].get("horse_number"),
                "horse1_name": entries_df.iloc[i].get("horse_name", ""),
                "horse2_number": entries_df.iloc[j].get("horse_number"),
                "horse2_name": entries_df.iloc[j].get("horse_name", ""),
                "wide_prob": round(float(prob), 6),
            })

        box_df = pd.DataFrame(combos)
        if not box_df.empty:
            box_df = box_df.sort_values("wide_prob", ascending=False).reset_index(drop=True)
            box_df.index += 1

        return {
            "selected_horses": selected_horses,
            "box_combos": box_df,
            "n_tickets": len(combos),
            "box_size": box_size,
        }
