# -*- coding: utf-8 -*-
"""HC（坂路調教）レコードのパーサ → SQLite

レイアウト（58文字固定・実データの累積タイム整合で検証済み 2026-07-11）:
  [0:2]   "HC"
  [2:3]   データ区分（1=新規, 2=更新 等）
  [3:11]  データ作成年月日 YYYYMMDD
  [11:12] トレセン区分（0=美浦, 1=栗東）
  [12:20] 調教年月日 YYYYMMDD
  [20:24] 調教時刻 HHMM
  [24:34] 血統登録番号（= netkeiba horse_id と同一体系）
  [34:38] 4ハロン計 (0.1秒)   [38:41] ラップ4F-3F (0.1秒)
  [41:45] 3ハロン計           [45:48] ラップ3F-2F
  [48:52] 2ハロン計           [52:55] ラップ2F-1F
  [55:58] 1ハロン (0.1秒)

タイム0は計測なし。重複（同一馬・同一日時）はデータ作成日が新しい方を採用。
"""
import os
import sqlite3
import sys
import time

RAW = r"C:\Users\fcmdt\jvdata\raw\SLOP\HC.txt"
DB = r"C:\Users\fcmdt\jvdata\jvdata.sqlite"


def to_sec(s, digits):
    try:
        v = int(s)
    except ValueError:
        return None
    if v <= 0:
        return None
    return v / 10.0


def main():
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS hanro (
        horse_id TEXT NOT NULL,
        train_date TEXT NOT NULL,
        train_time TEXT NOT NULL,
        tresen INTEGER,
        f4 REAL, lap43 REAL, f3 REAL, lap32 REAL, f2 REAL, lap21 REAL, f1 REAL,
        data_date TEXT,
        PRIMARY KEY (horse_id, train_date, train_time)
    )""")
    t0 = time.time()
    n = ins = 0
    batch = []
    with open(RAW, encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\r\n")
            if len(line) != 58 or not line.startswith("HC"):
                continue
            n += 1
            data_date = line[3:11]
            tresen = line[11:12]
            tdate = line[12:20]
            ttime = line[20:24]
            hid = line[24:34]
            batch.append((
                hid, tdate, ttime,
                int(tresen) if tresen.isdigit() else None,
                to_sec(line[34:38], 4), to_sec(line[38:41], 3),
                to_sec(line[41:45], 4), to_sec(line[45:48], 3),
                to_sec(line[48:52], 4), to_sec(line[52:55], 3),
                to_sec(line[55:58], 3),
                data_date,
            ))
            if len(batch) >= 50000:
                c.executemany("""INSERT INTO hanro VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(horse_id, train_date, train_time) DO UPDATE SET
                      tresen=excluded.tresen, f4=excluded.f4, lap43=excluded.lap43,
                      f3=excluded.f3, lap32=excluded.lap32, f2=excluded.f2,
                      lap21=excluded.lap21, f1=excluded.f1, data_date=excluded.data_date
                    WHERE excluded.data_date >= hanro.data_date""", batch)
                ins += len(batch)
                batch = []
                if ins % 500000 == 0:
                    print(f"{ins} processed...", flush=True)
    if batch:
        c.executemany("""INSERT INTO hanro VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(horse_id, train_date, train_time) DO UPDATE SET
              tresen=excluded.tresen, f4=excluded.f4, lap43=excluded.lap43,
              f3=excluded.f3, lap32=excluded.lap32, f2=excluded.f2,
              lap21=excluded.lap21, f1=excluded.f1, data_date=excluded.data_date
            WHERE excluded.data_date >= hanro.data_date""", batch)
        ins += len(batch)
    c.execute("CREATE INDEX IF NOT EXISTS idx_hanro_horse ON hanro(horse_id, train_date)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_hanro_tresen_date ON hanro(tresen, train_date)")
    conn.commit()
    rows = c.execute("SELECT COUNT(*) FROM hanro").fetchone()[0]
    dmin, dmax = c.execute("SELECT MIN(train_date), MAX(train_date) FROM hanro").fetchone()
    f4ok = c.execute("SELECT COUNT(*) FROM hanro WHERE f4 IS NOT NULL").fetchone()[0]
    print(f"done: read={n} rows={rows} period={dmin}..{dmax} f4有効={f4ok} ({time.time()-t0:.0f}s)")
    conn.close()


if __name__ == "__main__":
    main()
