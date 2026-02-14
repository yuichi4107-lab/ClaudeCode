-- Win5 Predictor 初期スキーマ

-- レース情報
CREATE TABLE IF NOT EXISTS races (
    race_id        TEXT PRIMARY KEY,          -- 例: 202405050811 (年+場+回+日+R)
    race_date      DATE NOT NULL,
    venue_code     TEXT NOT NULL,             -- 競馬場コード (01-10)
    venue_name     TEXT,
    race_number    INTEGER NOT NULL,          -- レース番号 (1-12)
    race_name      TEXT,
    surface        TEXT,                      -- turf / dirt / jump
    distance       INTEGER,                  -- 距離(m)
    track_condition TEXT,                     -- good / slightly_heavy / heavy / bad
    weather        TEXT,
    race_class     TEXT,
    race_class_code INTEGER,
    age_condition  TEXT,                      -- 例: 3歳以上
    weight_rule    TEXT,                      -- 例: 定量 / 別定 / ハンデ
    num_runners    INTEGER,
    prize_1st      REAL,                     -- 1着賞金(万円)
    created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_races_date ON races(race_date);
CREATE INDEX IF NOT EXISTS idx_races_venue ON races(venue_code, race_date);

-- レース結果 (各馬の出走・結果)
CREATE TABLE IF NOT EXISTS race_results (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    race_id        TEXT NOT NULL REFERENCES races(race_id),
    horse_id       TEXT NOT NULL,
    horse_name     TEXT,
    finish_position INTEGER,                  -- 着順 (NULL=取消/除外)
    post_position  INTEGER,                  -- 枠番
    horse_number   INTEGER,                  -- 馬番
    sex            TEXT,
    age            INTEGER,
    weight_carried REAL,                     -- 斤量
    jockey_id      TEXT,
    jockey_name    TEXT,
    trainer_id     TEXT,
    trainer_name   TEXT,
    finish_time    REAL,                     -- タイム(秒)
    margin         TEXT,                     -- 着差
    last_3f        REAL,                     -- 上がり3F(秒)
    horse_weight   INTEGER,                  -- 馬体重(kg)
    weight_change  INTEGER,                  -- 馬体重増減(kg)
    odds           REAL,                     -- 単勝オッズ
    popularity     INTEGER,                  -- 人気順
    running_style  TEXT,                     -- 脚質
    corner_positions TEXT,                   -- 通過順位 (例: "3-3-2-1")
    prize_money    REAL,                     -- 獲得賞金(万円)
    created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(race_id, horse_number)
);
CREATE INDEX IF NOT EXISTS idx_results_race ON race_results(race_id);
CREATE INDEX IF NOT EXISTS idx_results_horse ON race_results(horse_id);
CREATE INDEX IF NOT EXISTS idx_results_jockey ON race_results(jockey_id);
CREATE INDEX IF NOT EXISTS idx_results_trainer ON race_results(trainer_id);

-- 馬マスタ
CREATE TABLE IF NOT EXISTS horses (
    horse_id       TEXT PRIMARY KEY,
    horse_name     TEXT NOT NULL,
    sex            TEXT,
    birth_year     INTEGER,
    coat_color     TEXT,                     -- 毛色
    sire_id        TEXT,                     -- 父
    sire_name      TEXT,
    dam_id         TEXT,                     -- 母
    dam_name       TEXT,
    damsire_id     TEXT,                     -- 母父
    damsire_name   TEXT,
    owner          TEXT,
    breeder        TEXT,
    total_wins     INTEGER DEFAULT 0,
    total_runs     INTEGER DEFAULT 0,
    total_earnings REAL DEFAULT 0,
    created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 騎手マスタ
CREATE TABLE IF NOT EXISTS jockeys (
    jockey_id      TEXT PRIMARY KEY,
    jockey_name    TEXT NOT NULL,
    birth_year     INTEGER,
    affiliation    TEXT,                     -- 所属 (美浦/栗東/地方)
    total_wins     INTEGER DEFAULT 0,
    total_runs     INTEGER DEFAULT 0,
    win_rate       REAL DEFAULT 0,
    created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 調教師マスタ
CREATE TABLE IF NOT EXISTS trainers (
    trainer_id     TEXT PRIMARY KEY,
    trainer_name   TEXT NOT NULL,
    affiliation    TEXT,
    total_wins     INTEGER DEFAULT 0,
    total_runs     INTEGER DEFAULT 0,
    win_rate       REAL DEFAULT 0,
    created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- オッズ推移
CREATE TABLE IF NOT EXISTS odds_history (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    race_id        TEXT NOT NULL REFERENCES races(race_id),
    horse_number   INTEGER NOT NULL,
    timestamp      TIMESTAMP NOT NULL,
    win_odds       REAL,                     -- 単勝オッズ
    place_odds_min REAL,                     -- 複勝オッズ下限
    place_odds_max REAL,                     -- 複勝オッズ上限
    UNIQUE(race_id, horse_number, timestamp)
);
CREATE INDEX IF NOT EXISTS idx_odds_race ON odds_history(race_id);

-- Win5開催情報
CREATE TABLE IF NOT EXISTS win5_events (
    event_id       TEXT PRIMARY KEY,          -- 日付ベース: 20240101
    event_date     DATE NOT NULL,
    race1_id       TEXT REFERENCES races(race_id),
    race2_id       TEXT REFERENCES races(race_id),
    race3_id       TEXT REFERENCES races(race_id),
    race4_id       TEXT REFERENCES races(race_id),
    race5_id       TEXT REFERENCES races(race_id),
    payout         REAL,                     -- 配当金額
    carryover      REAL,                     -- キャリーオーバー額
    num_winners    INTEGER,                  -- 的中票数
    total_sales    REAL,                     -- 発売金額
    created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_win5_date ON win5_events(event_date);

-- Win5購入記録
CREATE TABLE IF NOT EXISTS win5_bets (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id       TEXT NOT NULL REFERENCES win5_events(event_id),
    bet_date       DATE NOT NULL,
    selections     TEXT NOT NULL,             -- JSON: [[1,3],[2],[1,5,8],[3],[1,2]]
    num_combinations INTEGER NOT NULL,
    total_cost     INTEGER NOT NULL,
    is_hit         INTEGER DEFAULT 0,
    payout         REAL DEFAULT 0,
    model_version  TEXT,
    created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 資金推移
CREATE TABLE IF NOT EXISTS bankroll (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    record_date    DATE NOT NULL,
    balance        REAL NOT NULL,
    deposit        REAL DEFAULT 0,            -- 入金
    withdrawal     REAL DEFAULT 0,            -- 出金
    bet_amount     REAL DEFAULT 0,            -- 購入金額
    payout         REAL DEFAULT 0,            -- 配当金額
    note           TEXT,
    created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_bankroll_date ON bankroll(record_date);

-- モデルレジストリ
CREATE TABLE IF NOT EXISTS model_registry (
    model_id       TEXT PRIMARY KEY,
    model_name     TEXT NOT NULL,
    version        TEXT NOT NULL,
    model_path     TEXT NOT NULL,
    train_start    DATE,
    train_end      DATE,
    auc            REAL,
    logloss        REAL,
    accuracy       REAL,
    feature_count  INTEGER,
    params         TEXT,                     -- JSON
    is_active      INTEGER DEFAULT 0,
    created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 特徴量キャッシュ
CREATE TABLE IF NOT EXISTS feature_cache (
    cache_key      TEXT PRIMARY KEY,          -- race_id + horse_id
    race_id        TEXT NOT NULL,
    horse_id       TEXT NOT NULL,
    features       TEXT NOT NULL,             -- JSON
    created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at     TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_fcache_race ON feature_cache(race_id);
