"""keiba-unified 統合設定"""

import os
from pathlib import Path

# プロジェクトルート
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# データディレクトリ
DATA_DIR = PROJECT_ROOT / "data"

# Telegram設定（共通・2026-05-30 フォールバック即値を除去。環境変数で供給すること）
TELEGRAM_BOT_TOKEN_JRA = os.environ.get("TG_TOKEN_JRA", "")
TELEGRAM_BOT_TOKEN_BANEI = os.environ.get("TG_TOKEN_BANEI", "")
TELEGRAM_CHAT_ID = os.environ.get("TG_CHAT_ID", "8571447808")

# スクレイピング共通設定
REQUEST_INTERVAL = 1.5  # 秒
REQUEST_TIMEOUT = 30
MAX_RETRIES = 3
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

# LightGBM共通デフォルト
LIGHTGBM_DEFAULT_PARAMS = {
    "objective": "binary",
    "metric": "binary_logloss",
    "boosting_type": "gbdt",
    "num_leaves": 63,
    "learning_rate": 0.05,
    "feature_fraction": 0.8,
    "bagging_fraction": 0.8,
    "bagging_freq": 5,
    "n_estimators": 500,
    "early_stopping_rounds": 50,
    "verbose": -1,
    "is_unbalance": True,
}
