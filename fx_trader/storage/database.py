"""SQLite データベース スキーマ定義・接続管理"""

import sqlite3
from contextlib import contextmanager

from fx_trader.config.settings import DB_PATH

SCHEMA_SQL = """
-- ローソク足データ (OHLCV)
CREATE TABLE IF NOT EXISTS candles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    instrument TEXT NOT NULL,
    granularity TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    open REAL NOT NULL,
    high REAL NOT NULL,
    low REAL NOT NULL,
    close REAL NOT NULL,
    volume INTEGER NOT NULL DEFAULT 0,
    complete INTEGER NOT NULL DEFAULT 1,
    UNIQUE(instrument, granularity, timestamp)
);

-- テクニカル指標キャッシュ
CREATE TABLE IF NOT EXISTS indicators (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    instrument TEXT NOT NULL,
    granularity TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    indicator_name TEXT NOT NULL,
    value REAL,
    UNIQUE(instrument, granularity, timestamp, indicator_name)
);

-- 売買シグナル
CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    instrument TEXT NOT NULL,
    granularity TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    signal_type TEXT NOT NULL,  -- 'buy' / 'sell' / 'hold'
    confidence REAL,
    model_name TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(instrument, granularity, timestamp, model_name)
);

-- 取引履歴
CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_id TEXT UNIQUE,             -- OANDA trade ID
    instrument TEXT NOT NULL,
    side TEXT NOT NULL,                -- 'buy' / 'sell'
    units REAL NOT NULL,
    entry_price REAL NOT NULL,
    exit_price REAL,
    stop_loss REAL,
    take_profit REAL,
    entry_time TEXT NOT NULL,
    exit_time TEXT,
    pnl REAL,                         -- 損益 (決済後に記録)
    pnl_pips REAL,                    -- 損益 pips
    status TEXT NOT NULL DEFAULT 'open',  -- 'open' / 'closed'
    signal_id INTEGER,
    notes TEXT,
    FOREIGN KEY (signal_id) REFERENCES signals(id)
);

-- 口座スナップショット (日次)
CREATE TABLE IF NOT EXISTS account_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_date TEXT NOT NULL UNIQUE,
    balance REAL NOT NULL,
    unrealized_pnl REAL NOT NULL DEFAULT 0,
    realized_pnl_daily REAL NOT NULL DEFAULT 0,
    open_trade_count INTEGER NOT NULL DEFAULT 0,
    nav REAL NOT NULL
);

-- データ取得ログ
CREATE TABLE IF NOT EXISTS fetch_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    instrument TEXT NOT NULL,
    granularity TEXT NOT NULL,
    from_time TEXT,
    to_time TEXT,
    candle_count INTEGER,
    fetched_at TEXT NOT NULL DEFAULT (datetime('now')),
    status TEXT NOT NULL DEFAULT 'success',
    error_msg TEXT
);

-- インデックス
CREATE INDEX IF NOT EXISTS idx_candles_inst_gran_ts
    ON candles(instrument, granularity, timestamp);
CREATE INDEX IF NOT EXISTS idx_candles_timestamp
    ON candles(timestamp);
CREATE INDEX IF NOT EXISTS idx_indicators_lookup
    ON indicators(instrument, granularity, timestamp, indicator_name);
CREATE INDEX IF NOT EXISTS idx_trades_instrument
    ON trades(instrument, status);
CREATE INDEX IF NOT EXISTS idx_trades_entry_time
    ON trades(entry_time);
CREATE INDEX IF NOT EXISTS idx_signals_lookup
    ON signals(instrument, granularity, timestamp);
"""


def get_connection(db_path=None):
    """SQLite 接続を取得（WALモード）"""
    path = db_path or str(DB_PATH)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(db_path=None):
    """データベース初期化（テーブル作成）"""
    conn = get_connection(db_path)
    conn.executescript(SCHEMA_SQL)
    conn.commit()
    conn.close()


@contextmanager
def db_session(db_path=None):
    """コンテキストマネージャでDB接続を管理"""
    conn = get_connection(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
