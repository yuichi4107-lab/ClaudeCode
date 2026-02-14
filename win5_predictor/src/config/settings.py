"""アプリケーション設定・定数"""

from pathlib import Path

# ──────────────────────────────────────
# パス設定
# ──────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"
MODELS_DIR = PROJECT_ROOT / "models"
DB_PATH = DATA_DIR / "win5.db"
CACHE_DIR = DATA_DIR / "cache"
EXPORT_DIR = DATA_DIR / "export"

# 起動時にディレクトリを作成
for d in (DATA_DIR, MODELS_DIR, CACHE_DIR, EXPORT_DIR):
    d.mkdir(parents=True, exist_ok=True)

# ──────────────────────────────────────
# スクレイピング設定
# ──────────────────────────────────────
NETKEIBA_BASE_URL = "https://db.netkeiba.com"
NETKEIBA_RACE_URL = "https://race.netkeiba.com"
REQUEST_INTERVAL_SEC = 1.2  # リクエスト間隔(秒) - 利用規約遵守
REQUEST_TIMEOUT_SEC = 30
MAX_RETRIES = 3
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

# ──────────────────────────────────────
# 特徴量設定
# ──────────────────────────────────────
RECENT_RUNS = 5  # 近走成績の参照レース数
MAX_RECENT_RUNS = 10
FEATURE_CACHE_TTL_HOURS = 24

# ──────────────────────────────────────
# モデル設定
# ──────────────────────────────────────
LIGHTGBM_DEFAULT_PARAMS = {
    "objective": "binary",
    "metric": "binary_logloss",
    "boosting_type": "gbdt",
    "num_leaves": 63,
    "learning_rate": 0.05,
    "feature_fraction": 0.8,
    "bagging_fraction": 0.8,
    "bagging_freq": 5,
    "verbose": -1,
    "n_estimators": 500,
    "early_stopping_rounds": 50,
    "min_child_samples": 20,
    "reg_alpha": 0.1,
    "reg_lambda": 0.1,
    "max_depth": -1,
    "is_unbalance": True,
}

# 時系列CV設定
CV_N_SPLITS = 5
CV_TEST_MONTHS = 3  # テスト期間(月)
CV_GAP_DAYS = 7  # 学習・テスト間のギャップ(日)

# ──────────────────────────────────────
# Win5設定
# ──────────────────────────────────────
WIN5_NUM_RACES = 5
WIN5_BET_UNIT = 100  # 1口100円
WIN5_DEDUCTION_RATE = 0.30  # 控除率30%
DEFAULT_BUDGET = 10000  # デフォルト予算

# ──────────────────────────────────────
# 資金管理設定
# ──────────────────────────────────────
KELLY_FRACTION = 0.25  # 1/4 Kelly
FIXED_FRACTION_RATE = 0.02  # 資金の2%
MIN_BET_AMOUNT = 100
MAX_BET_RATIO = 0.10  # 最大資金の10%

# ──────────────────────────────────────
# ログ設定
# ──────────────────────────────────────
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
LOG_LEVEL = "INFO"
