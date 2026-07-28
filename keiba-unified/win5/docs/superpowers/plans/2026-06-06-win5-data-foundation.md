# WIN5 Data Foundation (P0 ETL + P1 Events) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 既存JRAデータ（`keiba-unified/jra/data/keiba_live.db`, 2021-2026 / 17,457レース）を win5 自前DB（`win5.db`）へETL移植し、WIN5対象イベント（対象5R＋払戻＋キャリーオーバー）を収集して、勝率モデル学習に使えるデータ基盤を完成させる。

**Architecture:** win5 を自己完結に保つ（案B）。新規の「glueコード」は (1) jra→win5 スキーマ変換ETL、(2) WIN5イベント収集＋CSV突合検算 の2つだけ。既存の `Database`/`Repository`/dataclass models/`Win5TargetScraper` を再利用する。純粋関数（正規化・突合）はTDD、ネットワーク/全件移植は実行→件数検証で確認する。

**Tech Stack:** Python 3.11+, sqlite3（標準ライブラリ）, pytest, requests + beautifulsoup4（既存scraper）。LightGBM等のML依存はP2以降で導入。

**実行前提:** すべて `keiba-unified/win5/` をカレントとし、`PYTHONPATH=src`（または `python -m pytest`：`tests/conftest.py` が src をパス追加済み）で実行する。

**Git方針:** このリポジトリは Drive作業ツリー＋別所 `.git`、過去に機密誤pushの経緯あり。各タスクのコミットは **`keiba-unified/win5/` 配下のパスのみ** を `git add` する（広域 add 禁止）。**push はしない**（ユーザー判断）。

---

## File Structure

新規作成:
- `win5/src/etl/__init__.py` — ETLパッケージ初期化（空）
- `win5/src/etl/normalize.py` — 表記正規化の純粋関数（class/surface/sex_age/venue）
- `win5/src/etl/jra_importer.py` — `JraImporter`：jra DB を読み win5 Repository へupsert
- `win5/src/etl/win5_results_csv.py` — `win5_results_2026.csv` ローダ（突合検算用）
- `win5/src/etl/event_crosscheck.py` — イベント払戻のCSV突合（純粋関数）
- `win5/scripts/import_jra_data.py` — ETL実行CLI（全件移植）
- `win5/scripts/collect_win5_events.py` — WIN5イベント収集CLI（Sunday走査＋突合）
- `win5/scripts/verify_import.py` — 移植結果の件数検証CLI
- `win5/tests/test_etl/__init__.py`
- `win5/tests/test_etl/test_normalize.py`
- `win5/tests/test_etl/test_jra_importer.py`
- `win5/tests/test_etl/test_win5_results_csv.py`
- `win5/tests/test_etl/test_event_crosscheck.py`

参照（変更しない既存資産）:
- `win5/src/database/connection.py`（`Database(db_path).initialize()` で schema 生成）
- `win5/src/database/repository.py`（`upsert_race` / `bulk_upsert_race_results` / `upsert_horse` / `upsert_jockey` / `upsert_trainer` / `upsert_win5_event` / `get_race` / `get_race_results` / `upsert_win5_event` / `get_win5_events_in_range`）
- `win5/src/database/models.py`（`Race` / `RaceResult` / `Horse` / `Jockey` / `Trainer` / `Win5Event`）
- `win5/src/config/venues.py`（`VENUE_NAME_TO_CODE` / `RACE_CLASS` / `SURFACE_TYPES`）
- `win5/src/scraper/win5_target.py`（`Win5TargetScraper.scrape(date) -> Win5Event | None`）

---

## Task 0: リコンサイル（OneDrive版とkeiba-unified版の統合）

**Files:**
- 参照のみ（差分確認）。`archive/` への退避はコピー操作。

- [ ] **Step 1: 2コピーの差分を取得**

Run:
```bash
cd "g:/マイドライブ/YNFactory-cc/keiba-unified/win5"
diff -rq src "C:/Users/fcmdt/OneDrive/デスクトップ/ClaudeCode-claude-win-prediction-model-Izfwm/ClaudeCode-claude-win-prediction-model-Izfwm/win5_predictor/src"
```
Expected: 差分ファイル一覧。**keiba-unified側に無い/古いファイルがあれば**そのファイルだけを手動でコピーして取り込む（src全体の上書きはしない）。差分が無ければそのまま次へ。

