"""推論エンジン - 売買シグナル生成"""

import logging

import numpy as np
import pandas as pd

from fx_trader.config import settings
from fx_trader.features.builder import FeatureBuilder
from fx_trader.model.registry import load_model
from fx_trader.storage.repository import Repository

logger = logging.getLogger(__name__)


class ModelPredictor:
    """学習済みモデルで売買シグナルを生成"""

    def __init__(self, model_name: str, repo: Repository = None):
        self.model_name = model_name
        self.repo = repo or Repository()
        self.builder = FeatureBuilder(self.repo)
        self.model, self.metadata = load_model(model_name)

    def predict_signal(
        self,
        instrument: str,
        granularity: str = "H1",
        threshold: float = 0.55,
    ) -> dict:
        """単一通貨ペアの売買シグナルを生成

        Args:
            instrument: 通貨ペア
            granularity: 足の種類
            threshold: 売買判断の確率閾値

        Returns:
            dict: {
                instrument, signal_type, confidence,
                current_price, timestamp
            }
        """
        features = self.builder.build_prediction_features(instrument, granularity)
        if features.empty:
            logger.warning("No features available for %s", instrument)
            return {"instrument": instrument, "signal_type": "hold", "confidence": 0.0}

        # メタデータに保存された特徴量と合わせる
        model_features = self.metadata.get("features", [])
        if model_features:
            for col in model_features:
                if col not in features.columns:
                    features[col] = np.nan
            features = features[model_features]

        prob = self.model.predict_proba(features)[0]
        prob_up = prob[1]  # P(上昇)

        if prob_up >= threshold:
            signal_type = "buy"
            confidence = prob_up
        elif prob_up <= (1 - threshold):
            signal_type = "sell"
            confidence = 1 - prob_up
        else:
            signal_type = "hold"
            confidence = max(prob_up, 1 - prob_up)

        # 最新のローソク足情報
        candles = self.repo.get_candles(instrument, granularity, limit=1)

        result = {
            "instrument": instrument,
            "granularity": granularity,
            "signal_type": signal_type,
            "confidence": float(confidence),
            "prob_up": float(prob_up),
            "timestamp": str(candles.index[-1]) if not candles.empty else None,
            "model_name": self.model_name,
        }

        logger.info("Signal for %s: %s (confidence=%.3f, prob_up=%.3f)", instrument, signal_type, confidence, prob_up)
        return result

    def predict_all(
        self,
        instruments: list[str] = None,
        granularity: str = "H1",
        threshold: float = 0.55,
    ) -> list[dict]:
        """複数通貨ペアの売買シグナルを一括生成"""
        targets = instruments or settings.DEFAULT_INSTRUMENTS
        signals = []
        for inst in targets:
            signal = self.predict_signal(inst, granularity, threshold)
            signals.append(signal)
        return signals
