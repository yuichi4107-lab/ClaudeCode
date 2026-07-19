"""autorace.jp レース結果 JSON API のフィールド・コード対応表。

実サイトのHTMLはJS描画のシェルでありレース結果データを含まない
(2026-07 に実ページで確認)。データは以下の JSON API から取得する。

  POST /race_info/RaceResult   {placeCode, raceDate, raceNo}
    body.raceResult[] = {
      order, accidentCode, accidentName, carNo, playerCode, retireFlag,
      playerName, playerNameEn, motorcycleName, handicap,
      traialRetryCode, traialTime, raceTime, st, foulCode,
      anotherRaceNo, anotherRaceNo2,
    }
    body.refundInfo = {rtw, rfw, rt3, rf3, wid, tns, fns, absent}

  POST /race_info/OtherRaceInfo {placeCode, raceDate, raceNo}
    body = {placeKey, raceNo, gradeName, periodStartDate, periodEndDate,
            title, raceName, distance, temp, humid, roadtemp, situationCode,
            weather, raceTemp, raceHumid, raceRoadtemp, raceSituationCode,
            raceWeather, finalRaceNo, ...}

API仕様が変わった場合に修正するのは原則このファイルだけで済むようにしてある。
"""

# --- 走路状況コード → 正規化ラベル ---
# race.js config.situationNameList: 0=良走路,1=湿走路,2=風,3=オイル,4=荒,5=斑走路
# 斑走路(部分的に湿り)は保守的に湿扱い。風/オイル/荒はそのままのラベルで保存し、
# 指標側の「良走路のみ」フィルタから自然に外れるようにする。
SITUATION_TRACK_MAP = {
    0: "良走路",
    1: "湿走路",
    2: "風",
    3: "オイル",
    4: "荒",
    5: "湿走路",  # 斑走路
}

# --- 事故名(accidentName)の部分一致 → race_entries.status ---
# 結果ページ凡例: 欠:欠車/停:停止/徐:除外/落:落車/故:故障等/反:反則等/他:他落等/完:故障完走
# 辞書順に部分一致で照合する(「他落」は先に「落」でaccidentに解決される)。
# 「故障完走」等 order が付く行は着順を優先し finished のまま扱う(パーサ側)。
ACCIDENT_STATUS_MAP = {
    "欠": "scratched",   # 欠車
    "取消": "scratched",
    "除": "scratched",   # 除外
    "落": "accident",    # 落車・他落
    "転": "accident",    # 転倒
    "事": "accident",    # 事故
    "妨": "violation",   # 妨害
    "失": "violation",   # 失格
    "反": "violation",   # 反則
    "停": "dnf",         # 停止
    "故": "dnf",         # 故障
    "他": "dnf",
}

# --- スタート時の反則コード(foulCode) ---
# 凡例: F=フライング / L=出残り / B=後方スタート / W=スタート戒告 / A=その他異常発走
FOUL_FLYING_CODES = ["F", "Ｆ"]
FOUL_NOTE_MAP = {
    "F": "フライング",
    "L": "出残り",
    "B": "後方スタート",
    "W": "スタート戒告",
    "A": "その他異常発走",
}

# --- 再試走コード(traialRetryCode) ---
# race.js の描画コード上 1 のとき「再」を表示する
RETRIAL_CODES = [1]

# --- 払戻(refundInfo)の券種キー → 表示名 ---
# 組み合わせは list[] 内の 1thCarNo/2thCarNo/3thCarNo を "-" 連結で表現する
REFUND_BET_TYPES = {
    "rtw": "2連単",
    "rfw": "2連複",
    "rt3": "3連単",
    "rf3": "3連複",
    "wid": "ワイド",
    "tns": "単勝",
    "fns": "複勝",
}

# 払戻 typeCode: 0=通常, 1=特払い, 2=キャリーオーバー, 3=全返還, 4=無投票
REFUND_TYPE_NORMAL = 0

# --- HTMLシェルから CSRF トークンを抜き出す正規表現 ---
CSRF_TOKEN_PATTERN = r'<meta name="csrf-token" content="([^"]+)"'
