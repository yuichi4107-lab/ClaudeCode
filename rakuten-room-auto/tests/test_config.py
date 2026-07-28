from __future__ import annotations

import os
from pathlib import Path

from rakuten_room_auto.config import expand_env, load_config


def test_expand_env_with_default(monkeypatch):
    monkeypatch.delenv("ROOM_TEST_VALUE", raising=False)
    assert expand_env("${ROOM_TEST_VALUE:-fallback}") == "fallback"


def test_load_config_defaults(tmp_path, monkeypatch):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
sheet:
  spreadsheet_id: test-sheet
  worksheet_name: items
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("RAKUTEN_ROOM_CONFIG", str(config_path))
    cfg = load_config()
    assert cfg.sheet.spreadsheet_id == "test-sheet"
    assert cfg.sheet.worksheet_name == "items"
    assert cfg.sheet.columns["product_url"] == "商品URL"
    assert isinstance(cfg.runtime.root_dir, Path)

