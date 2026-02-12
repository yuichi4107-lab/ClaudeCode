VENUE_CODES = {
    "urawa":     "44",
    "funabashi": "45",
    "oi":        "46",
    "kawasaki":  "47",
}

VENUE_NAMES = {v: k for k, v in VENUE_CODES.items()}

NANKAN_VENUES = list(VENUE_CODES.values())  # ["44", "45", "46", "47"]

BASE_URLS = {
    "db_race":     "https://db.netkeiba.com/race/{race_id}/",
    "db_horse":    "https://db.netkeiba.com/horse/result/{horse_id}/",
    "nar_shutuba": "https://nar.netkeiba.com/race/shutuba.html",
    "nar_odds":    "https://nar.netkeiba.com/odds/odds_get_form.html",
    "db_racelist": "https://db.netkeiba.com/",
}

RATE_LIMIT_SECONDS = 3.0
REQUEST_TIMEOUT = 30
MAX_RETRIES = 3

DB_PATH = "data/nankan.db"
MODEL_DIR = "data/models"
CACHE_DIR = "data/cache"
USE_CACHE = True

TRACK_CONDITION_ENC = {"良": 0, "稍重": 1, "重": 2, "不良": 3}
TRACK_TYPE_ENC = {"ダート": 0, "芝": 1}
