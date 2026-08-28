"""節(開催)IDの導出。

同一会場でレース日付が暦日で連続している区間を1つの節とみなし、
meeting_id = "{venue}_{節初日}" を割り当てる。1日でも空くと別節扱い
(順延・中止で飛んだ日は整備力の前日ペア対象外になる安全側の挙動)。
"""

from datetime import date, timedelta

import pandas as pd


def derive_meeting_ids(races_df: pd.DataFrame) -> dict:
    """races DataFrame (race_id, venue, race_date) から
    {race_id: meeting_id} を返す純関数。evaluate 時に毎回再計算する冪等処理。"""
    result = {}
    if races_df.empty:
        return result
    for venue, group in races_df.groupby("venue"):
        dates = sorted({d for d in group["race_date"] if d})
        meeting_start = {}
        prev = None
        start = None
        for ds in dates:
            cur = date.fromisoformat(ds)
            if prev is None or (cur - prev) > timedelta(days=1):
                start = ds
            meeting_start[ds] = start
            prev = cur
        for _, row in group.iterrows():
            ds = row["race_date"]
            if ds in meeting_start:
                result[row["race_id"]] = f"{venue}_{meeting_start[ds]}"
    return result


def update_meeting_ids(conn) -> int:
    """meeting_id 未設定の races 行に日付連続性から導出したIDを書き込む。

    スクレイパーが API の periodStartDate から meeting_id を保存済みの行は
    そのまま(公式の節情報を優先)。返り値は導出対象になった行数。
    """
    races = pd.read_sql_query(
        "SELECT race_id, venue, race_date FROM races "
        "WHERE meeting_id IS NULL OR meeting_id = ''",
        conn,
    )
    mapping = derive_meeting_ids(races)
    cur = conn.cursor()
    cur.executemany(
        "UPDATE races SET meeting_id = ? WHERE race_id = ?",
        [(mid, rid) for rid, mid in mapping.items()],
    )
    conn.commit()
    return len(mapping)
