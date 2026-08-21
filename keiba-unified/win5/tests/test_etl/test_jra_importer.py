import sqlite3

import pytest

from database.connection import Database
from database.repository import Repository
from etl.jra_importer import JraImporter


@pytest.fixture
def jra_db(tmp_path):
    p = tmp_path / "jra.db"
    conn = sqlite3.connect(p)
    conn.executescript(
        """
        CREATE TABLE races (race_id TEXT, date TEXT, venue TEXT, race_number INT,
            name TEXT, class TEXT, distance INT, surface TEXT,
            track_condition TEXT, weather TEXT, head_count INT);
        CREATE TABLE results (race_id TEXT, horse_id TEXT, jockey_id TEXT, trainer_id TEXT,
            post_position INT, horse_number INT, weight_carried REAL, horse_weight INT,
            weight_change INT, finish_position INT, finish_time TEXT, margin TEXT,
            passing TEXT, last_3f REAL, odds_win REAL, popularity INT, sex_age TEXT, prize REAL);
        CREATE TABLE horses (horse_id TEXT, name TEXT, sex TEXT, birth_year INT,
            sire TEXT, broodmare_sire TEXT);
        CREATE TABLE jockeys (jockey_id TEXT, name TEXT);
        CREATE TABLE trainers (trainer_id TEXT, name TEXT);
        """
    )
    conn.execute(
        "INSERT INTO races VALUES "
        "('202606030101','2026-03-28','中山',1,'3歳未勝利','1勝',1200,'ダート','良','晴',16)"
    )
    conn.execute("INSERT INTO horses VALUES ('H1','サンプルホース','牝',2021,'父馬','母父')")
    conn.execute("INSERT INTO jockeys VALUES ('J1','テスト騎手')")
    conn.execute("INSERT INTO trainers VALUES ('T1','テスト調教師')")
    conn.execute(
        "INSERT INTO results VALUES "
        "('202606030101','H1','J1','T1',5,14,55.0,460,2,1,'1:11.0','-','3-3',38.5,4.2,3,'牝3',7000000)"
    )
    conn.commit()
    conn.close()
    return p


def test_import_maps_jra_to_win5(jra_db):
    db = Database(db_path=":memory:")
    db.initialize()
    repo = Repository(db)

    counts = JraImporter(jra_db, repo).run()

    assert counts["races"] == 1
    assert counts["results"] == 1

    race = repo.get_race("202606030101")
    assert race is not None
    assert race.venue_code == "06"
    assert race.venue_name == "中山"
    assert race.race_class == "1勝クラス"
    assert race.race_class_code == 3
    assert race.surface == "dirt"
    assert race.distance == 1200
    assert race.num_runners == 16

    results = repo.get_race_results("202606030101")
    assert len(results) == 1
    r = results[0]
    assert r.finish_position == 1
    assert r.odds == 4.2
    assert r.popularity == 3
    assert r.sex == "牝"
    assert r.age == 3
    assert r.horse_name == "サンプルホース"
    assert r.jockey_name == "テスト騎手"
    assert r.trainer_name == "テスト調教師"
    assert r.corner_positions == "3-3"
