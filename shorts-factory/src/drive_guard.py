"""Fail fast if a runtime hot-path process attempts to access CloudStorage."""
from __future__ import annotations

import os
import sys
from pathlib import Path


class DriveHotPathError(RuntimeError):
    pass


_installed = False


def _path_text(value: object) -> str | None:
    if isinstance(value, int):
        return None
    try:
        raw = os.fspath(value)
    except TypeError:
        return None
    if isinstance(raw, bytes):
        return raw.decode(errors="replace")
    return str(raw)


def _is_drive_path(value: object) -> bool:
    text = _path_text(value)
    if not text:
        return False
    normalized = text.replace("\\", "/")
    return "/Library/CloudStorage/" in normalized


def _audit(event: str, args: tuple) -> None:
    if event not in {
        "open",
        "os.listdir",
        "os.scandir",
        "os.mkdir",
        "os.rename",
        "os.remove",
        "os.rmdir",
        "shutil.copyfile",
        "shutil.copytree",
    }:
        return
    for value in args[:2]:
        if _is_drive_path(value):
            raise DriveHotPathError(
                f"Drive access blocked in runtime hot path: event={event} path={value}"
            )


def install() -> None:
    global _installed
    if _installed or os.environ.get("SHORTS_ALLOW_DRIVE_HOTPATH") == "1":
        return
    sys.addaudithook(_audit)
    _installed = True


def assert_local(path: Path | str, label: str = "path") -> None:
    if _is_drive_path(path):
        raise DriveHotPathError(f"Drive path configured for {label}: {path}")