- [ ] **Step 2: OneDrive版を archive へ退避（削除しない）**

Run:
```bash
mkdir -p "g:/マイドライブ/YNFactory-cc/keiba-unified/win5/archive"
cp -r "C:/Users/fcmdt/OneDrive/デスクトップ/ClaudeCode-claude-win-prediction-model-Izfwm/ClaudeCode-claude-win-prediction-model-Izfwm/win5_predictor" "g:/マイドライブ/YNFactory-cc/keiba-unified/win5/archive/win5_predictor_onedrive_20260606"
```
Expected: 退避完了。以後の正本は `keiba-unified/win5/`。

> 注: `archive/` は `.gitignore` 済みか確認し、未登録なら `win5/.gitignore` に `archive/` を追記（容量肥大とコミット汚染を防ぐ）。

---

## Task 1: ETLパッケージの雛形

**Files:**
- Create: `win5/src/etl/__init__.py`
- Create: `win5/tests/test_etl/__init__.py`

- [ ] **Step 1: パッケージ初期化ファイルを作成**

`win5/src/etl/__init__.py`:
```python
"""jra DB → win5 DB のETL・WIN5イベント収集モジュール"""
```

`win5/tests/test_etl/__init__.py`:
```python
```

- [ ] **Step 2: Commit**

```bash
git add win5/src/etl/__init__.py win5/tests/test_etl/__init__.py
git commit -m "chore(win5): add etl package skeleton"
```

---

## Task 2: 表記正規化の純粋関数（normalize.py）

**Files:**
- Create: `win5/src/etl/normalize.py`
- Test: `win5/tests/test_etl/test_normalize.py`

- [ ] **Step 1: 失敗するテストを書く**

`win5/tests/test_etl/test_normalize.py`:
```python
from etl.normalize import (
    normalize_class,
    split_sex_age,
    normalize_surface,
    venue_code_from_race_id,
)


def test_normalize_class_aliases():
    assert normalize_class("1勝") == ("1勝クラス", 3)
    assert normalize_class("2勝") == ("2勝クラス", 4)
    assert normalize_class("3勝") == ("3勝クラス", 5)
    assert normalize_class("OP") == ("オープン", 6)
    assert normalize_class("G1") == ("G1", 10)
    assert normalize_class("未勝利") == ("未勝利", 2)
    assert normalize_class("新馬") == ("新馬", 1)
    assert normalize_class("") == ("", 0)


def test_split_sex_age():
    assert split_sex_age("牝3") == ("牝", 3)
    assert split_sex_age("牡5") == ("牡", 5)
    assert split_sex_age("セ7") == ("セ", 7)
    assert split_sex_age("") == ("", 0)


def test_normalize_surface():
    assert normalize_surface("ダート") == "dirt"
    assert normalize_surface("芝") == "turf"
    assert normalize_surface("") == ""


def test_venue_code_from_race_id():
    assert venue_code_from_race_id("202606030101") == "06"
    assert venue_code_from_race_id("") == ""
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `python -m pytest tests/test_etl/test_normalize.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'etl.normalize'`）

- [ ] **Step 3: 最小実装を書く**

`win5/src/etl/normalize.py`:
```python
"""jra DBの表記を win5 の語彙へ正規化する純粋関数群"""

from config.venues import VENUE_NAME_TO_CODE, RACE_CLASS, SURFACE_TYPES

# jra の class 表記 → win5 RACE_CLASS のキー
CLASS_ALIASES = {
    "1勝": "1勝クラス",
    "2勝": "2勝クラス",
    "3勝": "3勝クラス",
    "OP": "オープン",
}


def normalize_class(jra_class: str) -> tuple[str, int]:
    """jra の class 文字列 → (win5クラス名, クラスコード)"""
    name = CLASS_ALIASES.get((jra_class or "").strip(), (jra_class or "").strip())
    return name, RACE_CLASS.get(name, 0)


