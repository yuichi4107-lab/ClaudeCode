"""モデルの保存・読み込み (joblib + メタデータ JSON)"""

import json
import logging
from datetime import datetime
from pathlib import Path

import joblib

from fx_trader.config.settings import MODEL_DIR

logger = logging.getLogger(__name__)


def save_model(model, model_name: str, metadata: dict = None):
    """モデルとメタデータを保存

    Args:
        model: 学習済みモデル
        model_name: モデル名 (例: "usdjpy_h1_v1")
        metadata: 付随情報 (学習期間、特徴量、スコア等)
    """
    model_path = MODEL_DIR / f"{model_name}.joblib"
    meta_path = MODEL_DIR / f"{model_name}_meta.json"

    joblib.dump(model, model_path)
    logger.info("Model saved: %s", model_path)

    if metadata:
        metadata["saved_at"] = datetime.now().isoformat()
        meta_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2))
        logger.info("Metadata saved: %s", meta_path)


def load_model(model_name: str):
    """モデルを読み込み

    Returns:
        tuple: (model, metadata_dict)
    """
    model_path = MODEL_DIR / f"{model_name}.joblib"
    meta_path = MODEL_DIR / f"{model_name}_meta.json"

    if not model_path.exists():
        raise FileNotFoundError(f"Model not found: {model_path}")

    model = joblib.load(model_path)
    logger.info("Model loaded: %s", model_path)

    metadata = {}
    if meta_path.exists():
        metadata = json.loads(meta_path.read_text())

    return model, metadata


def list_models() -> list[dict]:
    """保存済みモデル一覧を取得"""
    models = []
    for path in MODEL_DIR.glob("*.joblib"):
        name = path.stem
        meta_path = path.with_name(f"{name}_meta.json")
        metadata = {}
        if meta_path.exists():
            metadata = json.loads(meta_path.read_text())
        models.append({"name": name, "path": str(path), "metadata": metadata})
    return models
