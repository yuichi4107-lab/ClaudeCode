import json
import logging
from datetime import datetime
from pathlib import Path

import joblib

from nankan_predictor.config.settings import MODEL_DIR
from nankan_predictor.features.builder import NUMERIC_FEATURES

logger = logging.getLogger(__name__)


def save_model(model, model_name: str, meta: dict = None) -> None:
    model_dir = Path(MODEL_DIR)
    model_dir.mkdir(parents=True, exist_ok=True)

    model_path = model_dir / f"{model_name}.joblib"
    meta_path = model_dir / f"{model_name}_meta.json"

    joblib.dump(model, model_path)

    meta = meta or {}
    meta["saved_at"] = datetime.now().isoformat()
    meta["features"] = NUMERIC_FEATURES

    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    logger.info("Model saved: %s", model_path)
    print(f"Model saved: {model_path}")


def load_model(model_name: str):
    model_path = Path(MODEL_DIR) / f"{model_name}.joblib"
    if not model_path.exists():
        raise FileNotFoundError(
            f"Model not found: {model_path}\n"
            "Run 'nankan train' first."
        )
    model = joblib.load(model_path)
    logger.info("Model loaded: %s", model_path)
    return model


def load_meta(model_name: str) -> dict:
    meta_path = Path(MODEL_DIR) / f"{model_name}_meta.json"
    if not meta_path.exists():
        return {}
    with open(meta_path, encoding="utf-8") as f:
        return json.load(f)
