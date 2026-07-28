"""Best-effort one-way mirror from local runtime state to Google Drive.

Only this module is allowed to touch Drive during normal operations. It runs in
a child process supervised by a timeout so File Provider stalls cannot block
generation, approval, or posting.
"""
from __future__ import annotations

import copy
import errno
import fcntl
import hashlib
import json
import os
from datetime import datetime
from pathlib import Path

from .config import CONFIG
from .state_io import atomic_write_bytes, atomic_write_json


class MirrorBusy(RuntimeError):
    pass


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_manifest() -> dict:
    try:
        data = json.loads(CONFIG.mirror_manifest_path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {"files": {}}
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return {"files": {}}


def _map_runtime_path(value: str | None) -> str | None:
    if not value:
        return value
    path = Path(value)
    for local_root in (CONFIG.outputs_dir, CONFIG.work_dir):
        try:
            relative = path.relative_to(local_root)
            return str(CONFIG.drive_outputs_dir / relative)
        except ValueError:
            continue
    return value


def _queue_payload(source: Path) -> bytes:
    item = json.loads(source.read_text(encoding="utf-8"))
    mirrored = copy.deepcopy(item)
    mirrored["output_dir"] = _map_runtime_path(mirrored.get("output_dir"))
    video = mirrored.get("video") or {}
    video["path"] = _map_runtime_path(video.get("path"))
    video.pop("local_path", None)
    video.pop("upload_path", None)
    quality = mirrored.get("quality") or {}
    quality["report_path"] = _map_runtime_path(quality.get("report_path"))
    mirrored["mirror"] = {
        "source": "local-runtime",
        "runtime_revision": int(item.get("_revision") or 0),
    }
    return (json.dumps(mirrored, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _payload(source: Path) -> bytes:
    if source.parent == CONFIG.queue_dir and source.suffix == ".json":
        return _queue_payload(source)
    return source.read_bytes()


def _output_files() -> list[tuple[Path, Path, str]]:
    planned: list[tuple[Path, Path, str]] = []
    if not CONFIG.outputs_dir.exists():
        return planned
    for output_dir in sorted(p for p in CONFIG.outputs_dir.iterdir() if p.is_dir()):
        marker = output_dir / ".complete.json"
        if not marker.exists():
            continue
        files = sorted(p for p in output_dir.rglob("*") if p.is_file() and p != marker)
        files.append(marker)  # complete marker is published last
        for source in files:
            relative = source.relative_to(CONFIG.outputs_dir)
            planned.append((source, CONFIG.drive_outputs_dir / relative, f"outputs/{relative}"))
    return planned


def _state_files() -> list[tuple[Path, Path, str]]:
    planned: list[tuple[Path, Path, str]] = []
    if CONFIG.marketing_dir.exists():
        for source in sorted(p for p in CONFIG.marketing_dir.rglob("*") if p.is_file()):
            if source.name.startswith(".") or source.suffix == ".tmp":
                continue
            relative = source.relative_to(CONFIG.marketing_dir)
            if relative.parts and relative.parts[0] == "locks":
                continue
            planned.append(
                (source, CONFIG.drive_marketing_dir / relative, f"state/{relative}")
            )
    ledger_dir = CONFIG.runtime_dir / "posting_ledger"
    if ledger_dir.exists():
        for source in sorted(ledger_dir.glob("*.json")):
            planned.append(
                (
                    source,
                    CONFIG.drive_marketing_dir / "posting_ledger" / source.name,
                    f"ledger/{source.name}",
                )
            )
    return planned


def _acquire_nonblocking_lock() -> int:
    path = CONFIG.mirror_dir / "worker.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        os.close(fd)
        if exc.errno in (errno.EACCES, errno.EAGAIN):
            raise MirrorBusy("another mirror worker is still running") from exc
        raise
    return fd


def mirror_once() -> dict:
    CONFIG.assert_runtime_ready()
    lock_fd = _acquire_nonblocking_lock()
    try:
        manifest = _load_manifest()
        files = manifest.setdefault("files", {})
        copied = 0
        skipped = 0
        verified_bytes = 0

        # Outputs first. Drive queue JSON is exposed only after its completed output.
        plan = [*_output_files(), *_state_files()]
        for source, destination, key in plan:
            data = _payload(source)
            digest = _sha256_bytes(data)
            previous = files.get(key) or {}
            if previous.get("sha256") == digest and previous.get("size") == len(data):
                skipped += 1
                continue
            atomic_write_bytes(destination, data)
            if destination.stat().st_size != len(data) or _sha256_path(destination) != digest:
                raise OSError(f"mirror verification failed: {destination}")
            files[key] = {
                "sha256": digest,
                "size": len(data),
                "mirrored_at": _now(),
            }
            copied += 1
            verified_bytes += len(data)
            manifest["last_progress_at"] = _now()
            atomic_write_json(CONFIG.mirror_manifest_path, manifest)

        manifest["last_success_at"] = _now()
        manifest["last_error"] = None
        atomic_write_json(CONFIG.mirror_manifest_path, manifest)
        return {
            "ok": True,
            "copied": copied,
            "skipped": skipped,
            "verified_bytes": verified_bytes,
            "last_success_at": manifest["last_success_at"],
        }
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)