def split_sex_age(sex_age: str) -> tuple[str, int]:
    """'牝3' → ('牝', 3)。空なら ('', 0)"""
    s = (sex_age or "").strip()
    if not s:
        return "", 0
    sex = s[0]
    digits = "".join(ch for ch in s[1:] if ch.isdigit())
    return sex, int(digits) if digits else 0


def normalize_surface(surface: str) -> str:
    """'ダート'→'dirt', '芝'→'turf'。未知は ''"""
    return SURFACE_TYPES.get((surface or "").strip(), "")


def venue_code_from_race_id(race_id: str) -> str:
    """netkeiba 12桁レースIDの会場コード2桁を返す（例: '2026 06 ...' → '06'）"""
    return race_id[4:6] if race_id and len(race_id) >= 6 else ""


def venue_name_to_code(venue_name: str) -> str:
    """会場名 → コード。未知は ''"""
    return VENUE_NAME_TO_CODE.get((venue_name or "").strip(), "")
```

- [ ] **Step 4: テストが通ることを確認**

Run: `python -m pytest tests/test_etl/test_normalize.py -v`
Expected: PASS（5テスト）

> もし `RACE_CLASS` に `"1勝クラス"` 等のキーが無くPASSしない場合は、`config/venues.py` の `RACE_CLASS` を確認し、テストの期待コードを実際の値へ合わせる（venues.py が真実）。

- [ ] **Step 5: Commit**

```bash
git add win5/src/etl/normalize.py win5/tests/test_etl/test_normalize.py
git commit -m "feat(win5-etl): add jra->win5 value normalizers"
```

---

## Task 3: JRA→win5 インポータ（jra_importer.py）

**Files:**
- Create: `win5/src/etl/jra_importer.py`
- Test: `win5/tests/test_etl/test_jra_importer.py`

- [ ] **Step 1: 失敗するテストを書く（小さなjra相当DBを作って移植検証）**

`win5/tests/test_etl/test_jra_importer.py`:
```python
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
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `python -m pytest tests/test_etl/test_jra_importer.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'etl.jra_importer'`）

- [ ] **Step 3: 最小実装を書く**

