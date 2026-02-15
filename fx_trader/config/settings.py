"""FX自動売買システム 設定ファイル"""

import os
from pathlib import Path

# --- プロジェクトパス ---
BASE_DIR = Path(__file__).resolve().parent.parent.parent
DATA_DIR = BASE_DIR / "data" / "fx"
DB_PATH = DATA_DIR / "fx_trader.db"
MODEL_DIR = DATA_DIR / "models"
CACHE_DIR = DATA_DIR / "cache"

# ディレクトリ自動作成
for d in [DATA_DIR, MODEL_DIR, CACHE_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# --- OANDA API 設定 ---
# 環境変数から読み込み。デモ口座を推奨
OANDA_API_KEY = os.environ.get("OANDA_API_KEY", "")
OANDA_ACCOUNT_ID = os.environ.get("OANDA_ACCOUNT_ID", "")
OANDA_ENVIRONMENT = os.environ.get("OANDA_ENVIRONMENT", "practice")  # "practice" or "live"

OANDA_BASE_URL = {
    "practice": "https://api-fxpractice.oanda.com",
    "live": "https://api-fxtrade.oanda.com",
}

# --- 通貨ペア ---
INSTRUMENTS = {
    "USD_JPY": {"pip_location": -2, "display": "ドル円"},
    "EUR_USD": {"pip_location": -4, "display": "ユーロドル"},
    "EUR_JPY": {"pip_location": -2, "display": "ユーロ円"},
    "GBP_JPY": {"pip_location": -2, "display": "ポンド円"},
    "AUD_JPY": {"pip_location": -2, "display": "豪ドル円"},
    "GBP_USD": {"pip_location": -4, "display": "ポンドドル"},
}

DEFAULT_INSTRUMENTS = ["USD_JPY", "EUR_USD", "EUR_JPY"]

# --- 足の種類 ---
GRANULARITIES = {
    "M1": "1分足",
    "M5": "5分足",
    "M15": "15分足",
    "M30": "30分足",
    "H1": "1時間足",
    "H4": "4時間足",
    "D": "日足",
    "W": "週足",
}

DEFAULT_GRANULARITY = "H1"

# --- API レート制限 ---
API_RATE_LIMIT_SECONDS = 0.5  # OANDA API は比較的緩い
API_MAX_CANDLES_PER_REQUEST = 5000

# --- 取引設定 ---
DEFAULT_TRADE_UNITS = 1000  # 最小ロット（デモ口座）
MAX_POSITION_SIZE = 10000  # 最大ポジションサイズ
MAX_OPEN_TRADES = 3  # 同時保有ポジション数上限

# --- リスク管理 ---
RISK_PER_TRADE_PCT = 2.0  # 1トレードあたりの最大リスク (口座残高の%)
MAX_DAILY_LOSS_PCT = 5.0  # 1日の最大損失 (口座残高の%)
DEFAULT_STOP_LOSS_PIPS = 30  # デフォルト損切り幅 (pips)
DEFAULT_TAKE_PROFIT_PIPS = 60  # デフォルト利確幅 (pips)

# --- モデル設定 ---
MODEL_PARAMS = {
    "n_estimators": 300,
    "learning_rate": 0.05,
    "max_depth": 6,
    "min_child_samples": 20,
    "class_weight": "balanced",
    "random_state": 42,
}

# --- 特徴量設定 ---
FEATURE_LOOKBACK_PERIODS = [5, 10, 20, 50, 100, 200]  # 移動平均等の期間
RSI_PERIOD = 14
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9
BOLLINGER_PERIOD = 20
BOLLINGER_STD = 2
ATR_PERIOD = 14

# --- バックテスト ---
BACKTEST_INITIAL_BALANCE = 1_000_000  # 初期資金 (円)
BACKTEST_SPREAD_PIPS = 1.0  # スプレッド想定値
