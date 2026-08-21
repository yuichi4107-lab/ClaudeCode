"""帯広ばんえい競馬予想システム設定"""

import os
from pathlib import Path

# プロジェクトルート
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# データディレクトリ
DATA_DIR = PROJECT_ROOT / "data"
RAW_DATA_DIR = DATA_DIR / "raw"
PROCESSED_DATA_DIR = DATA_DIR / "processed"
MODELS_DIR = PROJECT_ROOT / "models"
PREDICTIONS_DIR = PROJECT_ROOT / "predictions"

# スクレイピング設定
REQUEST_INTERVAL = 2  # リクエスト間隔（秒）
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

# 帯広競馬場コード（地方競馬の場コード）
OBIHIRO_COURSE_CODE = "3"

# モデル設定
LIGHTGBM_PARAMS = {
    "objective": "binary",
    "metric": "auc",
    "boosting_type": "gbdt",
    "num_leaves": 31,
    "learning_rate": 0.05,
    "feature_fraction": 0.8,
    "bagging_fraction": 0.8,
    "bagging_freq": 5,
    "verbose": -1,
    "n_estimators": 500,
    "early_stopping_rounds": 50,
}

# 特徴量設定
PAST_RACE_COUNT = 5  # 過去何走分のデータを使うか

# Telegram設定（環境変数 or .envファイルから読み込み）
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