`win5/src/etl/jra_importer.py`:
```python
"""jra DB（keiba_live.db）を読み、win5 Repository へ変換移植する"""

import logging
import sqlite3
from datetime import date

from database.models import Horse, Jockey, Race, RaceResult, Trainer
from etl.normalize import (
    normalize_class,
    normalize_surface,
    split_sex_age,
    venue_code_from_race_id,
)

logger = logging.getLogger(__name__)


class JraImporter:
    """jra DB → win5 DB の一括/差分インポート"""

    def __init__(self, jra_db_path, repository):
        self.jra_db_path = str(jra_db_path)
        self.repo = repository

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.jra_db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def import_reference(self, conn) -> None:
        for row in conn.execute("SELECT horse_id, name, sex, birth_year FROM horses"):
            self.repo.upsert_horse(
                Horse(
                    horse_id=row["horse_id"],
                    horse_name=row["name"] or "",
                    sex=row["sex"] or "",
                    birth_year=row["birth_year"] or 0,
                )
            )
        for row in conn.execute("SELECT jockey_id, name FROM jockeys"):
            self.repo.upsert_jockey(
                Jockey(jockey_id=row["jockey_id"], jockey_name=row["name"] or "")
            )
        for row in conn.execute("SELECT trainer_id, name FROM trainers"):
            self.repo.upsert_trainer(
                Trainer(trainer_id=row["trainer_id"], trainer_name=row["name"] or "")
            )

    def import_races(self, conn) -> int:
        count = 0
        sql = (
            "SELECT race_id, date, venue, race_number, name, class, distance, "
            "surface, track_condition, weather, head_count FROM races"
        )
        for row in conn.execute(sql):
            cls_name, cls_code = normalize_class(row["class"] or "")
            self.repo.upsert_race(
                Race(
                    race_id=row["race_id"],
                    race_date=date.fromisoformat(row["date"]),
                    venue_code=venue_code_from_race_id(row["race_id"]),
                    venue_name=row["venue"] or "",
                    race_number=row["race_number"] or 0,
                    race_name=row["name"] or "",
                    surface=normalize_surface(row["surface"] or ""),
                    distance=row["distance"] or 0,
                    track_condition=row["track_condition"] or "",
                    weather=row["weather"] or "",
                    race_class=cls_name,
                    race_class_code=cls_code,
                    num_runners=row["head_count"] or 0,
                )
            )
            count += 1
        return count

    def _name_map(self, conn, table, id_col) -> dict:
        return {
            row[id_col]: (row["name"] or "")
            for row in conn.execute(f"SELECT {id_col}, name FROM {table}")
        }

    def import_results(self, conn) -> int:
        horse_names = self._name_map(conn, "horses", "horse_id")
        jockey_names = self._name_map(conn, "jockeys", "jockey_id")
        trainer_names = self._name_map(conn, "trainers", "trainer_id")

        count = 0
        batch: list[RaceResult] = []
        current_rid = None
        for row in conn.execute("SELECT * FROM results ORDER BY race_id"):
            if current_rid is not None and row["race_id"] != current_rid and batch:
                self.repo.bulk_upsert_race_results(batch)
                batch = []
            current_rid = row["race_id"]
            sex, age = split_sex_age(row["sex_age"] or "")
            batch.append(
                RaceResult(
                    race_id=row["race_id"],
                    horse_id=row["horse_id"],
                    horse_name=horse_names.get(row["horse_id"], ""),
                    finish_position=row["finish_position"],
                    post_position=row["post_position"] or 0,
                    horse_number=row["horse_number"] or 0,
                    sex=sex,
                    age=age,
                    weight_carried=row["weight_carried"] or 0.0,
                    jockey_id=row["jockey_id"] or "",
                    jockey_name=jockey_names.get(row["jockey_id"], ""),
                    trainer_id=row["trainer_id"] or "",
                    trainer_name=trainer_names.get(row["trainer_id"], ""),
                    last_3f=row["last_3f"],
                    horse_weight=row["horse_weight"],
                    weight_change=row["weight_change"],
                    odds=row["odds_win"],
                    popularity=row["popularity"],
                    margin=row["margin"] or "",
                    corner_positions=row["passing"] or "",
                    prize_money=row["prize"] or 0.0,
                )
            )
            count += 1
        if batch:
            self.repo.bulk_upsert_race_results(batch)
        return count

    def run(self) -> dict:
        conn = self._connect()
        try:
            self.import_reference(conn)
            n_races = self.import_races(conn)
            n_results = self.import_results(conn)
        finally:
            conn.close()
        logger.info("Imported races=%d results=%d", n_races, n_results)
        return {"races": n_races, "results": n_results}
```

- [ ] **Step 4: テストが通ることを確認**

Run: `python -m pytest tests/test_etl/test_jra_importer.py -v`
Expected: PASS

> もし `RaceResult` に `margin` 引数が無い等で `TypeError` が出たら、`database/models.py` の `RaceResult` 定義に合わせて該当行を削除/改名する（models.py が真実）。

- [ ] **Step 5: Commit**

```bash
git add win5/src/etl/jra_importer.py win5/tests/test_etl/test_jra_importer.py
git commit -m "feat(win5-etl): add JraImporter mapping jra DB to win5 schema"
```

---

## Task 4: WIN5結果CSVローダ（win5_results_csv.py）

**Files:**
- Create: `win5/src/etl/win5_results_csv.py`
- Test: `win5/tests/test_etl/test_win5_results_csv.py`

- [ ] **Step 1: 失敗するテストを書く**

