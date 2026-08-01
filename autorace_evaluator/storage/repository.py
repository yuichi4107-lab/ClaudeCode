import sqlite3
from datetime import datetime


# ---------------------------------------------------------------- players

def upsert_player(conn: sqlite3.Connection, player_no: int, player_name: str) -> None:
    conn.execute(
        """INSERT INTO players (player_no, player_name, updated_at)
           VALUES (?, ?, ?)
           ON CONFLICT(player_no) DO UPDATE SET
               player_name = excluded.player_name,
               updated_at  = excluded.updated_at""",
        (player_no, player_name, datetime.now().isoformat()),
    )
    conn.commit()


# ------------------------------------------------------------------ races

def upsert_race(conn: sqlite3.Connection, race: dict) -> None:
    """races テーブルへ全カラムUPSERTする。race_id は必須。"""
    defaults = {
        "venue": None, "race_date": None, "race_no": None, "race_name": None,
        "distance": None, "weather": None, "track_status": None,
        "trial_track_status": None, "temperature": None, "track_temp": None,
        "meeting_id": None, "field_size": None, "source_url": None,
    }
    data = {**defaults, **race, "scraped_at": datetime.now().isoformat()}
    conn.execute(
        """INSERT OR REPLACE INTO races
            (race_id, venue, race_date, race_no, race_name, distance, weather,
             track_status, trial_track_status, temperature, track_temp,
             meeting_id, field_size, source_url, scraped_at)
           VALUES
            (:race_id, :venue, :race_date, :race_no, :race_name, :distance, :weather,
             :track_status, :trial_track_status, :temperature, :track_temp,
             :meeting_id, :field_size, :source_url, :scraped_at)""",
        data,
    )
    conn.commit()


def set_meeting_id(conn: sqlite3.Connection, race_id: str, meeting_id: str) -> None:
    conn.execute(
        "UPDATE races SET meeting_id = ? WHERE race_id = ?", (meeting_id, race_id)
    )
    conn.commit()


# --------------------------------------------------------------- entries

def upsert_entries(conn: sqlite3.Connection, race_id: str, entries: list[dict]) -> None:
    """結果API由来の列をUPSERTする。

    INSERT OR REPLACE(行の削除+再挿入)にすると、結果を再取得したとき
    Program API 由来の列(bike_class 等)が消えるため、ON CONFLICT DO UPDATE で
    結果由来の列だけを更新する。
    """
    defaults = {
        "player_no": None, "player_name": None, "handicap": None,
        "trial_time": None, "is_retrial": 0, "race_time": None,
        "last_lap_time": None, "st": None, "is_flying": 0,
        "finish_pos": None, "status": "finished", "violation_note": None,
    }
    for entry in entries:
        data = {**defaults, **entry, "race_id": race_id}
        conn.execute(
            """INSERT INTO race_entries
                (race_id, car_no, player_no, player_name, handicap, trial_time,
                 is_retrial, race_time, last_lap_time, st, is_flying, finish_pos,
                 status, violation_note)
               VALUES
                (:race_id, :car_no, :player_no, :player_name, :handicap, :trial_time,
                 :is_retrial, :race_time, :last_lap_time, :st, :is_flying, :finish_pos,
                 :status, :violation_note)
               ON CONFLICT(race_id, car_no) DO UPDATE SET
                 player_no = excluded.player_no,
                 player_name = excluded.player_name,
                 handicap = excluded.handicap,
                 trial_time = excluded.trial_time,
                 is_retrial = excluded.is_retrial,
                 race_time = excluded.race_time,
                 last_lap_time = excluded.last_lap_time,
                 st = excluded.st,
                 is_flying = excluded.is_flying,
                 finish_pos = excluded.finish_pos,
                 status = excluded.status,
                 violation_note = excluded.violation_note""",
            data,
        )
    conn.commit()


