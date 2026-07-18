"""autorace.jp レース結果ページの DOM 対応表。

実HTMLを確認して修正するのは原則このファイルだけで済むようにしてある。
result_parser.py は列順に依存せず、テーブルヘッダの見出し文字列を
HEADER_FIELD_MAP で引いてフィールド名に解決する。

現状の値は公開情報からの想定 DOM(tests/fixtures/autorace/synthetic_result.html
が同じ構造を再現している)。実サイトで parse-html に warnings が出たら、
ここのセレクタ・見出し文字列を実HTMLに合わせて直すこと。
"""

# --- ページ全体 ---
SELECTORS = {
    # レースヘッダ(レース名・開催情報を含むブロック)
    "race_header": ".race-header, .raceHeader, h2.race-title",
    # 天候・走路状態・気温などの気象ブロック
    "weather_block": ".race-weather, .weather-info, .raceInfo-weather",
    # 結果テーブル(1行=1車)
    "result_table": "table.result-table, table.raceResult, table#resultTable",
    # 払戻テーブル
    "payout_table": "table.payout-table, table.payoutTable",
}

# --- 結果テーブルの見出し文字列 → フィールド名 ---
# キーは正規化(全角→半角・空白除去)後の見出しに部分一致で照合する。
# 同義語はリストで列挙。マッチしない列は無視し warnings に記録する。
HEADER_FIELD_MAP = {
    "finish_pos": ["着順", "着"],
    "car_no": ["車番", "車"],
    "player_name": ["選手名", "選手"],
    "player_no": ["登録番号", "登録"],
    "handicap": ["ハンデ", "ハンデ位置", "H"],
    "trial_time": ["試走タイム", "試走T", "試T"],
    "race_time": ["競走タイム", "競走T", "競T"],
    "last_lap_time": ["上がりタイム", "上がりT", "上りタイム", "上り"],
    "st": ["スタートタイミング", "ST", "S.T"],
    "violation_note": ["違反", "事故", "備考"],
}

# --- 気象ブロック内のラベル → フィールド名 ---
WEATHER_FIELD_MAP = {
    "weather": ["天候", "天気"],
    "track_status": ["走路状態", "走路"],
    "temperature": ["気温"],
    "track_temp": ["走路温度", "走路温"],
}

# --- 走路状態の表記ゆれ → 正規化ラベル ---
TRACK_STATUS_MAP = {
    "良": "良走路",
    "良走路": "良走路",
    "湿": "湿走路",
    "湿走路": "湿走路",
    "斑": "湿走路",  # 斑走路(部分的に湿り)は保守的に湿扱い
    "斑走路": "湿走路",
}

# --- 着順・タイム欄の非数値表記 → race_entries.status ---
# 部分一致で照合。マッチした行は finish_pos=None となり status が置き換わる。
ABNORMAL_STATUS_MAP = {
    "欠": "scratched",   # 欠車
    "取消": "scratched",
    "落": "accident",    # 落車
    "転": "accident",    # 転倒
    "事": "accident",    # 事故
    "妨": "violation",   # 妨害
    "失": "violation",   # 失格(妨害以外の失格も保守的に violation)
    "反": "violation",   # 反則
    "他": "dnf",
}

# --- ST欄の特殊表記 ---
ST_FLYING_MARKS = ["F", "Ｆ", "フライング"]  # is_flying=1, st=None
ST_MISSING_MARKS = ["-", "－", "ー", "欠", ""]

# --- 試走タイム欄の再試走マーク ---
RETRIAL_MARKS = ["再", "※", "*"]