`win5/tests/test_etl/test_win5_results_csv.py`:
```python
from datetime import date

from etl.win5_results_csv import load_win5_results


def test_load_skips_comments_and_parses(tmp_path):
    p = tmp_path / "w.csv"
    p.write_text(
        "# JRA WIN5 results 2026 -- comment\n"
        "# another comment\n"
        "date,race,grade,payout_yen,hit_tickets,p1,p2,p3,p4,p5,pops_verified\n"
        "2026-01-04,日刊スポーツ賞中山金杯,G3,2775800,184,5,2,1,4,7,True\n"
        "2026-01-11,キャリーオーバー回,G3,,0,1,1,1,1,1,False\n",
        encoding="utf-8",
    )
    rows = load_win5_results(p)
    assert rows[0] == {"date": date(2026, 1, 4), "payout_yen": 2775800.0}
    assert rows[1]["date"] == date(2026, 1, 11)
    assert rows[1]["payout_yen"] is None
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `python -m pytest tests/test_etl/test_win5_results_csv.py -v`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 最小実装を書く**

`win5/src/etl/win5_results_csv.py`:
```python
"""win5_results_2026.csv（手動転記の実WIN5払戻）を読み込む。突合検算に使う。"""

import csv
from datetime import date


def load_win5_results(csv_path) -> list[dict]:
    """先頭の # コメント行を除外し、date と payout_yen を取り出す。

    payout_yen が空欄（キャリーオーバー/不的中）の場合は None。
    """
    with open(csv_path, encoding="utf-8") as f:
        lines = [ln for ln in f if not ln.lstrip().startswith("#")]
    reader = csv.DictReader(lines)
    out: list[dict] = []
    for r in reader:
        d = (r.get("date") or "").strip()
        if not d:
            continue
        pay = (r.get("payout_yen") or "").strip()
        out.append(
            {
                "date": date.fromisoformat(d),
                "payout_yen": float(pay) if pay else None,
            }
        )
    return out
```

- [ ] **Step 4: テストが通ることを確認**

Run: `python -m pytest tests/test_etl/test_win5_results_csv.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add win5/src/etl/win5_results_csv.py win5/tests/test_etl/test_win5_results_csv.py
git commit -m "feat(win5-etl): add win5_results_2026 csv loader"
```

---

## Task 5: イベント払戻のCSV突合（event_crosscheck.py）

**Files:**
- Create: `win5/src/etl/event_crosscheck.py`
- Test: `win5/tests/test_etl/test_event_crosscheck.py`

- [ ] **Step 1: 失敗するテストを書く**

`win5/tests/test_etl/test_event_crosscheck.py`:
```python
from datetime import date

from database.models import Win5Event
from etl.event_crosscheck import crosscheck_payouts


def test_crosscheck_detects_mismatch():
    events = [
        Win5Event(event_id="20260104", event_date=date(2026, 1, 4), payout=2775800.0),
        Win5Event(event_id="20260111", event_date=date(2026, 1, 11), payout=999.0),
        Win5Event(event_id="20260118", event_date=date(2026, 1, 18), payout=None),
    ]
    csv_rows = [
        {"date": date(2026, 1, 4), "payout_yen": 2775800.0},   # 一致
        {"date": date(2026, 1, 11), "payout_yen": 5000.0},     # 不一致
        {"date": date(2026, 1, 18), "payout_yen": None},       # 両方None=一致
    ]
    mm = crosscheck_payouts(events, csv_rows)
    assert mm == [(date(2026, 1, 11), 999.0, 5000.0)]
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `python -m pytest tests/test_etl/test_event_crosscheck.py -v`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 最小実装を書く**

`win5/src/etl/event_crosscheck.py`:
```python
"""収集した Win5Event の払戻を win5_results_2026.csv と突合する純粋関数"""


def crosscheck_payouts(events, csv_rows, tol: float = 1.0) -> list[tuple]:
    """日付一致するイベントの payout を CSV と比較し、不一致のみ返す。

    返り値: [(date, event_payout, csv_payout), ...]
    両方 None は一致扱い。片方のみ None、または差が tol 超は不一致。
    """
    csv_by_date = {r["date"]: r["payout_yen"] for r in csv_rows}
    mismatches: list[tuple] = []
    for ev in events:
        d = ev.event_date
        if d not in csv_by_date:
            continue
        csv_pay = csv_by_date[d]
        ev_pay = ev.payout
        if csv_pay is None and ev_pay is None:
            continue
        if csv_pay is None or ev_pay is None:
            mismatches.append((d, ev_pay, csv_pay))
            continue
        if abs(float(ev_pay) - float(csv_pay)) > tol:
            mismatches.append((d, ev_pay, csv_pay))
    return mismatches
```

