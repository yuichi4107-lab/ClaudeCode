from __future__ import annotations

from dataclasses import replace

from rakuten_room_auto import runner as runner_module
from rakuten_room_auto.browser import BrowserAutomationError
from rakuten_room_auto.config import ReplenishConfig, load_config
from rakuten_room_auto.ledger import Ledger
from rakuten_room_auto.replenish import contains_exaggerated_claim
from rakuten_room_auto.runner import RoomAutomationRunner
from rakuten_room_auto.sheets import SheetTable


class FakeSheet:
    def __init__(self, table: SheetTable):
        self.table = table
        self.appended: list[dict[str, str]] = []
        self.updated: list[tuple[int, dict[str, str]]] = []

    def read_table(self) -> SheetTable:
        return self.table

    def append_row_fields(self, header, fields) -> None:
        self.appended.append(dict(fields))

    def update_row_fields(self, row, updates) -> None:
        self.updated.append((row.row_number, dict(updates)))


class FakeBrowser:
    items_by_url: dict[str, list[dict[str, str]]] = {}
    fail_urls: set[str] = set()

    def __init__(self, config):
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return None

    def fetch_ranking_items(self, ranking_url, limit=20):
        if ranking_url in self.fail_urls:
            raise BrowserAutomationError("ランキングページが開けません (HTTP 503)。")
        return list(self.items_by_url.get(ranking_url, []))[:limit]


def make_table(config, statuses: list[str]) -> SheetTable:
    columns = config.sheet.columns
    values = [[columns["product_url"], columns["description"], columns["status"]]]
    for index, status in enumerate(statuses):
        values.append([f"https://item.rakuten.co.jp/shop/exist-{index}/", "既存の紹介文", status])
    return SheetTable.from_values(values)


def make_runner(config, table, tmp_path) -> tuple[RoomAutomationRunner, FakeSheet]:
    instance = RoomAutomationRunner.__new__(RoomAutomationRunner)
    instance.config = config
    sheet = FakeSheet(table)
    instance.sheet = sheet
    instance.ledger = Ledger(tmp_path / "ledger.jsonl")
    instance.generator = None
    return instance, sheet


DISTINCT_TITLES = [
    "収納ボックス 折りたたみ ふた付き キャスター",
    "ヒツジのいらない枕 健康グッズ ギフト",
    "ニトリル手袋 使い捨て 料理 掃除",
    "とろとろケット 洗える タオルケット",
    "突っ張り棒 ハンガーラック 強力",
    "珪藻土バスノット 速乾 お風呂",
    "電気ケトル コーヒー 細口 ステンレス",
    "アロマディフューザー 加湿器 静音",
    "圧縮袋 布団 掃除機対応 大容量",
    "ステンレスボトル 保温 保冷 水筒",
]


def ranking_items(count: int, prefix: str = "new") -> list[dict[str, str]]:
    # 商品ごとに明確に異なるタイトルにする（類似判定に誤って弾かれないように）
    return [
        {
            "url": f"https://item.rakuten.co.jp/shop{index}/{prefix}-{index}/",
            "title": DISTINCT_TITLES[index % len(DISTINCT_TITLES)],
        }
        for index in range(count)
    ]


def test_replenish_skips_when_enough_remaining(tmp_path, monkeypatch):
    config = replace(
        load_config(), replenish=ReplenishConfig(enabled=True, threshold=5, batch=5, ranking_urls=("https://r/1",))
    )
    table = make_table(config, [config.statuses.approved] * 6)
    instance, sheet = make_runner(config, table, tmp_path)
    monkeypatch.setattr(runner_module, "RakutenRoomBrowser", FakeBrowser)
    summary = instance.replenish()
    assert summary.changed == 0
    assert sheet.appended == []


def test_replenish_adds_batch_and_skips_duplicates(tmp_path, monkeypatch):
    config = replace(
        load_config(), replenish=ReplenishConfig(enabled=True, threshold=5, batch=3, ranking_urls=("https://r/1",))
    )
    table = make_table(config, [config.statuses.approved] * 2)
    instance, sheet = make_runner(config, table, tmp_path)
    duplicate = {"url": "https://item.rakuten.co.jp/shop/exist-0/", "title": "既存と同じURLの商品"}
    FakeBrowser.items_by_url = {"https://r/1": [duplicate] + ranking_items(10)}
    FakeBrowser.fail_urls = set()
    monkeypatch.setattr(runner_module, "RakutenRoomBrowser", FakeBrowser)
    summary = instance.replenish()
    assert summary.changed == 3
    assert len(sheet.appended) == 3
    urls = {fields["product_url"] for fields in sheet.appended}
    assert "https://item.rakuten.co.jp/shop/exist-0/" not in urls
    for fields in sheet.appended:
        assert fields["status"] == config.statuses.unposted
        assert fields["description"]
        assert not contains_exaggerated_claim(fields["description"])


