"""Cross-process per-item posting lock held by the kernel for worker lifetime."""
from __future__ import annotations

import errno
import fcntl
import os
from pathlib import Path

from .config import CONFIG


def path_for(item_id: str) -> Path:
    lock_dir = CONFIG.runtime_dir / "post_locks"
    lock_dir.mkdir(parents=True, exist_ok=True)
    return lock_dir / f"{item_id}.lock"


def _open(item_id: str) -> tuple[int, Path]:
    path = path_for(item_id)
    fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    return fd, path


def _try_lock(fd: int) -> bool:
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError as exc:
        if exc.errno in (errno.EACCES, errno.EAGAIN):
            return False
        raise


def active(item_id: str) -> bool:
    fd, _path = _open(item_id)
    try:
        if not _try_lock(fd):
            return True
        fcntl.flock(fd, fcntl.LOCK_UN)
        return False
    finally:
        os.close(fd)


def acquire(item_id: str) -> tuple[int | None, Path]:
    fd, path = _open(item_id)
    if not _try_lock(fd):
        os.close(fd)
        return None, path
    os.ftruncate(fd, 0)
    os.write(fd, str(os.getpid()).encode("utf-8"))
    os.fsync(fd)
    return fd, path


def release(fd: int, path: Path) -> None:
    del path  # persistent lock files are harmless; flock is the source of truth
    fcntl.flock(fd, fcntl.LOCK_UN)
    os.close(fd)