- [ ] **Step 4: テストが通ることを確認**

Run: `python -m pytest tests/test_etl/test_event_crosscheck.py -v`
Expected: PASS

- [ ] **Step 5: ETL全テストをまとめて実行**

Run: `python -m pytest tests/test_etl/ -v`
Expected: PASS（normalize 5 + importer 1 + csv 1 + crosscheck 1）

- [ ] **Step 6: Commit**

```bash
git add win5/src/etl/event_crosscheck.py win5/tests/test_etl/test_event_crosscheck.py
git commit -m "feat(win5-etl): add event payout crosscheck against csv"
```

---

## Task 6: ETL実行CLI（import_jra_data.py）と検証CLI（verify_import.py）

**Files:**
- Create: `win5/scripts/import_jra_data.py`
- Create: `win5/scripts/verify_import.py`

- [ ] **Step 1: ETL実行スクリプトを書く**

`win5/scripts/import_jra_data.py`:
```python
"""jra/keiba_live.db を win5.db へ移植する実行スクリプト。

使い方:
  cd keiba-unified/win5
  PYTHONPATH=src python scripts/import_jra_data.py \
      --jra-db ../jra/data/keiba_live.db --win5-db data/win5.db
"""

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from database.connection import Database  # noqa: E402
from database.repository import Repository  # noqa: E402
from etl.jra_importer import JraImporter  # noqa: E402


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--jra-db", default="../jra/data/keiba_live.db")
    ap.add_argument("--win5-db", default="data/win5.db")
    args = ap.parse_args()

    db = Database(db_path=args.win5_db)
    db.initialize()
    repo = Repository(db)

    counts = JraImporter(args.jra_db, repo).run()
    print(f"DONE: races={counts['races']} results={counts['results']}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 検証スクリプトを書く**

`win5/scripts/verify_import.py`:
```python
"""win5.db への移植結果を件数・整合で検証する。"""

import argparse
import sqlite3


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--win5-db", default="data/win5.db")
    args = ap.parse_args()

    c = sqlite3.connect(args.win5_db)
    races = c.execute("SELECT COUNT(*) FROM races").fetchone()[0]
    results = c.execute("SELECT COUNT(*) FROM race_results").fetchone()[0]
    winners = c.execute("SELECT COUNT(*) FROM race_results WHERE finish_position=1").fetchone()[0]
    null_odds = c.execute("SELECT COUNT(*) FROM race_results WHERE odds IS NULL").fetchone()[0]
    dmin, dmax = c.execute("SELECT MIN(race_date), MAX(race_date) FROM races").fetchone()
    c.close()

    print(f"races={races} results={results} winners(1着)={winners}")
    print(f"date_range={dmin}..{dmax} null_odds={null_odds}")
    assert races > 15000, "races が想定（>15000）未満。移植失敗の可能性"
    assert results > 200000, "results が想定（>200000）未満"
    assert winners >= races * 0.9, "1着レコード数が不足（レースあたり1着が欠損）"
    print("VERIFY OK")


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: 本番ETLを実行（全件移植）**

Run:
```bash
PYTHONPATH=src python scripts/import_jra_data.py --jra-db ../jra/data/keiba_live.db --win5-db data/win5.db
```
Expected: `DONE: races=17457 results=240330`（件数はjra側の現状に一致。数百件の前後差は許容）

> 注: 既存 win5.db には89レースの旧データが入っている。`upsert_*` は INSERT ... ON CONFLICT 系のため上書き更新される。完全に作り直したい場合は事前に `data/win5.db` を削除して再実行（`initialize()` がスキーマ再生成）。

- [ ] **Step 4: 移植結果を検証**

Run:
```bash
python scripts/verify_import.py --win5-db data/win5.db
```
Expected: `VERIFY OK`、`date_range=2021-01-05..2026-03-28` 付近、`null_odds` は少数（中止・除外馬由来）。

