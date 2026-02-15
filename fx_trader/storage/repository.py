"""データアクセス層 - CRUD操作"""

import sqlite3
from typing import Optional

import pandas as pd

from fx_trader.storage.database import get_connection, init_db


class Repository:
    """FXデータのCRUD操作を提供"""

    def __init__(self, db_path=None):
        self.db_path = db_path
        init_db(db_path)

    def _conn(self):
        return get_connection(self.db_path)

    # --- Candles ---

    def upsert_candles(self, candles: list[dict]):
        """ローソク足データを一括upsert"""
        if not candles:
            return
        conn = self._conn()
        try:
            conn.executemany(
                """INSERT INTO candles (instrument, granularity, timestamp, open, high, low, close, volume, complete)
                   VALUES (:instrument, :granularity, :timestamp, :open, :high, :low, :close, :volume, :complete)
                   ON CONFLICT(instrument, granularity, timestamp)
                   DO UPDATE SET open=excluded.open, high=excluded.high, low=excluded.low,
                                 close=excluded.close, volume=excluded.volume, complete=excluded.complete""",
                candles,
            )
            conn.commit()
        finally:
            conn.close()

    def get_candles(
        self,
        instrument: str,
        granularity: str,
        from_time: Optional[str] = None,
        to_time: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> pd.DataFrame:
        """ローソク足データを取得してDataFrameで返す"""
        conn = self._conn()
        try:
            query = "SELECT timestamp, open, high, low, close, volume FROM candles WHERE instrument=? AND granularity=?"
            params: list = [instrument, granularity]

            if from_time:
                query += " AND timestamp >= ?"
                params.append(from_time)
            if to_time:
                query += " AND timestamp < ?"
                params.append(to_time)

            query += " ORDER BY timestamp ASC"

            if limit:
                query += " LIMIT ?"
                params.append(limit)

            df = pd.read_sql_query(query, conn, params=params)
            if not df.empty:
                df["timestamp"] = pd.to_datetime(df["timestamp"])
                df.set_index("timestamp", inplace=True)
            return df
        finally:
            conn.close()

    def get_latest_candle_time(self, instrument: str, granularity: str) -> Optional[str]:
        """最新のローソク足タイムスタンプを取得"""
        conn = self._conn()
        try:
            row = conn.execute(
                "SELECT MAX(timestamp) as max_ts FROM candles WHERE instrument=? AND granularity=?",
                (instrument, granularity),
            ).fetchone()
            return row["max_ts"] if row and row["max_ts"] else None
        finally:
            conn.close()

    # --- Signals ---

    def upsert_signal(self, signal: dict):
        """売買シグナルをupsert"""
        conn = self._conn()
        try:
            conn.execute(
                """INSERT INTO signals (instrument, granularity, timestamp, signal_type, confidence, model_name)
                   VALUES (:instrument, :granularity, :timestamp, :signal_type, :confidence, :model_name)
                   ON CONFLICT(instrument, granularity, timestamp, model_name)
                   DO UPDATE SET signal_type=excluded.signal_type, confidence=excluded.confidence""",
                signal,
            )
            conn.commit()
            return conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        finally:
            conn.close()

    def get_signals(
        self,
        instrument: str,
        from_time: Optional[str] = None,
        to_time: Optional[str] = None,
    ) -> pd.DataFrame:
        """シグナル一覧を取得"""
        conn = self._conn()
        try:
            query = "SELECT * FROM signals WHERE instrument=?"
            params: list = [instrument]
            if from_time:
                query += " AND timestamp >= ?"
                params.append(from_time)
            if to_time:
                query += " AND timestamp < ?"
                params.append(to_time)
            query += " ORDER BY timestamp ASC"
            return pd.read_sql_query(query, conn, params=params)
        finally:
            conn.close()

    # --- Trades ---

    def insert_trade(self, trade: dict) -> int:
        """取引記録を挿入"""
        conn = self._conn()
        try:
            conn.execute(
                """INSERT INTO trades (trade_id, instrument, side, units, entry_price, stop_loss,
                                       take_profit, entry_time, status, signal_id, notes)
                   VALUES (:trade_id, :instrument, :side, :units, :entry_price, :stop_loss,
                           :take_profit, :entry_time, :status, :signal_id, :notes)""",
                trade,
            )
            conn.commit()
            return conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        finally:
            conn.close()

    def close_trade(self, trade_id: str, exit_price: float, exit_time: str, pnl: float, pnl_pips: float):
        """取引をクローズ"""
        conn = self._conn()
        try:
            conn.execute(
                """UPDATE trades SET exit_price=?, exit_time=?, pnl=?, pnl_pips=?, status='closed'
                   WHERE trade_id=?""",
                (exit_price, exit_time, pnl, pnl_pips, trade_id),
            )
            conn.commit()
        finally:
            conn.close()

    def get_open_trades(self, instrument: Optional[str] = None) -> list[dict]:
        """未決済取引を取得"""
        conn = self._conn()
        try:
            query = "SELECT * FROM trades WHERE status='open'"
            params: list = []
            if instrument:
                query += " AND instrument=?"
                params.append(instrument)
            rows = conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_trade_history(
        self,
        instrument: Optional[str] = None,
        from_time: Optional[str] = None,
        to_time: Optional[str] = None,
    ) -> pd.DataFrame:
        """決済済み取引履歴を取得"""
        conn = self._conn()
        try:
            query = "SELECT * FROM trades WHERE status='closed'"
            params: list = []
            if instrument:
                query += " AND instrument=?"
                params.append(instrument)
            if from_time:
                query += " AND entry_time >= ?"
                params.append(from_time)
            if to_time:
                query += " AND entry_time < ?"
                params.append(to_time)
            query += " ORDER BY entry_time ASC"
            return pd.read_sql_query(query, conn, params=params)
        finally:
            conn.close()

    # --- Account Snapshots ---

    def upsert_account_snapshot(self, snapshot: dict):
        """口座スナップショットをupsert"""
        conn = self._conn()
        try:
            conn.execute(
                """INSERT INTO account_snapshots (snapshot_date, balance, unrealized_pnl, realized_pnl_daily, open_trade_count, nav)
                   VALUES (:snapshot_date, :balance, :unrealized_pnl, :realized_pnl_daily, :open_trade_count, :nav)
                   ON CONFLICT(snapshot_date)
                   DO UPDATE SET balance=excluded.balance, unrealized_pnl=excluded.unrealized_pnl,
                                 realized_pnl_daily=excluded.realized_pnl_daily, open_trade_count=excluded.open_trade_count,
                                 nav=excluded.nav""",
                snapshot,
            )
            conn.commit()
        finally:
            conn.close()

    # --- Fetch Log ---

    def log_fetch(self, log_entry: dict):
        """データ取得ログを記録"""
        conn = self._conn()
        try:
            conn.execute(
                """INSERT INTO fetch_log (instrument, granularity, from_time, to_time, candle_count, status, error_msg)
                   VALUES (:instrument, :granularity, :from_time, :to_time, :candle_count, :status, :error_msg)""",
                log_entry,
            )
            conn.commit()
        finally:
            conn.close()
