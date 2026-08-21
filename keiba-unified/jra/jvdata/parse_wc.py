# -*- coding: utf-8 -*-
"""WC（ウッドチップ調教）レコードのパーサ → SQLite woodテーブル

レイアウト（103バイト固定・2026-07-12にSonnetエージェントが実データ検証済み、
恒等式一致率99.87%・不一致は全件センチネル/部分計測で説明可能）:
  ヘッダはHCと共通: [0:2]WC [2:3]区分 [3:11]作成日 [11:12]トレセン
                    [12:20]調教日 [20:24]時刻 [24:34]血統登録番号
  [34:36] コースコード [36:37] 予備
  [37:103] F10累計(4)+lap(3) を F10→F2 で9組 → 最後にF1(3)。0.1秒単位・0埋め
  9999/999 はセンチネル（欠測）として無効化する

特徴量用に F4累計・F3累計・F1・lap2-1 を抽出（hanroと同じ意味論）。
"""
import sqlite3
import time

RAW = r"C:\Users\fcmdt\jvdata\raw\WOOD\WC.txt"
DB = r"C:\Users\fcmdt\jvdata\jvdata.sqlite"

# F4cum/lap3_2/F2cum/lap2_1/F1 の開始位置（37 + (10-k)*7）
def fpos(k):          # Fk累計(4桁)の開始オフセット
    return 37 + (10 - k) * 7

F1_POS = 37 + 9 * 7   # = 100


def to_sec(s):
    try:
        v = int(s)
    except ValueError:
        return None
    if v <= 0 or set(s.lstrip("0")) == {"9"} and len(s.lstrip("0")) >= 3:
        return None   # 0 or 999/9999センチネル
    return v / 10.0


def main():
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS wood (
        horse_id TEXT NOT NULL,
        train_date TEXT NOT NULL,
        train_time TEXT NOT NULL,
        tresen INTEGER,
        course TEXT,
        f6 REAL, f5 REAL, f4 REAL, f3 REAL, f2 REAL, f1 REAL, lap21 REAL,
        data_date TEXT,
        PRIMARY KEY (horse_id, train_date, train_time)
    )""")
    t0 = time.time()
    n = 0
    batch = []
    sql = """INSERT INTO wood VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(horse_id, train_date, train_time) DO UPDATE SET
          tresen=excluded.tresen, course=excluded.course,
          f6=excluded.f6, f5=excluded.f5, f4=excluded.f4, f3=excluded.f3,
          f2=excluded.f2, f1=excluded.f1, lap21=excluded.lap21,
          data_date=excluded.data_date
        WHERE excluded.data_date >= wood.data_date"""
    with open(RAW, encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\r\n")
            if len(line) != 103 or not line.startswith("WC"):
                continue
            n += 1
            batch.append((
                line[24:34], line[12:20], line[20:24],
                int(line[11:12]) if line[11:12].isdigit() else None,
                line[34:36],
                to_sec(line[fpos(6):fpos(6) + 4]),
                to_sec(line[fpos(5):fpos(5) + 4]),
                to_sec(line[fpos(4):fpos(4) + 4]),
                to_sec(line[fpos(3):fpos(3) + 4]),
                to_sec(line[fpos(2):fpos(2) + 4]),
                to_sec(line[F1_POS:F1_POS + 3]),
                to_sec(line[fpos(2) + 4:fpos(2) + 7]),   # lap2-1
                line[3:11],
            ))
            if len(batch) >= 50000:
                c.executemany(sql, batch)
                batch = []
    if batch:
        c.executemany(sql, batch)
    c.execute("CREATE INDEX IF NOT EXISTS idx_wood_horse ON wood(horse_id, train_date)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_wood_tresen_date ON wood(tresen, train_date)")
    conn.commit()
    rows = c.execute("SELECT COUNT(*) FROM wood").fetchone()[0]
    f4ok = c.execute("SELECT COUNT(*) FROM wood WHERE f4 IS NOT NULL").fetchone()[0]
    dmin, dmax = c.execute("SELECT MIN(train_date), MAX(train_date) FROM wood").fetchone()
    print(f"done: read={n} rows={rows} f4有効={f4ok} period={dmin}..{dmax} ({time.time()-t0:.0f}s)")
    conn.close()


if __name__ == "__main__":
    main()