- [ ] **Step 5: Commit**

```bash
git add win5/scripts/import_jra_data.py win5/scripts/verify_import.py
git commit -m "feat(win5-etl): add jra import + verification CLIs"
```

> **P0 完了条件（spec §7）**: win5.db に2021-2026のraces/resultsが入り、件数がjra側と整合。← Step 4 の `VERIFY OK` で満たす。

---

## Task 7: WIN5イベント収集CLI（collect_win5_events.py）

**Files:**
- Create: `win5/scripts/collect_win5_events.py`

- [ ] **Step 1: スクレイパーを単一日付で疎通確認（全件ループ前の安全確認）**

Run:
```bash
PYTHONPATH=src python -c "
from datetime import date
from scraper.win5_target import Win5TargetScraper
ev = Win5TargetScraper().scrape(date(2026,3,22))
print('races:', [ev.race1_id, ev.race2_id, ev.race3_id, ev.race4_id, ev.race5_id] if ev else None)
print('payout:', ev.payout if ev else None)
"
```
Expected: 5本のrace_id（12桁）と払戻が表示される。

> もし race_id が5本未満 or payout が None の場合、netkeiba のページ構造が `win5_target.py` の CSSセレクタ（`.Win5_Result, .pay_block` 等）と乖離している。**ここで停止し、`win5_target.py` のセレクタ/正規表現を現行ページに合わせて修正**してから次へ進む（このセレクタ修正は本タスクの一部）。

- [ ] **Step 2: 収集スクリプトを書く**

`win5/scripts/collect_win5_events.py`:
```python
"""WIN5対象イベント（対象5R＋払戻＋CO）を期間収集し win5_events へ保存、CSV突合する。

使い方:
  cd keiba-unified/win5
  PYTHONPATH=src python scripts/collect_win5_events.py --start 2021-01-01 --end 2026-05-31
"""

import argparse
import logging
import sys
import time
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from config.settings import REQUEST_INTERVAL_SEC  # noqa: E402
from database.connection import Database  # noqa: E402
from database.repository import Repository  # noqa: E402
from etl.event_crosscheck import crosscheck_payouts  # noqa: E402
from etl.win5_results_csv import load_win5_results  # noqa: E402
from scraper.win5_target import Win5TargetScraper  # noqa: E402


def sundays(start: date, end: date):
    d = start + timedelta(days=(6 - start.weekday()) % 7)  # 次の日曜
    while d <= end:
        yield d
        d += timedelta(days=7)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--win5-db", default="data/win5.db")
    ap.add_argument("--csv", default="data/win5_results_2026.csv")
    args = ap.parse_args()

    db = Database(db_path=args.win5_db)
    db.initialize()
    repo = Repository(db)
    scraper = Win5TargetScraper()

    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)

    collected = []
    for d in sundays(start, end):
        ev = scraper.scrape(d)
        if ev is None:
            logging.info("no WIN5 on %s", d)
        else:
            repo.upsert_win5_event(ev)
            collected.append(ev)
        time.sleep(REQUEST_INTERVAL_SEC)

    print(f"collected events: {len(collected)}")

    csv_path = Path(args.csv)
    if csv_path.exists():
        mismatches = crosscheck_payouts(collected, load_win5_results(csv_path))
        if mismatches:
            print(f"CROSSCHECK MISMATCHES ({len(mismatches)}):")
            for d, ev_pay, csv_pay in mismatches:
                print(f"  {d}: event={ev_pay} csv={csv_pay}")
        else:
            print("CROSSCHECK OK (no mismatches on overlapping dates)")


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: 2026年の重複期間で小さく収集して突合確認**

Run:
```bash
PYTHONPATH=src python scripts/collect_win5_events.py --start 2026-01-01 --end 2026-05-31
```
Expected: `collected events: ~20`、`CROSSCHECK OK`（または少数の不一致が列挙される）。

> **P1 合格条件（spec §7）**: csv突合一致（2026年1〜5月の払戻が一致）。不一致が出た場合は、その日付の payout 抽出ロジック（`win5_target.py`）を修正して再実行する。

- [ ] **Step 4: 全期間（2021-2026）を収集**

Run:
```bash
PYTHONPATH=src python scripts/collect_win5_events.py --start 2021-01-01 --end 2026-05-31
```
Expected: `collected events: ~250`（約5年×年間50前後）。所要 ~5〜10分（レート制限1.2秒/件）。

- [ ] **Step 5: win5_events の件数と対象5Rがracesに存在するか検証**

Run:
```bash
python -c "
import sqlite3
c=sqlite3.connect('data/win5.db')
n=c.execute('SELECT COUNT(*) FROM win5_events').fetchone()[0]
# 対象5RがすべてレースとしてDBに存在するか（リンク健全性）
miss=c.execute('''
  SELECT COUNT(*) FROM win5_events e
  WHERE NOT EXISTS (SELECT 1 FROM races r WHERE r.race_id=e.race5_id)
''').fetchone()[0]
print(f'win5_events={n} race5_missing_in_races={miss}')
c.close()
"
```
Expected: `win5_events` が ~250、`race5_missing_in_races` は 0 に近い（0が理想。多い場合は race_id 抽出または移植期間の不足を疑う）。

- [ ] **Step 6: Commit**

```bash
git add win5/scripts/collect_win5_events.py
git commit -m "feat(win5-etl): add WIN5 event collector with csv crosscheck"
```

> **P1 完了条件（spec §7）**: win5_events 2021-2026 充足＋csv突合一致 ← Step 3〜5 で満たす。

---

## Task 8: データ基盤の最終確認とドキュメント

**Files:**
- Modify: `win5/README.md`（データ基盤の作り方セクションを追記）

- [ ] **Step 1: 全ETLテストを再実行**

Run: `python -m pytest tests/test_etl/ -v`
Expected: 全PASS

- [ ] **Step 2: README にデータ基盤手順を追記**

`win5/README.md` の「## データ」セクション直後に以下を追記:
```markdown
## データ基盤の構築（P0/P1）