def test_replenish_continues_after_ranking_failure(tmp_path, monkeypatch):
    config = replace(
        load_config(),
        replenish=ReplenishConfig(enabled=True, threshold=5, batch=2, ranking_urls=("https://r/bad", "https://r/ok")),
    )
    table = make_table(config, [config.statuses.approved])
    instance, sheet = make_runner(config, table, tmp_path)
    FakeBrowser.items_by_url = {"https://r/ok": ranking_items(5, prefix="ok")}
    FakeBrowser.fail_urls = {"https://r/bad"}
    monkeypatch.setattr(runner_module, "RakutenRoomBrowser", FakeBrowser)
    summary = instance.replenish()
    assert summary.errors == 1
    assert summary.changed == 2
    assert len(sheet.appended) == 2


def test_replenish_dry_run_does_not_write(tmp_path, monkeypatch):
    config = replace(
        load_config(), replenish=ReplenishConfig(enabled=True, threshold=5, batch=2, ranking_urls=("https://r/1",))
    )
    table = make_table(config, [config.statuses.approved])
    instance, sheet = make_runner(config, table, tmp_path)
    FakeBrowser.items_by_url = {"https://r/1": ranking_items(5)}
    FakeBrowser.fail_urls = set()
    monkeypatch.setattr(runner_module, "RakutenRoomBrowser", FakeBrowser)
    summary = instance.replenish(dry_run=True)
    assert summary.changed == 2
    assert sheet.appended == []


def test_replenish_skips_similar_titles_within_batch(tmp_path, monkeypatch):
    config = replace(
        load_config(), replenish=ReplenishConfig(enabled=True, threshold=5, batch=5, ranking_urls=("https://r/1",))
    )
    table = make_table(config, [config.statuses.approved])
    instance, sheet = make_runner(config, table, tmp_path)
    FakeBrowser.items_by_url = {
        "https://r/1": [
            {"url": "https://item.rakuten.co.jp/shop-a/glove001/", "title": "ニトリル手袋 100枚入り 使い捨て 料理 掃除"},
            # 別ショップだがタイトルが同一商品（スキップされるべき）
            {"url": "https://item.rakuten.co.jp/shop-b/nitrile100/", "title": "使い捨て ニトリル手袋 100枚入り 掃除 料理 高品質"},
            # 同ショップの型番違い（スキップされるべき）
            {"url": "https://item.rakuten.co.jp/shop-a/glove002/", "title": "まったく別の商品名のタオルケット"},
            {"url": "https://item.rakuten.co.jp/shop-c/pillow1/", "title": "ヒツジのいらない枕 健康グッズ ギフト 実用的"},
        ]
    }
    FakeBrowser.fail_urls = set()
    monkeypatch.setattr(runner_module, "RakutenRoomBrowser", FakeBrowser)
    summary = instance.replenish()
    urls = [fields["product_url"] for fields in sheet.appended]
    assert urls == [
        "https://item.rakuten.co.jp/shop-a/glove001/",
        "https://item.rakuten.co.jp/shop-c/pillow1/",
    ]
    assert summary.changed == 2


def test_approve_marks_similar_product_as_needs_review(tmp_path, monkeypatch):
    config = load_config()
    columns = config.sheet.columns
    values = [
        [columns["product_url"], columns["description"], columns["status"]],
        [
            "https://item.rakuten.co.jp/tenkapas/glove002/",
            "ニトリル手袋100枚入り。丈夫で破れにくい高品質タイプ。掃除や料理に。",
            config.statuses.completed,
        ],
        [
            "https://item.rakuten.co.jp/other-shop/nitrile100/",
            "使い捨てニトリル手袋100枚入り。料理や掃除、ウイルス対策に活躍する高品質グローブ。",
            config.statuses.approval_pending,
        ],
        [
            "https://item.rakuten.co.jp/shop-c/pillow1/",
            "ヒツジのいらない枕。実用的な健康グッズでギフトにも。",
            config.statuses.approval_pending,
        ],
    ]
    table = SheetTable.from_values(values)
    instance, sheet = make_runner(config, table, tmp_path)
    monkeypatch.setattr(runner_module, "check_product_url", lambda url: None)
    summary = instance.approve(limit=10)
    updates = dict(sheet.updated)
    assert updates[3]["status"] == config.statuses.needs_review  # 手袋の類似商品はスキップ
    assert updates[4]["status"] == config.statuses.approved  # 枕は承認
    assert summary.errors == 1


def test_replenish_records_error_on_empty_ranking(tmp_path, monkeypatch):
    config = replace(
        load_config(), replenish=ReplenishConfig(enabled=True, threshold=5, batch=2, ranking_urls=("https://r/empty",))
    )
    table = make_table(config, [config.statuses.approved])
    instance, sheet = make_runner(config, table, tmp_path)
    FakeBrowser.items_by_url = {"https://r/empty": []}
    FakeBrowser.fail_urls = set()
    monkeypatch.setattr(runner_module, "RakutenRoomBrowser", FakeBrowser)
    summary = instance.replenish()
    assert summary.errors == 1
    assert sheet.appended == []
