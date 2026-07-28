"""YAML設定ファイル読み込みモジュール"""

import os
import yaml


_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_CONFIG_DIR = os.path.join(_PROJECT_ROOT, "config")


def _load_yaml(filename: str) -> dict:
    path = os.path.join(_CONFIG_DIR, filename)
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_settings() -> dict:
    return _load_yaml("settings.yaml")


def load_features_config() -> dict:
    return _load_yaml("features.yaml")


def load_strategies_config() -> dict:
    return _load_yaml("strategies.yaml")


def load_backtest_config() -> dict:
    return _load_yaml("backtest.yaml")


def get_db_path() -> str:
    settings = load_settings()
    db_rel = settings["database"]["path"]
    return os.path.join(_PROJECT_ROOT, db_rel)


def get_project_root() -> str:
    return _PROJECT_ROOT
