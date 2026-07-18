"""オートレース選手能力評価システムの設定。

会場スラッグ・URL・DB/キャッシュパス・指標計算の閾値定数を一元管理する。
"""

# autorace.jp のURLパスに使われる会場スラッグ
VENUE_SLUGS = ["kawaguchi", "isesaki", "hamamatsu", "sanyou", "iizuka"]

VENUE_NAMES_JA = {
    "kawaguchi": "川口",
    "isesaki": "伊勢崎",
    "hamamatsu": "浜松",
    "sanyou": "山陽",
    "iizuka": "飯塚",
}

BASE_URLS = {
    # レース結果: 日付は YYYY-MM-DD、race_no は 1..12
    "race_result": "https://autorace.jp/race_info/RaceResult/{venue}/{date}_{race_no}",
    # 開催カレンダー(レース一覧探索の第一候補。解析不能時は probe 方式に切替)
    "race_info_top": "https://autorace.jp/race_info/",
    "recent": "https://autorace.jp/race_info/Recent/{venue}",
}

RATE_LIMIT_SECONDS = 3.0
REQUEST_TIMEOUT = 30
MAX_RETRIES = 3
MAX_RACE_NO = 12  # probe 方式で試すレース番号の上限

DB_PATH = "data/autorace.db"
CACHE_DIR = "data/autorace_cache"
REPORT_DIR = "data/reports"
USE_CACHE = True

# 競走タイム・上がりタイムの掲載単位。
#   "per100m": 100mあたり換算タイム(例 3.36)としてそのまま扱う
#   "total":   総所要時間として距離で割って per-100m に換算する
# 実HTMLで確認後に確定させること(metrics は to_per100m() 経由でのみ参照)。
TIME_FORMAT = "per100m"

# --- 指標計算の定数 ---
SHRINKAGE_K = 10        # 経験ベイズ縮約 n/(n+k) の k
MIN_RACES = 10          # スタート力・突っ込み度スコアの最小出走数(未満は参考行)
MIN_PAIRS = 5           # 整備力スコアの最小前日ペア数(未満は参考行)
RIDGE_ALPHA = 1.0       # 残差モデルの Ridge 正則化係数
TRIAL_TIME_DECIMALS = 2  # 試走タイム差の丸め桁(0.01秒刻み)

# 走路状態の正規化後ラベル
TRACK_GOOD = "良走路"
TRACK_WET = "湿走路"

# race_entries.status の取りうる値
STATUS_FINISHED = "finished"    # 完走
STATUS_SCRATCHED = "scratched"  # 欠車・出走取消
STATUS_ACCIDENT = "accident"    # 落車・転倒・事故
STATUS_VIOLATION = "violation"  # 反則・妨害による失格
STATUS_DNF = "dnf"              # その他未完走