既存JRAデータ（`../jra/data/keiba_live.db`）を流用して win5.db を構築する。

```bash
# P0: JRAデータをwin5.dbへ移植
PYTHONPATH=src python scripts/import_jra_data.py
python scripts/verify_import.py            # VERIFY OK を確認

# P1: WIN5対象イベントを収集（対象5R＋払戻＋CO）
PYTHONPATH=src python scripts/collect_win5_events.py --start 2021-01-01 --end 2026-05-31
```

> jra DBのテキストはUTF-8（特殊デコード不要）。class表記は `1勝→1勝クラス` 等に正規化済み。
> オッズは確定オッズ（odds_win）を事前EVの代理に使う既知の制約あり。
```

- [ ] **Step 3: Commit**

```bash
git add win5/README.md
git commit -m "docs(win5): document data foundation build steps"
```

---

## 完了の定義（このプランのスコープ）

- [ ] `tests/test_etl/` 全PASS
- [ ] `scripts/verify_import.py` が `VERIFY OK`（win5.dbに2021-2026の17k+レース・240k+着順）
- [ ] `win5_events` が ~250件、対象5RがracesにリンクOK、2026年1〜5月のcsv突合一致

これらが満たされたら、**P2（勝率モデル：1着ラベル＋walk-forward＋較正＋人気ベースライン超え）以降を別プランとして作成**する（実データの分布を見てから書くことで、投機的でない具体的なタスクにする）。

---

## Self-Review メモ（spec照合）

- spec §3 リコンサイル → Task 0 で実装
- spec §5.1 スキーマ・マッピング → Task 2/3（normalize + JraImporter）で実装
- spec §1.2 UTF-8/CP932 → 調査で UTF-8 確定、特殊デコード不要（normalizeに反映）
- spec §7 P0 合格基準（件数整合）→ Task 6 verify_import
- spec §7 P1 合格基準（csv突合一致）→ Task 7 Step 3
- spec §6 過学習対策（人気ベースライン超え等）→ **P2プランで実装**（本プランのスコープ外）
- spec §9 オッズ近似の既知制約 → README/Task 8 に明記