def update_entry_program_fields(
    conn: sqlite3.Connection, race_id: str, entries: list[dict]
) -> int:
    """出走表(Program)API由来の列のみ更新する。

    結果収集が先行している前提(存在しない race_id×car_no は0行更新)。
    更新できた行数を返す。
    """
    defaults = {
        "bike_class": None, "graduation_code": None, "player_rank": None,
        "age": None, "rate2": None, "rate3": None,
    }
    updated = 0
    for entry in entries:
        # パーサが事前予想用の追加キー(handicap等)を返しても、
        # ここで更新するのは Program 由来の6列のみに限定する
        picked = {k: entry.get(k) for k in list(defaults) + ["car_no"]}
        data = {**defaults, **picked, "race_id": race_id}
        cur = conn.execute(
            """UPDATE race_entries SET
                 bike_class = :bike_class,
                 graduation_code = :graduation_code,
                 player_rank = :player_rank,
                 age = :age,
                 rate2 = :rate2,
                 rate3 = :rate3
               WHERE race_id = :race_id AND car_no = :car_no""",
            data,
        )
        updated += cur.rowcount
    conn.commit()
    return updated


# --------------------------------------------------------------- payouts

def upsert_payouts(conn: sqlite3.Connection, race_id: str, payouts: list[dict]) -> None:
    for p in payouts:
        conn.execute(
            """INSERT OR REPLACE INTO payouts (race_id, bet_type, combination, payout)
               VALUES (?, ?, ?, ?)""",
            (race_id, p["bet_type"], p["combination"], p.get("payout")),
        )
    conn.commit()


# ------------------------------------------------------------- scrape_log

def log_scrape(
    conn: sqlite3.Connection,
    url: str,
    status_code: int,
    error_msg: str | None = None,
) -> None:
    conn.execute(
        """INSERT INTO scrape_log (url, scraped_at, status_code, error_msg)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(url) DO UPDATE SET
               scraped_at  = excluded.scraped_at,
               status_code = excluded.status_code,
               error_msg   = excluded.error_msg""",
        (url, datetime.now().isoformat(), status_code, error_msg),
    )
    conn.commit()


def clear_recent_not_found(
    conn: sqlite3.Connection, from_date: str, to_date: str
) -> int:
    """期間内日付をURLに含む「データなし」記録を削除して再チェック対象に戻す。

    結果未確定のうちに 4101 を踏んだレースは status_code=404 で記録され、
    was_scraped が完了扱いにして永久にスキップされてしまう。週次更新の
    直前に直近期間分を消して再チェックさせる。開催中止(4200)の記録は残す。
    更新行数を返す。
    """
    from datetime import date, timedelta

    start = date.fromisoformat(from_date)
    end = date.fromisoformat(to_date)
    deleted = 0
    d = start
    while d <= end:
        cur = conn.execute(
            r"""DELETE FROM scrape_log
                WHERE status_code = 404
                  AND (error_msg IS NULL OR error_msg NOT LIKE '%4200%')
                  AND url LIKE '%/' || ? || '\_%' ESCAPE '\'""",
            (d.isoformat(),),
        )
        deleted += cur.rowcount
        d += timedelta(days=1)
    conn.commit()
    return deleted


def was_scraped(conn: sqlite3.Connection, url: str) -> bool:
    """scrape_log に成功(200)または404の記録があれば True(再取得不要)。"""
    row = conn.execute(
        "SELECT status_code FROM scrape_log WHERE url = ?", (url,)
    ).fetchone()
    return row is not None and row["status_code"] in (200, 404)


# --------------------------------------------------------- query helpers

def get_races(
    conn: sqlite3.Connection,
    from_date: str,
    to_date: str,
    venue: str | None = None,
) -> list[sqlite3.Row]:
    sql = "SELECT * FROM races WHERE race_date BETWEEN ? AND ?"
    params: list = [from_date, to_date]
    if venue:
        sql += " AND venue = ?"
        params.append(venue)
    sql += " ORDER BY race_date, venue, race_no"
    return conn.execute(sql, params).fetchall()


def get_entries_with_race(
    conn: sqlite3.Connection,
    from_date: str,
    to_date: str,
    venue: str | None = None,
) -> list[sqlite3.Row]:
    """race_entries と races を JOIN し、race_no/race_date/venue/track_status/trial_track_status/distance/meeting_id を含めて返す。"""
    sql = """
    SELECT e.*, r.race_no, r.race_date, r.venue, r.track_status,
           r.trial_track_status, r.distance, r.meeting_id
    FROM race_entries e
    JOIN races r ON e.race_id = r.race_id
    WHERE r.race_date BETWEEN ? AND ?
    """
    params: list = [from_date, to_date]
    if venue:
        sql += " AND r.venue = ?"
        params.append(venue)
    sql += " ORDER BY r.race_date, e.race_id, e.car_no"
    return conn.execute(sql, params).fetchall()
