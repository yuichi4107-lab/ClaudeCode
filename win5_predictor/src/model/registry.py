"""モデルバージョン管理"""

import logging
from datetime import date, datetime
from pathlib import Path

import numpy as np

from config.settings import MODELS_DIR
from database.models import ModelInfo
from database.repository import Repository
from model.trainer import LightGBMTrainer

logger = logging.getLogger(__name__)


class ModelRegistry:
    """学習済みモデルのバージョン管理"""

    def __init__(self, repo: Repository | None = None):
        self.repo = repo or Repository()

    def register(
        self,
        trainer: LightGBMTrainer,
        model_name: str = "lgbm_win5",
        train_start: date | None = None,
        train_end: date | None = None,
    ) -> str:
        """モデルを保存・登録する"""
        version = datetime.now().strftime("%Y%m%d_%H%M%S")
        model_id = f"{model_name}_{version}"

        # モデルファイル保存
        model_path = trainer.save(version=version)

        # CV結果から指標を取得
        auc = 0.0
        logloss = 0.0
        accuracy = 0.0
        if trainer.cv_results:
            auc = float(np.mean([r["auc"] for r in trainer.cv_results]))
            logloss = float(np.mean([r["logloss"] for r in trainer.cv_results]))
            accuracy = float(np.mean([r.get("accuracy", 0) for r in trainer.cv_results]))

        import json

        model_info = ModelInfo(
            model_id=model_id,
            model_name=model_name,
            version=version,
            model_path=str(model_path),
            train_start=train_start,
            train_end=train_end,
            auc=auc,
            logloss=logloss,
            accuracy=accuracy,
            feature_count=len(trainer.feature_names),
            params=json.dumps(trainer.params),
            is_active=False,
        )

        self.repo.register_model(model_info)
        logger.info("Model registered: %s (AUC=%.4f)", model_id, auc)

        return model_id

    def activate(self, model_id: str):
        """指定モデルをアクティブにする"""
        self.repo.set_active_model(model_id)
        logger.info("Model activated: %s", model_id)

    def register_and_activate(
        self,
        trainer: LightGBMTrainer,
        model_name: str = "lgbm_win5",
        train_start: date | None = None,
        train_end: date | None = None,
    ) -> str:
        """モデルを登録しアクティブにする"""
        model_id = self.register(trainer, model_name, train_start, train_end)
        self.activate(model_id)
        return model_id

    def get_active(self) -> ModelInfo | None:
        """現在のアクティブモデル情報を取得"""
        return self.repo.get_active_model()

    def load_active(self) -> LightGBMTrainer:
        """アクティブモデルを読み込む"""
        info = self.get_active()
        if info is None:
            raise ValueError("No active model found")
        if not Path(info.model_path).exists():
            raise FileNotFoundError(f"Model file not found: {info.model_path}")
        return LightGBMTrainer.load(info.model_path)

    def list_models(self) -> list[dict]:
        """登録済みモデル一覧を返す"""
        with self.repo.db.cursor() as cur:
            rows = cur.execute(
                "SELECT model_id, model_name, version, auc, logloss, "
                "feature_count, is_active, created_at "
                "FROM model_registry ORDER BY created_at DESC"
            ).fetchall()
        return [dict(r) for r in rows]
