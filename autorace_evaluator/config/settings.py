"""オートレース選手能力評価システムの設定。

会場スラッグ・URL・DB/キャッシュパス・指標計算の閾値定数を一元管理する。

データ取得は autorace.jp の JSON API を使う(実HTMLは JS 描画のシェルのみで
レース結果データを含まないことを 2026-07 に実ページで確認済み)。
"""

# autorace.jp のURLパスに使われる会場スラッグ
VENUE_SLUGS = ["kawaguchi", "isesaki", "hamamatsu", "sanyou", "iizuka"]

# 川口の1日2回開催(2開催目)。カレンダーに現れた場合のみ収集対象に加える。
TWICE_VENUE_SLUG = "kawaguchi2"

VENUE_NAMES_JA = {
    "kawaguchi": "川口",
    "isesaki": "伊勢崎",
    "hamamatsu": "浜松",
    "sanyou": "山陽",
    "iizuka": "飯塚",
    "kawaguchi2": "川口(2回目)",
}

# API の placeCode (web_app/js/race.js 内 config.placeCodeList より)
PLACE_CODES = {
    "kawaguchi": 2,
    "isesaki": 3,
    "hamamatsu": 4,
    "iizuka": 5,
    "sanyou": 6,
    "kawaguchi2": 12,
}

BASE_URLS = {
    # 結果ページ(HTMLシェル)。CSRFトークン取得と scrape_log のキーに使う
    "race_result_page": "https://autorace.jp/race_info/RaceResult/{venue}/{date}_{race_no}",
    # レース結果 JSON API (POST {placeCode, raceDate: "YYYY-MM-DD", raceNo})
    "api_race_result": "https://autorace.jp/race_info/RaceResult",
    # レース補足情報 JSON API (POST 同上): 距離・天候・走路状況・節開始日など
    "api_other_race_info": "https://autorace.jp/race_info/OtherRaceInfo",
    # 出走表 JSON API (POST 同上): 車級・期別・級班・年齢・連対率など
    "api_program": "https://autorace.jp/race_info/Program",
    # 出走表の scrape_log キー用疑似URL(一意で安定していればよい)
    "race_program_page": "https://autorace.jp/race_info/RaceProgram/{venue}/{date}_{race_no}",
    # 開催カレンダー JSON API (GET ?date=YYYY-MM)
    "api_calendar": "https://autorace.jp/race_info/XML/Calendar",
    # CSRFトークン取得用ページ
    "race_info_top": "https://autorace.jp/race_info/",
}

# API 応答の result="Failure" 時のエラーコード
API_CODE_NO_DATA = "4101"   # レスポンス0件(未開催・存在しないレース番号・未確定)
API_CODE_CANCELLED = "4200"  # 開催中止

RATE_LIMIT_SECONDS = 3.0
REQUEST_TIMEOUT = 30
MAX_RETRIES = 3
MAX_RACE_NO = 12  # カレンダーから最終レース番号が取れない場合の探索上限

DB_PATH = "data/autorace.db"
CACHE_DIR = "data/autorace_cache"
REPORT_DIR = "data/reports"
USE_CACHE = True

# 競走タイム・上がりタイムの掲載単位。
#   "per100m": 100mあたり換算タイム(例 3.36)としてそのまま扱う
#   "total":   総所要時間として距離で割って per-100m に換算する
# 実API応答 (raceTime="3.852", distance=3100) で per-100m 換算掲載と確認済み。
TIME_FORMAT = "per100m"

# --- 指標計算の定数 ---
SHRINKAGE_K = 10        # 経験ベイズ縮約 n/(n+k) の k
MIN_RACES = 10          # スタート力・突っ込み度スコアの最小出走数(未満は参考行)
MIN_PAIRS = 5           # 整備力スコアの最小前日ペア数(未満は参考行)
RIDGE_ALPHA = 1.0       # 残差モデルの Ridge 正則化係数
TRIAL_TIME_DECIMALS = 2  # 試走タイム差の丸め桁(0.01秒刻み)

# --- 湿走路適性の定数 ---
MIN_WET_RACES = 5       # wet_score の最小湿走路出走数(未満は参考行)
SHRINKAGE_K_WET = 5     # 湿走路残差の縮約k(母数が小さいため既定10より弱める)

# --- 新人(2級車)指標の定数 ---
ROOKIE_RECENT_TERMS = 2   # データ内最大期別からこの期数以内を新人とみなす
ROOKIE_MAX_RACES = 30     # DB内初出走からこの走数以内も新人とみなす
ROOKIE_MIN_RACES = 5      # rookie_score の最小2級車出走数(未満は参考行)
ROOKIE_SHRINKAGE_K = 3    # 新人残差の縮約k

# 走路状態の正規化後ラベル
TRACK_GOOD = "良走路"
TRACK_WET = "湿走路"

# race_entries.status の取りうる値
STATUS_FINISHED = "finished"    # 完走
STATUS_SCRATCHED = "scratched"  # 欠車・出走取消・除外
STATUS_ACCIDENT = "accident"    # 落車・転倒・事故
STATUS_VIOLATION = "violation"  # 反則・妨害による失格
STATUS_DNF = "dnf"              # その他未完走(停止・故障等)
