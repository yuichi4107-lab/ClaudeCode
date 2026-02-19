# JRA 中央競馬 10場の会場コード
VENUE_CODES = {
    "sapporo":  "01",  # 札幌
    "hakodate": "02",  # 函館
    "fukushima": "03", # 福島
    "niigata":  "04",  # 新潟
    "tokyo":    "05",  # 東京
    "nakayama": "06",  # 中山
    "chukyo":   "07",  # 中京
    "kyoto":    "08",  # 京都
    "hanshin":  "09",  # 阪神
    "kokura":   "10",  # 小倉
}

VENUE_NAMES = {v: k for k, v in VENUE_CODES.items()}

VENUE_NAMES_JP = {
    "01": "札幌", "02": "函館", "03": "福島", "04": "新潟", "05": "東京",
    "06": "中山", "07": "中京", "08": "京都", "09": "阪神", "10": "小倉",
}

JRA_VENUES = list(VENUE_CODES.values())

BASE_URLS = {
    "db_race":      "https://db.netkeiba.com/race/{race_id}/",
    "db_horse":     "https://db.netkeiba.com/horse/result/{horse_id}/",
    "jra_shutuba":  "https://race.netkeiba.com/race/shutuba.html",
    "jra_odds":     "https://race.netkeiba.com/odds/index.html",
    "db_racelist":  "https://db.netkeiba.com/",
}

RATE_LIMIT_SECONDS = 3.0
REQUEST_TIMEOUT = 30
MAX_RETRIES = 3

DB_PATH = "data/jra.db"
MODEL_DIR = "data/models"
CACHE_DIR = "data/cache"
USE_CACHE = True

TRACK_CONDITION_ENC = {"良": 0, "稍重": 1, "重": 2, "不良": 3}
TRACK_TYPE_ENC = {"ダート": 0, "芝": 1, "障害": 2}
COURSE_DIRECTION_ENC = {"右": 0, "左": 1, "直線": 2}
RACE_CLASS_ENC = {"未勝利": 1, "1勝クラス": 2, "2勝クラス": 3, "3勝クラス": 4, "オープン": 5}
