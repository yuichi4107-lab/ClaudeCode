"""画像生成の設定."""

import os

# Google AI Studio API キー (環境変数から取得)
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

# モデル設定
DEFAULT_MODEL = "gemini-3.1-flash-image-preview"  # NanoBanana2

# 画像設定
DEFAULT_ASPECT_RATIO = "1:1"
DEFAULT_OUTPUT_DIR = "data/generated_images"

# 並行リクエスト設定
MAX_CONCURRENT_REQUESTS = 5  # 同時リクエスト上限
REQUEST_TIMEOUT = 120  # 秒
RETRY_MAX_ATTEMPTS = 3
RETRY_BASE_DELAY = 2.0  # 秒 (指数バックオフの基数)

# サポートされるアスペクト比
SUPPORTED_ASPECT_RATIOS = [
    "1:1", "16:9", "9:16", "4:3", "3:4",
    "3:2", "2:3", "4:1", "1:4", "8:1", "1:8",
    "21:9",
]
