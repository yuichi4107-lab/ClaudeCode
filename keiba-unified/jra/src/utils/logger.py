"""ロギング設定モジュール"""

import logging
import os
import sys

from src.utils.config_loader import load_settings, get_project_root


_initialized = False


def setup_logger(name: str = None) -> logging.Logger:
    global _initialized

    logger = logging.getLogger(name or "keiba")

    if not _initialized:
        try:
            settings = load_settings()
            log_cfg = settings.get("logging", {})
        except Exception:
            log_cfg = {}

        level = getattr(logging, log_cfg.get("level", "INFO"))
        fmt = log_cfg.get(
            "format", "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
        )
        formatter = logging.Formatter(fmt)

        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)

        root = logging.getLogger()
        root.setLevel(level)
        root.addHandler(console_handler)

        log_file = log_cfg.get("file")
        if log_file:
            log_path = os.path.join(get_project_root(), log_file)
            os.makedirs(os.path.dirname(log_path), exist_ok=True)
            file_handler = logging.FileHandler(log_path, encoding="utf-8")
            file_handler.setFormatter(formatter)
            root.addHandler(file_handler)

        _initialized = True

    return logger
