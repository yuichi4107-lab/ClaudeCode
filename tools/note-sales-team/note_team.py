#!/usr/bin/env python3
"""State, approval UI, and exact-metric analysis for the note sales team.

The module controls one-time approvals and verifies the evidence returned by
the note/X workers.  Browser/API mutations are performed by those workers only
after an approval has been claimed; LINE remains outside this workflow.
"""

from __future__ import annotations

import argparse
import csv
import contextlib
import functools
import hashlib
import html
import io
import json
import os
import re
import secrets
import stat
import sys
import tempfile
import threading
import time
import urllib.parse
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Iterable

try:  # Unix/macOS
    import fcntl
except ImportError:  # pragma: no cover - Windows fallback
    fcntl = None  # type: ignore[assignment]

try:  # Windows
    import msvcrt
except ImportError:  # pragma: no cover - Unix/macOS
    msvcrt = None  # type: ignore[assignment]


PROJECT_REL = Path(".company/projects/note販売AIチーム")
CONFIG_REL = PROJECT_REL / "config/team.json"
RUNS_REL = PROJECT_REL / "runs"
REPORTS_REL = PROJECT_REL / "reports"
STYLE_CANDIDATES_REL = PROJECT_REL / "data/style-candidates.json"
STYLE_REGISTRY_REL = PROJECT_REL / "data/style-corpus.json"
STYLE_SELECTION_SHA_ALGORITHM = "sha256-canonical-json-v1"
STAGES = (
    "plan",
    "outline",
    "draft",
    "promotion",
    "note_draft",
    "note_publish",
    "x_publish",
    "analysis",
)
EXTERNAL_AUTH_STAGES = {"note_draft", "note_publish", "x_publish"}
TERMINAL_STATUSES = {"completed", "rejected"}
BASE_STAGE_STATUSES = {
    "locked",
    "awaiting_output",
    "revision_requested",
    "review",
    "approved",
    "fatal_violation",
    "owner_escalation",
}
EXTERNAL_STAGE_STATUSES = {
    "authorization_required",
    "authorization_ready",
    "authorized",
    "external_in_progress",
    "reconciliation_required",
}
STAGE_STATUS_EXTRAS = {
    "draft": {"unit_cycle", "awaiting_final_output"},
    **{stage: EXTERNAL_STAGE_STATUSES for stage in EXTERNAL_AUTH_STAGES},
}
UNIT_STATUSES = {
    "awaiting_output",
    "revision_requested",
    "review",
    "approved",
    "fatal_violation",
    "owner_escalation",
}
SECRET_PATTERN = re.compile(
    r"(?:sk_(?:live|test)_[A-Za-z0-9]{12,}|sk-[A-Za-z0-9_-]{16,}|"
    r"whsec_[A-Za-z0-9]{12,}|xox[baprs]-[A-Za-z0-9-]{12,}|"
    r"gh[pousr]_[A-Za-z0-9]{20,}|GOCSPX-[A-Za-z0-9_-]{12,}|"
    r"AKIA[A-Z0-9]{16}|-----BEGIN [A-Z ]*PRIVATE KEY-----|"
    r"\d{6,12}:[A-Za-z0-9_-]{20,}|"
    r"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}|"
    r"Bearer\s+[A-Za-z0-9._-]{16,}|"
    r"(?:api[_-]?key|secret[_-]?key|secret|token|password|cookie)\s*[:=]\s*[^\s]{8,})",
    re.IGNORECASE,
)
SAFE_SLUG = re.compile(r"[^a-z0-9-]+")
RUN_ID_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,94}[a-z0-9])?$")
WINDOWS_RESERVED_NAMES = {
    "con",
    "prn",
    "aux",
    "nul",
    *(f"com{number}" for number in range(1, 10)),
    *(f"lpt{number}" for number in range(1, 10)),
}
MAX_TEXT_BYTES = 2_000_000
MAX_METRIC_BYTES = 10_000_000
MAX_METRIC_ROWS = 100_000
MAX_METRIC_INTEGER = 1_000_000_000_000_000
LOCK_TIMEOUT_SECONDS = 5.0
AUTH_TTL_MINUTES = 10
CLAIM_TTL_MINUTES = 5
_RUN_THREAD_LOCKS: dict[str, threading.RLock] = {}
_RUN_THREAD_LOCKS_GUARD = threading.Lock()
JST = timezone(timedelta(hours=9), name="Asia/Tokyo")


class NoteTeamError(RuntimeError):
    """Raised when state or input violates the workflow contract."""


class FatalQualityError(NoteTeamError):
    """Raised for a quality violation that terminates the current run."""


def repo_root(start: Path | None = None) -> Path:
    """Find the YNFactory root without relying on a machine-specific path."""
    current = (start or Path.cwd()).resolve()
    for candidate in (current, *current.parents):
        if (candidate / "AGENTS.md").is_file() and (candidate / ".company").is_dir():
            return candidate
    raise NoteTeamError("AGENTS.md と .company/ があるリポジトリルートを特定できません")


def now_jst() -> datetime:
    return datetime.now(JST)


def iso_now() -> str:
    return now_jst().isoformat(timespec="seconds")


def load_json(path: Path) -> Any:
    try:
        with path.open("r", encoding="utf-8-sig") as handle:
            return json.load(handle)
    except FileNotFoundError as exc:
        raise NoteTeamError(f"必須ファイルがありません: {path}") from exc
    except json.JSONDecodeError as exc:
        raise NoteTeamError(f"JSONが不正です: {path}: {exc}") from exc


def load_json_with_expected_sha(path: Path, expected: str, label: str) -> Any:
    if path.is_symlink():
        raise NoteTeamError(f"{label}にシンボリックリンクは使えません")
    try:
        payload = path.read_bytes()
    except FileNotFoundError as exc:
        raise NoteTeamError(f"{label}がありません: {path}") from exc
    if sha256_bytes(payload) != expected:
        raise NoteTeamError(f"{label}のSHA-256が固定時と一致しません")
    try:
        return json.loads(payload.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise NoteTeamError(f"{label}のJSONが不正です") from exc


def atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def atomic_write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json_bytes(payload: Any) -> bytes:
    """Return the stable UTF-8 representation used by style selection hashes."""
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def open_private_regular_file(path: Path, flags: int, mode: int = 0o600) -> int:
    """Open a fixed local control file without following links or hard links."""
    try:
        before = path.lstat()
    except FileNotFoundError:
        before = None
    if before is not None and not stat.S_ISREG(before.st_mode):
        raise OSError(f"制御ファイルは通常ファイルである必要があります: {path}")
    if before is not None and before.st_nlink != 1:
        raise OSError(f"制御ファイルにハードリンクは使えません: {path}")

    safe_flags = flags | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, safe_flags, mode)
    try:
        opened = os.fstat(fd)
        if not stat.S_ISREG(opened.st_mode):
            raise OSError(f"制御ファイルは通常ファイルである必要があります: {path}")
        if opened.st_nlink != 1:
            raise OSError(f"制御ファイルにハードリンクは使えません: {path}")

        after = path.lstat()
        if not stat.S_ISREG(after.st_mode):
            raise OSError(f"制御ファイルは通常ファイルである必要があります: {path}")
        if after.st_dev != opened.st_dev or after.st_ino != opened.st_ino:
            raise OSError(f"制御ファイルがopen中に差し替えられました: {path}")
        if hasattr(os, "fchmod"):
            os.fchmod(fd, mode)
        return fd
    except BaseException:
        os.close(fd)
        raise


@contextlib.contextmanager
def run_lock(root: Path, run_id_value: str):
    """Serialize state transitions across UI threads and local processes."""
    directory = run_dir(root, run_id_value)
    if not directory.is_dir():
        raise NoteTeamError(f"runがありません: {run_id_value}")
    lock_path = directory / ".state.lock"
    key = str(lock_path.absolute())
    with _RUN_THREAD_LOCKS_GUARD:
        thread_lock = _RUN_THREAD_LOCKS.setdefault(key, threading.RLock())
    with thread_lock:
        try:
            fd = open_private_regular_file(lock_path, os.O_CREAT | os.O_RDWR)
        except OSError as exc:
            raise NoteTeamError(f"runロックを安全に開けません: {lock_path}") from exc
        started = time.monotonic()
        acquired = False
        try:
            while not acquired:
                try:
                    if fcntl is not None:
                        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    elif msvcrt is not None:  # pragma: no cover - Windows
                        os.lseek(fd, 0, os.SEEK_SET)
                        if os.fstat(fd).st_size == 0:
                            os.write(fd, b"0")
                            os.fsync(fd)
                        os.lseek(fd, 0, os.SEEK_SET)
                        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                    else:  # thread lock is still safe within this process
                        pass
                    acquired = True
                except (BlockingIOError, OSError):
                    if time.monotonic() - started >= LOCK_TIMEOUT_SECONDS:
                        raise NoteTeamError("別の操作がこのrunを更新中です。数秒後に再試行してください")
                    time.sleep(0.05)
            os.ftruncate(fd, 0)
            os.write(fd, f"{os.getpid()} {iso_now()}\n".encode("utf-8"))
            os.fsync(fd)
            yield
        finally:
            if acquired:
                if fcntl is not None:
                    fcntl.flock(fd, fcntl.LOCK_UN)
                elif msvcrt is not None:  # pragma: no cover - Windows
                    os.lseek(fd, 0, os.SEEK_SET)
                    msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            os.close(fd)


@contextlib.contextmanager
def create_run_lock(root: Path):
    """Serialize run creation so identical requests are retry-safe."""
    runs_root = ensure_private_directory(root.resolve(), RUNS_REL)
    lock_path = runs_root / ".create.lock"
    key = str(lock_path.absolute())
    with _RUN_THREAD_LOCKS_GUARD:
        thread_lock = _RUN_THREAD_LOCKS.setdefault(key, threading.RLock())
    with thread_lock:
        try:
            fd = open_private_regular_file(lock_path, os.O_CREAT | os.O_RDWR)
        except OSError as exc:
            raise NoteTeamError("run作成ロックを安全に開けません") from exc
        acquired = False
        started = time.monotonic()
        try:
            while not acquired:
                try:
                    if fcntl is not None:
                        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    elif msvcrt is not None:  # pragma: no cover - Windows
                        os.lseek(fd, 0, os.SEEK_SET)
                        if os.fstat(fd).st_size == 0:
                            os.write(fd, b"0")
                            os.fsync(fd)
                        os.lseek(fd, 0, os.SEEK_SET)
                        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                    acquired = True
                except (BlockingIOError, OSError):
                    if time.monotonic() - started >= LOCK_TIMEOUT_SECONDS:
                        raise NoteTeamError("run作成を別プロセスが実行中です")
                    time.sleep(0.05)
            os.ftruncate(fd, 0)
            os.write(fd, f"{os.getpid()} {iso_now()}\n".encode("utf-8"))
            os.fsync(fd)
            yield
        finally:
            if acquired:
                if fcntl is not None:
                    fcntl.flock(fd, fcntl.LOCK_UN)
                elif msvcrt is not None:  # pragma: no cover - Windows
                    os.lseek(fd, 0, os.SEEK_SET)
                    msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            os.close(fd)


@contextlib.contextmanager
def style_corpus_lock(root: Path):
    """Serialize approval of the project-wide style corpus."""
    data_root = ensure_private_directory(root.resolve(), PROJECT_REL / "data")
    lock_path = data_root / ".style-corpus.lock"
    key = str(lock_path.absolute())
    with _RUN_THREAD_LOCKS_GUARD:
        thread_lock = _RUN_THREAD_LOCKS.setdefault(key, threading.RLock())
    with thread_lock:
        try:
            fd = open_private_regular_file(lock_path, os.O_CREAT | os.O_RDWR)
        except OSError as exc:
            raise NoteTeamError("style corpus承認ロックを安全に開けません") from exc
        acquired = False
        started = time.monotonic()
        try:
            while not acquired:
                try:
                    if fcntl is not None:
                        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    elif msvcrt is not None:  # pragma: no cover - Windows
                        os.lseek(fd, 0, os.SEEK_SET)
                        if os.fstat(fd).st_size == 0:
                            os.write(fd, b"0")
                            os.fsync(fd)
                        os.lseek(fd, 0, os.SEEK_SET)
                        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                    acquired = True
                except (BlockingIOError, OSError):
                    if time.monotonic() - started >= LOCK_TIMEOUT_SECONDS:
                        raise NoteTeamError("style corpusを別プロセスが更新中です")
                    time.sleep(0.05)
            os.ftruncate(fd, 0)
            os.write(fd, f"{os.getpid()} {iso_now()}\n".encode("utf-8"))
            os.fsync(fd)
            yield
        finally:
            if acquired:
                if fcntl is not None:
                    fcntl.flock(fd, fcntl.LOCK_UN)
                elif msvcrt is not None:  # pragma: no cover - Windows
                    os.lseek(fd, 0, os.SEEK_SET)
                    msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            os.close(fd)


def locked_run_mutation(function):
    @functools.wraps(function)
    def wrapped(root: Path, run_id_value: str, *args: Any, **kwargs: Any):
        with run_lock(root, run_id_value):
            return function(root, run_id_value, *args, **kwargs)

    return wrapped


def append_audit(run_dir: Path, event: dict[str, Any]) -> None:
    event = {"at": event.get("at", iso_now()), **event}
    path = run_dir / "audit.jsonl"
    fd = open_private_regular_file(path, os.O_CREAT | os.O_WRONLY | os.O_APPEND)
    with os.fdopen(fd, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def assert_no_secret(value: str, label: str = "入力") -> None:
    if SECRET_PATTERN.search(value):
        raise NoteTeamError(f"{label}に認証情報らしい文字列があります。保存を中止しました")


def resolve_inside(base: Path, value: str | Path) -> Path:
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = base / candidate
    candidate = candidate.resolve()
    base_resolved = base.resolve()
    try:
        candidate.relative_to(base_resolved)
    except ValueError as exc:
        raise NoteTeamError(f"許可範囲外のパスです: {candidate}") from exc
    return candidate


def ensure_private_directory(base: Path, relative: str | Path) -> Path:
    """Create/verify a directory chain without following symlink components."""
    base_resolved = base.resolve()
    relative_path = Path(relative)
    if relative_path.is_absolute() or ".." in relative_path.parts:
        raise NoteTeamError(f"不正なディレクトリ指定です: {relative_path}")
    current = base_resolved
    for part in relative_path.parts:
        candidate = current / part
        if candidate.is_symlink():
            raise NoteTeamError(f"書き込み先にシンボリックリンクは使えません: {candidate}")
        if not candidate.exists():
            try:
                candidate.mkdir(mode=0o700)
            except FileExistsError:
                pass
        if candidate.is_symlink():
            raise NoteTeamError(f"書き込み先にシンボリックリンクは使えません: {candidate}")
        if not candidate.is_dir():
            raise NoteTeamError(f"書き込み先の親がディレクトリではありません: {candidate}")
        resolved = candidate.resolve()
        try:
            resolved.relative_to(base_resolved)
        except ValueError as exc:
            raise NoteTeamError(f"書き込み先が許可範囲外です: {resolved}") from exc
        current = resolved
    return current


def read_safe_text(path: Path, label: str) -> tuple[str, bytes]:
    if not path.is_file():
        raise NoteTeamError(f"{label}ファイルがありません: {path}")
    payload = path.read_bytes()
    if len(payload) > MAX_TEXT_BYTES:
        raise NoteTeamError(f"{label}は2MB以下のUTF-8テキストにしてください")
    try:
        content = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise NoteTeamError(f"{label}はUTF-8テキストにしてください") from exc
    assert_no_secret(content, label)
    return content, payload


def parse_checked_at(value: Any, label: str = "checked_at") -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise NoteTeamError(f"{label}はタイムゾーン付きISO 8601日時で必須です")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise NoteTeamError(f"{label}はタイムゾーン付きISO 8601日時で指定してください") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise NoteTeamError(f"{label}にタイムゾーンがありません")
    return parsed


def validate_editor_draft_url(value: Any, draft_id: Any, label: str) -> None:
    if not isinstance(draft_id, str) or not re.fullmatch(r"n[A-Za-z0-9_-]{3,}", draft_id):
        raise NoteTeamError(f"{label}の editor_draft_id 形式が不正です")
    if not isinstance(value, str):
        raise NoteTeamError(f"{label}のURLが文字列ではありません")
    parsed = urllib.parse.urlparse(value)
    try:
        port = parsed.port
    except ValueError as exc:
        raise NoteTeamError(f"{label}のURLポートが不正です") from exc
    if (
        parsed.scheme != "https"
        or parsed.hostname != "editor.note.com"
        or parsed.netloc not in {"editor.note.com", "editor.note.com:443"}
        or port not in {None, 443}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path.rstrip("/") != f"/notes/{draft_id}/edit"
        or parsed.params
        or parsed.query
        or parsed.fragment
    ):
        raise NoteTeamError(f"{label}のURLがeditor_draft_idと一致するnote編集URLではありません")


def validate_new_draft_url(value: Any) -> None:
    if not isinstance(value, str):
        raise NoteTeamError("note事前確認のeditor_urlが文字列ではありません")
    parsed = urllib.parse.urlparse(value)
    try:
        port = parsed.port
    except ValueError as exc:
        raise NoteTeamError("note事前確認のeditor_urlポートが不正です") from exc
    if (
        parsed.scheme != "https"
        or parsed.hostname != "note.com"
        or parsed.netloc not in {"note.com", "note.com:443"}
        or port not in {None, 443}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path.rstrip("/") != "/notes/new"
        or parsed.params
        or parsed.query
        or parsed.fragment
    ):
        raise NoteTeamError("note事前確認は https://note.com/notes/new の空の新規投稿画面で行ってください")


def validate_note_public_url(
    value: Any,
    note_id: Any,
    label: str,
    expected_article_id: Any | None = None,
) -> None:
    if not isinstance(note_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{2,}", note_id):
        raise NoteTeamError(f"{label}のnote ID形式が不正です")
    if not isinstance(value, str):
        raise NoteTeamError(f"{label}のURLが文字列ではありません")
    parsed = urllib.parse.urlparse(value)
    try:
        port = parsed.port
    except ValueError as exc:
        raise NoteTeamError(f"{label}のURLポートが不正です") from exc
    expected_prefix = f"/{note_id}/n/"
    article_id = parsed.path.removeprefix(expected_prefix).rstrip("/")
    if (
        parsed.scheme != "https"
        or parsed.hostname != "note.com"
        or parsed.netloc not in {"note.com", "note.com:443"}
        or port not in {None, 443}
        or parsed.username is not None
        or parsed.password is not None
        or not parsed.path.startswith(expected_prefix)
        or not re.fullmatch(r"n[A-Za-z0-9_-]{3,}", article_id)
        or parsed.params
        or parsed.query
        or parsed.fragment
    ):
        raise NoteTeamError(f"{label}が対象note IDの公開記事URLではありません")
    if expected_article_id is not None and article_id != expected_article_id:
        raise NoteTeamError(f"{label}の公開記事IDが元のeditor draft IDと一致しません")


def validate_x_status_url(value: Any, username: Any, tweet_id: Any, label: str) -> None:
    if not isinstance(username, str) or not re.fullmatch(r"[A-Za-z0-9_]{1,15}", username):
        raise NoteTeamError(f"{label}のXユーザー名が不正です")
    if not isinstance(tweet_id, str) or not re.fullmatch(r"\d{5,30}", tweet_id):
        raise NoteTeamError(f"{label}のtweet IDが不正です")
    if not isinstance(value, str):
        raise NoteTeamError(f"{label}のURLが文字列ではありません")
    parsed = urllib.parse.urlparse(value)
    try:
        port = parsed.port
    except ValueError as exc:
        raise NoteTeamError(f"{label}のURLポートが不正です") from exc
    if (
        parsed.scheme != "https"
        or parsed.hostname != "x.com"
        or parsed.netloc not in {"x.com", "x.com:443"}
        or port not in {None, 443}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path.rstrip("/") != f"/{username}/status/{tweet_id}"
        or parsed.params
        or parsed.query
        or parsed.fragment
    ):
        raise NoteTeamError(f"{label}がXのアカウントとtweet IDに一致しません")


def require_recent_check(value: Any, label: str, max_age_minutes: int = 10) -> datetime:
    parsed = parse_checked_at(value, label)
    now = now_jst()
    comparable = parsed.astimezone(now.tzinfo)
    if comparable > now + timedelta(minutes=1):
        raise NoteTeamError(f"{label}が現在時刻より先です")
    if now - comparable > timedelta(minutes=max_age_minutes):
        raise NoteTeamError(f"{label}が{max_age_minutes}分より古いため再確認が必要です")
    return parsed


def load_fact_pack_input(root: Path, fact_pack: str | Path) -> tuple[Path, bytes, str]:
    source = resolve_inside(root, fact_pack)
    content, payload = read_safe_text(source, "fact pack")
    approved = re.search(r"(?mi)^owner_approved:\s*true\s*$", content)
    approved_at = re.search(r"(?mi)^approved_at:\s*(\S+)\s*$", content)
    if not approved or not approved_at:
        raise NoteTeamError("fact packに owner_approved: true と approved_at: タイムゾーン付き日時が必要です")
    parse_checked_at(approved_at.group(1), "fact pack approved_at")
    return source, payload, sha256_bytes(payload)


def store_fact_pack(
    root: Path,
    state: dict[str, Any],
    source: Path,
    payload: bytes,
    digest: str,
) -> dict[str, Any]:
    existing = state.setdefault("inputs", {}).get("fact_pack")
    if existing:
        if existing.get("sha256") == digest:
            return existing
        raise NoteTeamError("このrunには別のfact packが固定済みです。差し替えは新しいrunで行ってください")
    directory = run_dir(root, state["run_id"]).resolve()
    inputs_directory = ensure_private_directory(directory, "inputs")
    saved = inputs_directory / f"fact-pack-{digest[:16]}.md"
    if saved.is_symlink():
        raise NoteTeamError(f"fact pack保存先にシンボリックリンクは使えません: {saved}")
    atomic_write_bytes(saved, payload)
    saved.chmod(0o400)
    record = {
        "source": source.resolve().relative_to(root.resolve()).as_posix(),
        "artifact": saved.resolve().relative_to(directory).as_posix(),
        "sha256": digest,
        "owner_approved_at": None,
        "owner_approved_by": None,
    }
    state["inputs"]["fact_pack"] = record
    return record


def verify_fact_pack(
    root: Path, state: dict[str, Any], *, require_owner_approval: bool = True
) -> dict[str, Any]:
    record = state.get("inputs", {}).get("fact_pack")
    if not isinstance(record, dict):
        raise NoteTeamError("paid-longformに必要なfact packが固定されていません")
    relative = record.get("artifact")
    expected = record.get("sha256")
    if not isinstance(relative, str) or not isinstance(expected, str):
        raise NoteTeamError("fact pack固定記録が不正です")
    path = resolve_inside(run_dir(root, state["run_id"]), relative)
    if not path.is_file() or path.is_symlink() or sha256_file(path) != expected:
        raise NoteTeamError("fact packの承認固定版が変更または破損しています")
    if require_owner_approval and (
        not record.get("owner_approved_at") or record.get("owner_approved_by") != "owner"
    ):
        raise NoteTeamError("fact packはローカル承認画面でオーナー確認が必要です")
    return record


def snapshot_text(
    run_directory: Path,
    source_relative: str,
    category: str,
    attempt: int,
) -> tuple[str, str]:
    base = run_directory.resolve()
    source = resolve_inside(base, source_relative)
    _, payload = read_safe_text(source, "成果物")
    digest = sha256_bytes(payload)
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "-", source.name).strip("-.") or "artifact.txt"
    # Keep the complete snapshot basename comfortably below common 255-byte
    # filesystem limits while retaining a useful suffix and collision marker.
    name_budget = 96
    if len(safe_name.encode("ascii")) > name_budget:
        suffix = Path(safe_name).suffix
        if len(suffix) > 16:
            suffix = suffix[-16:]
        marker = f"-{digest[16:24]}"
        stem = safe_name[: -len(Path(safe_name).suffix)] if Path(safe_name).suffix else safe_name
        keep = max(1, name_budget - len(marker) - len(suffix))
        safe_name = f"{stem[:keep]}{marker}{suffix}"
    parent = ensure_private_directory(base, Path(".snapshots") / category)
    target = parent / f"{attempt:02d}-{digest[:16]}-{safe_name}"
    if target.is_symlink():
        raise NoteTeamError(f"スナップショット先にシンボリックリンクは使えません: {target}")
    if target.exists():
        if sha256_file(target) != digest:
            raise NoteTeamError("スナップショットの整合性エラーです")
    else:
        atomic_write_bytes(target, payload)
        target.chmod(0o400)
    return target.resolve().relative_to(base).as_posix(), digest


def verify_snapshot(run_directory: Path, target: dict[str, Any]) -> None:
    relative = target.get("artifact")
    expected = target.get("artifact_sha256")
    if not relative or not expected:
        raise NoteTeamError("レビュー対象の固定版またはSHA-256がありません")
    path = resolve_inside(run_directory, relative)
    if not path.is_file() or sha256_file(path) != expected:
        raise NoteTeamError("レビュー後に成果物が変更されました。再submitしてください")


def verify_director_qa_snapshot(
    root: Path,
    run_directory: Path,
    stage: str,
    unit: str | None,
    target: dict[str, Any],
) -> None:
    record = target.get("director_qa")
    if not isinstance(record, dict):
        raise NoteTeamError("Director QAの固定版がありません。再submitしてください")
    qa_target = {
        "artifact": record.get("artifact"),
        "artifact_sha256": record.get("sha256"),
    }
    verify_snapshot(run_directory, qa_target)
    validate_director_qa(
        root,
        stage,
        unit,
        target.get("artifact_sha256") or "",
        resolve_inside(run_directory, qa_target["artifact"] or ""),
    )


def discard_snapshots(run_directory: Path, relatives: Iterable[str | None]) -> None:
    """Remove only newly rejected immutable candidates inside .snapshots/."""
    snapshot_root = (run_directory / ".snapshots").resolve()
    for relative in relatives:
        if not relative:
            continue
        try:
            path = resolve_inside(snapshot_root, resolve_inside(run_directory, relative))
        except NoteTeamError:
            continue
        try:
            path.chmod(0o600)
            path.unlink()
        except FileNotFoundError:
            pass


def style_config(config: dict[str, Any]) -> dict[str, Any]:
    settings = config.get("style_sources")
    if not isinstance(settings, dict):
        raise NoteTeamError("team.json の style_sources 設定が必要です")
    required = {
        "candidate_registry_path",
        "registry_path",
        "minimum_note_samples",
        "minimum_x_samples",
        "require_owner_approval",
    }
    missing = sorted(required - set(settings))
    if missing:
        raise NoteTeamError(
            f"style_sources の必須キーがありません: {', '.join(missing)}"
        )
    if settings.get("registry_path") != STYLE_REGISTRY_REL.as_posix():
        raise NoteTeamError(
            f"style_sources.registry_path は {STYLE_REGISTRY_REL.as_posix()} に固定してください"
        )
    if settings.get("candidate_registry_path") != STYLE_CANDIDATES_REL.as_posix():
        raise NoteTeamError(
            f"style_sources.candidate_registry_path は {STYLE_CANDIDATES_REL.as_posix()} に固定してください"
        )
    if settings.get("minimum_note_samples") != 3:
        raise NoteTeamError("style_sources.minimum_note_samples は 3 が必要です")
    if settings.get("minimum_x_samples") != 20:
        raise NoteTeamError("style_sources.minimum_x_samples は 20 が必要です")
    if settings.get("require_owner_approval") is not True:
        raise NoteTeamError("style_sources.require_owner_approval は true が必要です")
    return settings


def repo_relative_regular_file(root: Path, value: Any, label: str) -> Path:
    """Resolve an existing repository file without accepting link components."""
    if not isinstance(value, str) or not value.strip():
        raise NoteTeamError(f"{label}はリポジトリ相対パスで必須です")
    relative = Path(value)
    if relative.is_absolute() or not relative.parts or ".." in relative.parts:
        raise NoteTeamError(f"{label}に絶対パスや .. は使えません")
    base = root.resolve()
    candidate = base
    for part in relative.parts:
        candidate = candidate / part
        if candidate.is_symlink():
            raise NoteTeamError(f"{label}にシンボリックリンクは使えません")
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(base)
    except FileNotFoundError as exc:
        raise NoteTeamError(f"{label}がありません: {relative.as_posix()}") from exc
    except ValueError as exc:
        raise NoteTeamError(f"{label}がリポジトリ外を指しています") from exc
    if not resolved.is_file() or resolved.is_symlink():
        raise NoteTeamError(f"{label}は通常ファイルである必要があります")
    return resolved


def read_repo_text_file(
    root: Path, relative: str | Path, label: str, *, reject_secrets: bool = False
) -> tuple[Path, str, bytes]:
    path = repo_relative_regular_file(root, str(relative), label)
    payload = path.read_bytes()
    if len(payload) > MAX_TEXT_BYTES:
        raise NoteTeamError(f"{label}は2MB以下にしてください")
    try:
        content = payload.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise NoteTeamError(f"{label}はUTF-8テキストにしてください") from exc
    if reject_secrets:
        assert_no_secret(content, label)
    return path, content, payload


def load_repo_json_file(
    root: Path, relative: str | Path, label: str
) -> tuple[dict[str, Any], bytes, str]:
    _, content, payload = read_repo_text_file(root, relative, label)
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        raise NoteTeamError(f"{label}のJSONが不正です: {exc}") from exc
    if not isinstance(parsed, dict):
        raise NoteTeamError(f"{label}はJSONオブジェクトである必要があります")
    return parsed, payload, sha256_bytes(payload)


def require_style_string(candidate: dict[str, Any], key: str, label: str) -> str:
    value = candidate.get(key)
    if not isinstance(value, str) or not value.strip():
        raise NoteTeamError(f"{label}.{key} は空でない文字列が必要です")
    return value


def validate_style_constraints(candidate: dict[str, Any], label: str) -> None:
    constraints = candidate.get("constraints")
    if not isinstance(constraints, list) or not all(
        isinstance(item, str) and item.strip() for item in constraints
    ):
        raise NoteTeamError(f"{label}.constraints は空でない文字列配列が必要です")


def validate_style_candidate_id(value: Any, label: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(
        r"[A-Za-z0-9](?:[A-Za-z0-9._-]{0,126}[A-Za-z0-9])?", value
    ):
        raise NoteTeamError(f"{label}.candidate_id の形式が不正です")
    return value


def validate_style_note_url(value: Any, label: str) -> str:
    if not isinstance(value, str):
        raise NoteTeamError(f"{label}のnote URLが文字列ではありません")
    parsed = urllib.parse.urlparse(value)
    try:
        port = parsed.port
    except ValueError as exc:
        raise NoteTeamError(f"{label}のnote URLポートが不正です") from exc
    if (
        parsed.scheme != "https"
        or parsed.hostname != "note.com"
        or parsed.netloc not in {"note.com", "note.com:443"}
        or port not in {None, 443}
        or parsed.username is not None
        or parsed.password is not None
        or not re.fullmatch(r"/[A-Za-z0-9_-]+/n/n[A-Za-z0-9_-]+/?", parsed.path)
        or parsed.params
        or parsed.query
        or parsed.fragment
    ):
        raise NoteTeamError(f"{label}が公開note記事URLではありません")
    return value


def validate_provenance_relative_path(value: Any, label: str) -> None:
    """Validate provenance labels that are never opened by this program."""
    if value is None:
        return
    if not isinstance(value, str) or not value.strip():
        raise NoteTeamError(f"{label}の形式が不正です")
    candidate = Path(value)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise NoteTeamError(f"{label}に絶対パスや .. は使えません")


def validate_style_evidence_date(value: Any, precision: Any, label: str) -> None:
    """Accept an honest date-only observation or a timezone-aware timestamp."""
    if precision == "date":
        if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            raise NoteTeamError(f"{label}はYYYY-MM-DD形式が必要です")
        try:
            datetime.strptime(value, "%Y-%m-%d")
        except ValueError as exc:
            raise NoteTeamError(f"{label}の日付が不正です") from exc
        return
    if precision == "timestamp":
        parse_checked_at(value, label)
        return
    raise NoteTeamError(f"{label}のverification_precisionはdateまたはtimestampが必要です")


def style_selection_manifest(
    note_candidates: list[dict[str, Any]], x_candidates: list[dict[str, Any]]
) -> dict[str, Any]:
    return {
        "notes": [
            {
                "candidate_id": candidate["candidate_id"],
                "file_sha256": candidate["file_sha256"],
            }
            for candidate in note_candidates
        ],
        "x": [
            {
                "candidate_id": candidate["candidate_id"],
                "tweet_id": candidate["tweet_id"],
                "text_sha256": candidate["text_sha256"],
            }
            for candidate in x_candidates
        ],
    }


def load_style_candidate_pack(
    root: Path, config: dict[str, Any] | None = None
) -> tuple[dict[str, Any], str, dict[str, Any], str]:
    config = config or load_config(root)
    settings = style_config(config)
    payload, _, pack_sha = load_repo_json_file(
        root, settings["candidate_registry_path"], "style candidate pack"
    )
    if isinstance(payload.get("version"), bool) or not isinstance(payload.get("version"), int):
        raise NoteTeamError("style candidate pack.version は整数が必要です")
    if payload.get("status") != "owner-approval-required":
        raise NoteTeamError("style candidate pack.status は owner-approval-required が必要です")
    if payload.get("brand_style_candidate") is not True:
        raise NoteTeamError("style candidate pack.brand_style_candidate は true が必要です")
    if payload.get("owner_style_approval_required") is not True:
        raise NoteTeamError("style candidate pack.owner_style_approval_required は true が必要です")
    parse_checked_at(payload.get("generated_at"), "style candidate pack.generated_at")
    limitations = payload.get("limitations")
    if not isinstance(limitations, list) or not all(
        isinstance(item, str) and item.strip() for item in limitations
    ):
        raise NoteTeamError("style candidate pack.limitations は文字列配列が必要です")

    note_candidates = payload.get("note_candidates")
    x_candidates = payload.get("x_candidates")
    if not isinstance(note_candidates, list) or len(note_candidates) != settings["minimum_note_samples"]:
        raise NoteTeamError(
            f"style candidate packのnote候補は正確に{settings['minimum_note_samples']}件が必要です"
        )
    if not isinstance(x_candidates, list) or len(x_candidates) != settings["minimum_x_samples"]:
        raise NoteTeamError(
            f"style candidate packのX候補は正確に{settings['minimum_x_samples']}件が必要です"
        )

    seen_ids: set[str] = set()
    note_paths: set[str] = set()
    note_urls: set[str] = set()
    for index, candidate in enumerate(note_candidates, 1):
        label = f"note_candidates[{index}]"
        if not isinstance(candidate, dict):
            raise NoteTeamError(f"{label}はJSONオブジェクトが必要です")
        candidate_id = validate_style_candidate_id(candidate.get("candidate_id"), label)
        if candidate_id in seen_ids:
            raise NoteTeamError(f"style candidate packのcandidate_idが重複しています: {candidate_id}")
        seen_ids.add(candidate_id)
        require_style_string(candidate, "title", label)
        require_style_string(candidate, "preview", label)
        source_path = require_style_string(candidate, "source_path", label)
        if source_path in note_paths:
            raise NoteTeamError(f"style candidate packのnote source_pathが重複しています: {source_path}")
        note_paths.add(source_path)
        source_url = validate_style_note_url(candidate.get("source_url"), label)
        public_url = validate_style_note_url(candidate.get("public_url"), label)
        if source_url != public_url:
            raise NoteTeamError(f"{label}のsource_urlとpublic_urlが一致しません")
        if public_url in note_urls:
            raise NoteTeamError(f"style candidate packのnote URLが重複しています: {public_url}")
        note_urls.add(public_url)
        precision = candidate.get("verification_precision")
        validate_style_evidence_date(
            candidate.get("public_verified_at"), precision, f"{label}.public_verified_at"
        )
        if candidate.get("published_at") is not None:
            validate_style_evidence_date(
                candidate.get("published_at"), precision, f"{label}.published_at"
            )
        if not isinstance(candidate.get("metrics"), dict):
            raise NoteTeamError(f"{label}.metrics はJSONオブジェクトが必要です")
        note_metrics = candidate["metrics"]
        if note_metrics.get("scope") != "publication-verified-only" or any(
            note_metrics.get(key) != "N/A"
            for key in ("sales_units", "sales_amount_yen", "paid_conversion_rate")
        ):
            raise NoteTeamError(
                f"{label}.metricsはpublication-verified-onlyと売上3指標のN/Aを明示する必要があります"
            )
        validate_style_constraints(candidate, label)
        expected_sha = candidate.get("file_sha256")
        if not isinstance(expected_sha, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_sha):
            raise NoteTeamError(f"{label}.file_sha256 の形式が不正です")
        source, _, source_payload = read_repo_text_file(
            root, source_path, f"{label}.source_path", reject_secrets=True
        )
        if source.suffix.lower() not in {".md", ".txt"}:
            raise NoteTeamError(f"{label}.source_path は .md または .txt にしてください")
        if sha256_bytes(source_payload) != expected_sha:
            raise NoteTeamError(f"{label}のnoteファイルSHA-256が一致しません")

    x_account = config.get("x_account")
    if not isinstance(x_account, dict):
        raise NoteTeamError("X候補検証にteam.jsonのx_account固定が必要です")
    tweet_ids: set[str] = set()
    x_urls: set[str] = set()
    for index, candidate in enumerate(x_candidates, 1):
        label = f"x_candidates[{index}]"
        if not isinstance(candidate, dict):
            raise NoteTeamError(f"{label}はJSONオブジェクトが必要です")
        candidate_id = validate_style_candidate_id(candidate.get("candidate_id"), label)
        if candidate_id in seen_ids:
            raise NoteTeamError(f"style candidate packのcandidate_idが重複しています: {candidate_id}")
        seen_ids.add(candidate_id)
        tweet_id = require_style_string(candidate, "tweet_id", label)
        if not re.fullmatch(r"\d{5,30}", tweet_id) or tweet_id in tweet_ids:
            raise NoteTeamError(f"{label}.tweet_id の形式が不正または重複しています")
        tweet_ids.add(tweet_id)
        require_style_string(candidate, "title", label)
        text = require_style_string(candidate, "text", label)
        require_style_string(candidate, "preview", label)
        assert_no_secret(text, f"{label}.text")
        author_id = require_style_string(candidate, "author_id", label)
        author_username = require_style_string(candidate, "author_username", label)
        if (
            author_id != x_account.get("user_id")
            or author_username.lower() != str(x_account.get("username", "")).lower()
        ):
            raise NoteTeamError(f"{label}のX投稿者がteam.jsonの固定アカウントと一致しません")
        source_url = require_style_string(candidate, "source_url", label)
        validate_x_status_url(source_url, author_username, tweet_id, label)
        if source_url in x_urls:
            raise NoteTeamError(f"style candidate packのX URLが重複しています: {source_url}")
        x_urls.add(source_url)
        parse_checked_at(candidate.get("posted_at"), f"{label}.posted_at")
        x_metrics = candidate.get("metrics")
        if not isinstance(x_metrics, dict) or not isinstance(
            x_metrics.get("public_metrics"), dict
        ):
            raise NoteTeamError(
                f"{label}.metrics.public_metrics はJSONオブジェクトが必要です"
            )
        if candidate.get("brand_style_candidate") is not True:
            raise NoteTeamError(f"{label}.brand_style_candidate は true が必要です")
        if candidate.get("owner_style_approval_required") is not True:
            raise NoteTeamError(f"{label}.owner_style_approval_required は true が必要です")
        validate_style_constraints(candidate, label)
        for key in ("source_queue", "source_ledger"):
            validate_provenance_relative_path(candidate.get(key), f"{label}.{key}")
        expected_sha = candidate.get("text_sha256")
        actual_sha = sha256_bytes(text.encode("utf-8"))
        if expected_sha != actual_sha:
            raise NoteTeamError(f"{label}.text_sha256がX本文の再計算値と一致しません")

    manifest = style_selection_manifest(note_candidates, x_candidates)
    selection_sha = sha256_bytes(canonical_json_bytes(manifest))
    if payload.get("selection_manifest") != manifest:
        raise NoteTeamError("style candidate pack.selection_manifestが候補本体と一致しません")
    if payload.get("selection_sha256") != selection_sha:
        raise NoteTeamError("style candidate pack.selection_sha256がcanonical JSON再計算値と一致しません")
    if not isinstance(payload.get("selection_sha256_algorithm"), str):
        raise NoteTeamError("style candidate pack.selection_sha256_algorithm が必要です")
    return payload, pack_sha, manifest, selection_sha


def style_registry_records(candidate_pack: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    note_sources = [
        {
            "candidate_id": candidate["candidate_id"],
            "title": candidate["title"],
            "source_path": candidate["source_path"],
            "source_url": candidate["source_url"],
            "file_sha256": candidate["file_sha256"],
        }
        for candidate in candidate_pack["note_candidates"]
    ]
    x_sources = [
        {
            "candidate_id": candidate["candidate_id"],
            "tweet_id": candidate["tweet_id"],
            "title": candidate["title"],
            "source_url": candidate["source_url"],
            "text_sha256": candidate["text_sha256"],
        }
        for candidate in candidate_pack["x_candidates"]
    ]
    return note_sources, x_sources


def load_style_registry_raw(root: Path) -> tuple[dict[str, Any], str]:
    registry, _, registry_sha = load_repo_json_file(
        root, STYLE_REGISTRY_REL, "style corpus registry"
    )
    return registry, registry_sha


def validate_approved_style_registry(
    registry: dict[str, Any],
    candidate_pack: dict[str, Any],
    candidate_pack_sha: str,
    selection_manifest: dict[str, Any],
    selection_sha: str,
) -> dict[str, Any]:
    if registry.get("version") != 2 or registry.get("status") != "approved":
        raise NoteTeamError("style corpus registryはversion 2のapprovedである必要があります")
    if registry.get("approved_by") != "owner":
        raise NoteTeamError("style corpus registry.approved_byはownerである必要があります")
    parse_checked_at(registry.get("approved_at"), "style corpus registry.approved_at")
    if registry.get("candidate_pack_path") != STYLE_CANDIDATES_REL.as_posix():
        raise NoteTeamError("style corpus registryのcandidate packパスが固定値と一致しません")
    if registry.get("candidate_pack_sha256") != candidate_pack_sha:
        raise NoteTeamError("style corpus registryのcandidate pack SHA-256が現在値と一致しません")
    if registry.get("selection_manifest") != selection_manifest:
        raise NoteTeamError("style corpus registry.selection_manifestが承認候補と一致しません")
    if registry.get("selection_sha256") != selection_sha:
        raise NoteTeamError("style corpus registry.selection_sha256がcanonical JSON再計算値と一致しません")
    if registry.get("selection_sha256_algorithm") != STYLE_SELECTION_SHA_ALGORITHM:
        raise NoteTeamError("style corpus registry.selection_sha256_algorithmが不正です")
    expected_notes, expected_x = style_registry_records(candidate_pack)
    if registry.get("note_sources") != expected_notes:
        raise NoteTeamError("style corpus registryのnote_sourcesが承認候補と一致しません")
    if registry.get("x_sources") != expected_x:
        raise NoteTeamError("style corpus registryのx_sourcesが承認候補と一致しません")
    return registry


def verify_style_corpus(
    root: Path, config: dict[str, Any] | None = None
) -> dict[str, Any]:
    config = config or load_config(root)
    candidate_pack, pack_sha, manifest, selection_sha = load_style_candidate_pack(
        root, config
    )
    registry, _ = load_style_registry_raw(root)
    return validate_approved_style_registry(
        registry, candidate_pack, pack_sha, manifest, selection_sha
    )


def approve_style_corpus(
    root: Path,
    expected_candidate_pack_sha256: str,
    expected_registry_sha256: str,
    *,
    owner_session_confirmed: bool = False,
) -> dict[str, Any]:
    if not owner_session_confirmed:
        raise NoteTeamError("style corpus承認はローカル承認画面から実行してください")
    for value, label in (
        (expected_candidate_pack_sha256, "candidate pack SHA-256"),
        (expected_registry_sha256, "registry SHA-256"),
    ):
        if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
            raise NoteTeamError(f"{label}の形式が不正です")
    with style_corpus_lock(root):
        config = load_config(root)
        candidate_pack, pack_sha, manifest, selection_sha = load_style_candidate_pack(
            root, config
        )
        if not secrets.compare_digest(pack_sha, expected_candidate_pack_sha256):
            raise NoteTeamError("style candidate packが画面表示後に変更されました。再読み込みしてください")
        registry, registry_sha = load_style_registry_raw(root)
        if not secrets.compare_digest(registry_sha, expected_registry_sha256):
            try:
                return validate_approved_style_registry(
                    registry, candidate_pack, pack_sha, manifest, selection_sha
                )
            except NoteTeamError as exc:
                raise NoteTeamError(
                    "style corpus registryが画面表示後に変更されました。再読み込みしてください"
                ) from exc

        if registry.get("status") == "approved":
            try:
                return validate_approved_style_registry(
                    registry, candidate_pack, pack_sha, manifest, selection_sha
                )
            except NoteTeamError as exc:
                raise NoteTeamError(
                    "承認済みstyle corpusを別内容で上書きできません"
                ) from exc
        if registry.get("status") not in {"setup-required", "owner-approval-required"}:
            raise NoteTeamError("style corpus registryが承認可能な初期状態ではありません")

        note_sources, x_sources = style_registry_records(candidate_pack)
        approved = {
            "version": 2,
            "status": "approved",
            "approved_by": "owner",
            "approved_at": iso_now(),
            "candidate_pack_path": STYLE_CANDIDATES_REL.as_posix(),
            "candidate_pack_sha256": pack_sha,
            "selection_manifest": manifest,
            "selection_sha256": selection_sha,
            "selection_sha256_algorithm": STYLE_SELECTION_SHA_ALGORITHM,
            "note_sources": note_sources,
            "x_sources": x_sources,
            "limitations": list(candidate_pack.get("limitations", [])),
        }

        # Recheck the exact pack and all referenced note files immediately
        # before the atomic registry replacement.
        _, final_pack_sha, final_manifest, final_selection_sha = load_style_candidate_pack(
            root, config
        )
        final_registry, final_registry_sha = load_style_registry_raw(root)
        if (
            final_pack_sha != pack_sha
            or final_manifest != manifest
            or final_selection_sha != selection_sha
        ):
            raise NoteTeamError("style candidate packが承認処理中に変更されました")
        if final_registry != registry or final_registry_sha != registry_sha:
            raise NoteTeamError("style corpus registryが承認処理中に変更されました")
        registry_path = repo_relative_regular_file(
            root, STYLE_REGISTRY_REL.as_posix(), "style corpus registry"
        )
        atomic_write_json(registry_path, approved)
        return approved


def load_config(root: Path) -> dict[str, Any]:
    config = load_json(root / CONFIG_REL)
    required = {
        "timezone",
        "project_root",
        "legacy_accounts_path",
        "legacy_history_path",
        "default_account_id",
        "default_theme_id",
        "article_defaults",
        "product_profiles",
        "safety",
        "metrics",
        "style_sources",
    }
    missing = sorted(required - set(config))
    if missing:
        raise NoteTeamError(f"team.json の必須キーがありません: {', '.join(missing)}")
    if config["timezone"] != "Asia/Tokyo":
        raise NoteTeamError("初期版は timezone=Asia/Tokyo のみ対応します")
    style_config(config)
    return config


def get_accounts(root: Path, config: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    payload = load_json(resolve_inside(root, config["legacy_accounts_path"]))
    if not isinstance(payload, dict) or not isinstance(payload.get("accounts"), list):
        raise NoteTeamError("accounts.json の accounts 配列がありません")
    if not isinstance(payload.get("themes"), list):
        raise NoteTeamError("accounts.json の themes 配列がありません")
    return payload["accounts"], payload["themes"]


def get_account_theme(
    root: Path, config: dict[str, Any], account_id: str, theme_id: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    accounts, themes = get_accounts(root, config)
    account = next((item for item in accounts if item.get("account_id") == account_id), None)
    if not account:
        raise NoteTeamError(f"未登録の account_id です: {account_id}")
    if account.get("status") != "active":
        raise NoteTeamError(f"active ではないアカウントです: {account_id}")
    theme = next((item for item in themes if item.get("theme_id") == theme_id), None)
    if not theme:
        raise NoteTeamError(f"未登録の theme_id です: {theme_id}")
    if theme.get("account_id") != account_id:
        raise NoteTeamError(
            f"theme_id={theme_id} は account_id={account_id} に割り当てられていません"
        )
    return account, theme


def slugify(value: str) -> str:
    normalized = SAFE_SLUG.sub("-", value.lower()).strip("-")
    if normalized:
        return normalized[:48]
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def run_dir(root: Path, run_id: str) -> Path:
    if not RUN_ID_PATTERN.fullmatch(run_id) or run_id in WINDOWS_RESERVED_NAMES:
        raise NoteTeamError("run_id は1〜96文字の小文字英数字・ハイフンで、先頭末尾は英数字にしてください")
    runs_root = ensure_private_directory(root.resolve(), RUNS_REL)
    candidate = runs_root / run_id
    if candidate.is_symlink():
        raise NoteTeamError(f"runディレクトリにシンボリックリンクは使えません: {candidate}")
    if candidate.exists() and not candidate.is_dir():
        raise NoteTeamError(f"runパスがディレクトリではありません: {candidate}")
    resolved = candidate.resolve()
    try:
        resolved.relative_to(runs_root)
    except ValueError as exc:
        raise NoteTeamError(f"runパスが許可範囲外です: {resolved}") from exc
    return resolved


def state_path(root: Path, run_id: str) -> Path:
    return run_dir(root, run_id) / "state.json"


def load_state(root: Path, run_id: str) -> dict[str, Any]:
    path = state_path(root, run_id)
    if path.is_symlink():
        raise NoteTeamError(f"state.jsonにシンボリックリンクは使えません: {path}")
    state = load_json(path)
    validate_state(state)
    if state.get("run_id") != run_id:
        raise NoteTeamError(
            f"state.json内のrun_id={state.get('run_id')} が要求run_id={run_id} と一致しません"
        )
    return state


def save_state(root: Path, state: dict[str, Any], event: dict[str, Any]) -> None:
    state["updated_at"] = iso_now()
    state["revision"] = int(state.get("revision", 0)) + 1
    committed_event = {"at": iso_now(), **event, "state_revision": state["revision"]}
    state.setdefault("audit_log", []).append(committed_event)
    validate_state(state)
    directory = run_dir(root, state["run_id"])
    atomic_write_json(directory / "state.json", state)
    try:
        append_audit(directory, committed_event)
    except OSError:
        # state.json.audit_log is the atomic source of truth; JSONL is a readable mirror.
        pass


def initial_stage_map() -> dict[str, dict[str, Any]]:
    return {
        stage: {
            "status": "locked" if stage != "plan" else "awaiting_output",
            "attempts": 0,
            "artifact": None,
            "units": {},
        }
        for stage in STAGES
    }


def create_run(
    root: Path,
    account_id: str,
    theme_id: str,
    slug: str,
    title: str | None = None,
    product_profile: str = "free-standard",
    run_id_value: str | None = None,
    fact_pack: str | Path | None = None,
) -> tuple[dict[str, Any], bool]:
    config = load_config(root)
    verify_style_corpus(root, config)
    account, theme = get_account_theme(root, config, account_id, theme_id)
    assert_no_secret(slug, "slug")
    if run_id_value:
        assert_no_secret(run_id_value, "run_id")
    slug_value = slugify(slug)
    generated_id = f"{now_jst():%Y%m%d}-{slugify(account_id)}-{slug_value}"
    run_id_value = run_id_value or generated_id
    fact_pack_source: Path | None = None
    fact_pack_payload: bytes | None = None
    fact_pack_digest: str | None = None
    if fact_pack:
        fact_pack_source, fact_pack_payload, fact_pack_digest = load_fact_pack_input(
            root, fact_pack
        )
    with create_run_lock(root):
        directory = run_dir(root, run_id_value)
        state_file = directory / "state.json"
        if directory.exists() and not state_file.is_file():
            incomplete_root = ensure_private_directory(directory.parent, ".incomplete")
            recovered = incomplete_root / (
                f"{run_id_value}-{now_jst():%Y%m%d%H%M%S}-{secrets.token_hex(4)}"
            )
            os.replace(directory, recovered)
        if directory.exists():
            existing = load_state(root, run_id_value)
            existing_fact_digest = (
                existing.get("inputs", {}).get("fact_pack") or {}
            ).get("sha256")
            same = (
                existing.get("account_id") == account_id
                and existing.get("theme_id") == theme_id
                and existing.get("slug") == slug_value
                and existing.get("title") == title
                and existing.get("product_profile") == product_profile
                and (fact_pack_digest is None or fact_pack_digest == existing_fact_digest)
            )
            if same:
                return existing, True
            raise NoteTeamError(f"同名runが別条件で存在します: {run_id_value}")

        if product_profile not in {"free-standard", "paid-longform"}:
            raise NoteTeamError("product_profile は free-standard または paid-longform です")
        if title:
            assert_no_secret(title, "タイトル")
        try:
            directory.mkdir(mode=0o700)
        except FileExistsError as exc:
            raise NoteTeamError(f"run作成先が競合しました: {run_id_value}") from exc

        create_event = {
            "at": iso_now(),
            "action": "create",
            "actor": "orchestrator",
            "stage": "plan",
            "product_profile": product_profile,
            "state_revision": 0,
        }
        state: dict[str, Any] = {
            "schema_version": 3,
            "run_id": run_id_value,
            "slug": slug_value,
            "account_id": account_id,
            "account_display_name": account.get("display_name"),
            "theme_id": theme_id,
            "theme_name": theme.get("theme_name"),
            "title": title,
            "product_profile": product_profile,
            "current_stage": "plan",
            "status": "active",
            "stages": initial_stage_map(),
            "approvals": [],
            "external_authorizations": [],
            "inputs": {},
            "revision": 0,
            "audit_log": [create_event],
            "created_at": iso_now(),
            "updated_at": iso_now(),
        }
        if (
            fact_pack_payload is not None
            and fact_pack_source is not None
            and fact_pack_digest is not None
        ):
            store_fact_pack(
                root, state, fact_pack_source, fact_pack_payload, fact_pack_digest
            )
        atomic_write_json(directory / "state.json", state)
        append_audit(directory, create_event)
        return state, False


@locked_run_mutation
def attach_fact_pack(
    root: Path, run_id_value: str, fact_pack: str | Path, actor: str = "owner"
) -> dict[str, Any]:
    assert_no_secret(actor, "actor")
    state = load_state(root, run_id_value)
    if state["status"] != "active" or state["current_stage"] != "plan":
        raise NoteTeamError("fact packはplan承認前にだけ固定できます")
    source, payload, digest = load_fact_pack_input(root, fact_pack)
    record = store_fact_pack(root, state, source, payload, digest)
    save_state(
        root,
        state,
        {
            "action": "attach_fact_pack",
            "actor": actor,
            "stage": "plan",
            "fact_pack_sha256": record["sha256"],
        },
    )
    return state


@locked_run_mutation
def approve_fact_pack(
    root: Path,
    run_id_value: str,
    actor: str = "owner",
    *,
    owner_session_confirmed: bool = False,
) -> dict[str, Any]:
    if not owner_session_confirmed:
        raise NoteTeamError("fact pack承認はローカル承認画面から行ってください")
    if actor != "owner":
        raise NoteTeamError("fact packを承認できるのはownerだけです")
    state = load_state(root, run_id_value)
    if state["status"] != "active" or state["current_stage"] != "plan":
        raise NoteTeamError("fact packはplan承認前にだけ承認できます")
    record = verify_fact_pack(root, state, require_owner_approval=False)
    record["owner_approved_at"] = iso_now()
    record["owner_approved_by"] = actor
    save_state(
        root,
        state,
        {
            "action": "approve_fact_pack",
            "actor": actor,
            "stage": "plan",
            "fact_pack_sha256": record["sha256"],
        },
    )
    return state


def validate_state(state: dict[str, Any]) -> None:
    required = {"run_id", "account_id", "theme_id", "current_stage", "status", "stages"}
    missing = sorted(required - set(state))
    if missing:
        raise NoteTeamError(f"state.json の必須キーがありません: {', '.join(missing)}")
    if state["current_stage"] not in STAGES:
        raise NoteTeamError(f"不正な current_stage: {state['current_stage']}")
    if not isinstance(state.get("stages"), dict):
        raise NoteTeamError("state.json の stages はJSONオブジェクトである必要があります")
    if set(state["stages"]) != set(STAGES):
        raise NoteTeamError("state.json の stages が現行定義と一致しません")
    run_id_value = state.get("run_id")
    if not isinstance(run_id_value, str) or not RUN_ID_PATTERN.fullmatch(run_id_value):
        raise NoteTeamError("state.json の run_id 形式が不正です")
    if state.get("status") not in {"active", "completed", "rejected"}:
        raise NoteTeamError(f"state.json の status が不正です: {state.get('status')}")
    if not isinstance(state.get("revision", 0), int) or state.get("revision", 0) < 0:
        raise NoteTeamError("state.json の revision が不正です")
    for list_key in ("approvals", "external_authorizations", "audit_log"):
        if list_key in state and not isinstance(state[list_key], list):
            raise NoteTeamError(f"state.json の {list_key} は配列である必要があります")
    authorization_records: dict[str, dict[str, Any]] = {}
    for authorization in state.get("external_authorizations", []):
        if not isinstance(authorization, dict) or not isinstance(
            authorization.get("id"), str
        ):
            raise NoteTeamError("state.json の外部操作許可記録が不正です")
        authorization_id = authorization["id"]
        if authorization_id in authorization_records:
            raise NoteTeamError("state.json に重複した外部操作許可IDがあります")
        authorization_records[authorization_id] = authorization
    for stage, stage_data in state["stages"].items():
        if not isinstance(stage_data, dict) or not isinstance(stage_data.get("status"), str):
            raise NoteTeamError(f"stage={stage} の状態形式が不正です")
        allowed_statuses = BASE_STAGE_STATUSES | STAGE_STATUS_EXTRAS.get(stage, set())
        if stage_data["status"] not in allowed_statuses:
            raise NoteTeamError(f"stage={stage} のstatusが不正です: {stage_data['status']}")
        attempts = stage_data.get("attempts", 0)
        if isinstance(attempts, bool) or not isinstance(attempts, int) or attempts < 0 or attempts > 5:
            raise NoteTeamError(f"stage={stage} の attempts が不正です")
        artifact = stage_data.get("artifact")
        digest = stage_data.get("artifact_sha256")
        if artifact is not None and (
            not isinstance(artifact, str)
            or not isinstance(digest, str)
            or not re.fullmatch(r"[0-9a-f]{64}", digest)
        ):
            raise NoteTeamError(f"stage={stage} の成果物またはSHA-256が不正です")
        if stage_data["status"] == "review" and artifact is None:
            raise NoteTeamError(f"stage={stage} のreviewに成果物固定版がありません")
        if (
            stage_data["status"] == "review"
            and stage not in EXTERNAL_AUTH_STAGES
            and not isinstance(stage_data.get("director_qa"), dict)
        ):
            raise NoteTeamError(f"stage={stage} のreviewにDirector QA固定版がありません")
        failures = stage_data.get("quality_failures", [])
        if not isinstance(failures, list):
            raise NoteTeamError(f"stage={stage} の quality_failures が不正です")
        if stage == "x_publish" and stage_data["status"] in {
            "external_in_progress",
            "reconciliation_required",
        }:
            components = stage_data.get("components")
            if not isinstance(components, dict) or set(components) != {"main", "reply"}:
                raise NoteTeamError("x_publishのcomponent台帳が不正です")
            for component_name in ("main", "reply"):
                component = components[component_name]
                if not isinstance(component, dict) or component.get("status") not in {
                    "pending",
                    "posted",
                }:
                    raise NoteTeamError(f"X {component_name} componentの状態が不正です")
                if component.get("status") == "posted" and (
                    not isinstance(component.get("tweet_id"), str)
                    or not component["tweet_id"].isdigit()
                    or not isinstance(component.get("tweet_url"), str)
                ):
                    raise NoteTeamError(f"X {component_name} componentの結果が不正です")
            if (
                components["reply"].get("status") == "posted"
                and components["main"].get("status") != "posted"
            ):
                raise NoteTeamError("X本投稿より先にリプを確定できません")
        units = stage_data.get("units", {})
        if not isinstance(units, dict):
            raise NoteTeamError(f"stage={stage} の units が不正です")
        if stage_data["status"] in {"unit_cycle", "awaiting_final_output"} and not units:
            raise NoteTeamError(f"stage={stage} の単位工程にunitがありません")
        if stage_data["status"] == "awaiting_final_output" and not all(
            item.get("status") == "approved" for item in units.values()
        ):
            raise NoteTeamError(f"stage={stage} の最終原稿待ちに未承認unitがあります")
        for unit, unit_data in units.items():
            if not isinstance(unit, str) or not isinstance(unit_data, dict):
                raise NoteTeamError(f"stage={stage} のunit定義が不正です")
            if unit_data.get("status") not in UNIT_STATUSES:
                raise NoteTeamError(
                    f"stage={stage} unit={unit} のstatusが不正です: {unit_data.get('status')}"
                )
            unit_attempts = unit_data.get("attempts", 0)
            if (
                isinstance(unit_attempts, bool)
                or not isinstance(unit_attempts, int)
                or unit_attempts < 0
                or unit_attempts > 5
            ):
                raise NoteTeamError(f"stage={stage} unit={unit} の attempts が不正です")
            unit_artifact = unit_data.get("artifact")
            unit_digest = unit_data.get("artifact_sha256")
            if unit_artifact is not None and (
                not isinstance(unit_artifact, str)
                or not isinstance(unit_digest, str)
                or not re.fullmatch(r"[0-9a-f]{64}", unit_digest)
            ):
                raise NoteTeamError(
                    f"stage={stage} unit={unit} の成果物またはSHA-256が不正です"
                )
            if unit_data.get("status") == "review" and (
                unit_artifact is None
                or not isinstance(unit_data.get("director_qa"), dict)
            ):
                raise NoteTeamError(
                    f"stage={stage} unit={unit} のreview固定版がありません"
                )
            unit_failures = unit_data.get("quality_failures", [])
            if not isinstance(unit_failures, list):
                raise NoteTeamError(
                    f"stage={stage} unit={unit} の quality_failures が不正です"
                )
    if state["status"] == "active":
        current_index = STAGES.index(state["current_stage"])
        for earlier in STAGES[:current_index]:
            if state["stages"][earlier]["status"] != "approved":
                raise NoteTeamError(f"現在工程より前の {earlier} がapprovedではありません")
        current_status = state["stages"][state["current_stage"]]["status"]
        if current_status in {"locked", "approved", "fatal_violation"}:
            raise NoteTeamError(f"現在工程のstatusが不正です: {current_status}")
        for later in STAGES[current_index + 1 :]:
            if state["stages"][later]["status"] != "locked":
                raise NoteTeamError(f"現在工程より後の {later} がlockedではありません")
        if state["current_stage"] in EXTERNAL_AUTH_STAGES and current_status in {
            "authorized",
            "external_in_progress",
            "reconciliation_required",
        }:
            external_stage = state["current_stage"]
            stage_data = state["stages"][external_stage]
            if not stage_data.get("authorization_id"):
                raise NoteTeamError(f"{external_stage}の外部状態にauthorization_idがありません")
            authorization = authorization_records.get(stage_data["authorization_id"])
            if not authorization or authorization.get("stage") != external_stage:
                raise NoteTeamError(f"{external_stage}のauthorization_idに対応する許可記録がありません")
            if current_status == "authorized" and authorization.get("consumed_at") is not None:
                raise NoteTeamError(f"未使用状態の{external_stage}許可がすでに消費されています")
            if current_status in {"external_in_progress", "reconciliation_required"} and (
                not stage_data.get("claim_id") or not stage_data.get("claim_expires_at")
            ):
                raise NoteTeamError(f"{external_stage}のclaim状態にIDまたは期限がありません")
            if current_status in {"external_in_progress", "reconciliation_required"} and (
                authorization.get("consumed_at") is None
                or authorization.get("claim_id") != stage_data.get("claim_id")
            ):
                raise NoteTeamError(f"{external_stage}のclaimに対応する消費済み許可記録がありません")
    if state["status"] == "completed":
        if state["current_stage"] != "analysis":
            raise NoteTeamError("completed runのcurrent_stageはanalysisである必要があります")
        if any(state["stages"][stage]["status"] != "approved" for stage in STAGES):
            raise NoteTeamError("completed runに未承認工程があります")


def active_stage(state: dict[str, Any], stage: str) -> dict[str, Any]:
    if state["status"] in TERMINAL_STATUSES:
        raise NoteTeamError(f"runは {state['status']} のため変更できません")
    if stage != state["current_stage"]:
        raise NoteTeamError(
            f"現在の工程は {state['current_stage']} です。{stage} は操作できません"
        )
    return state["stages"][stage]


def artifact_relative(run_directory: Path, artifact: str) -> str:
    candidate = resolve_inside(run_directory, artifact)
    read_safe_text(candidate, "成果物")
    return candidate.relative_to(run_directory.resolve()).as_posix()


def validate_director_qa(
    root: Path,
    stage: str,
    unit: str | None,
    artifact_digest: str,
    qa_path: Path,
) -> dict[str, Any]:
    payload = load_json(qa_path)
    required = {
        "stage",
        "unit",
        "checked_artifact_sha256",
        "score",
        "verdict",
        "fatal_violations",
        "checked_at",
        "reviewer",
    }
    if not isinstance(payload, dict) or required - set(payload):
        missing = sorted(required - set(payload if isinstance(payload, dict) else {}))
        raise NoteTeamError(f"Director QA記録の必須項目がありません: {', '.join(missing)}")
    if payload["stage"] != stage or payload["unit"] != unit:
        raise NoteTeamError("Director QA記録のstage/unitが成果物と一致しません")
    if payload["checked_artifact_sha256"] != artifact_digest:
        raise NoteTeamError("Directorが採点したバイトとsubmit対象が一致しません")
    score = payload["score"]
    if isinstance(score, bool) or not isinstance(score, int) or not 0 <= score <= 100:
        raise NoteTeamError("Director QAのscoreは0〜100の整数で指定してください")
    violations = payload["fatal_violations"]
    if not isinstance(violations, list):
        raise NoteTeamError("Director QAのfatal_violationsは配列で指定してください")
    if violations:
        raise FatalQualityError("Director QAに致命的違反があるためrunを停止します")
    gate = max(85, int(load_config(root)["article_defaults"]["quality_gate"]))
    if score < gate or payload["verdict"] != "PASS":
        raise NoteTeamError(f"Director QAが不合格です: score={score}, gate={gate}")
    if payload["reviewer"] != "note-director":
        raise NoteTeamError("Director QAのreviewerは note-director である必要があります")
    parse_checked_at(payload["checked_at"], "Director QA checked_at")
    return payload


def validate_plan_proposals(path: Path) -> list[str]:
    content, _ = read_safe_text(path, "plan成果物")
    proposal_ids = re.findall(r"(?mi)^proposal_id:\s*(plan-0[1-3])\s*$", content)
    expected = ["plan-01", "plan-02", "plan-03"]
    if proposal_ids != expected:
        raise NoteTeamError(
            "plan成果物は proposal_id: plan-01 / plan-02 / plan-03 をこの順で1回ずつ含めてください"
        )
    return proposal_ids


URL_TOKEN_PATTERN = re.compile(r"https?://[^\s<>「」]+", re.IGNORECASE)


def x_weighted_length(text: str) -> int:
    """Return the X weighted length used by the workflow.

    X counts URLs as 23 characters and most CJK/emoji code points as weight 2.
    The weight-1 ranges below mirror twitter-text's published configuration.
    """
    total = 0
    cursor = 0
    for match in URL_TOKEN_PATTERN.finditer(text):
        total += sum(
            1
            if (
                ord(char) <= 0x10FF
                or 0x2000 <= ord(char) <= 0x200D
                or 0x2010 <= ord(char) <= 0x201F
                or 0x2032 <= ord(char) <= 0x2037
            )
            else 2
            for char in text[cursor : match.start()]
        )
        total += 23
        cursor = match.end()
    total += sum(
        1
        if (
            ord(char) <= 0x10FF
            or 0x2000 <= ord(char) <= 0x200D
            or 0x2010 <= ord(char) <= 0x201F
            or 0x2032 <= ord(char) <= 0x2037
        )
        else 2
        for char in text[cursor:]
    )
    return total


def validate_promotion_variants(path: Path) -> list[str]:
    payload = load_json(path)
    if not isinstance(payload, dict) or set(payload) != {"variants"}:
        raise NoteTeamError("promotion成果物は variants だけを持つJSONにしてください")
    variants = payload.get("variants")
    if not isinstance(variants, list) or len(variants) != 3:
        raise NoteTeamError("promotion成果物はX投稿案を3案にしてください")
    expected = ["x-01", "x-02", "x-03"]
    ids: list[str] = []
    for index, variant in enumerate(variants):
        required = {"promotion_id", "intent", "primary_text", "reply_text_template"}
        if not isinstance(variant, dict) or required - set(variant):
            raise NoteTeamError(f"promotion案{index + 1}の必須項目が足りません")
        promotion_id = variant["promotion_id"]
        if promotion_id != expected[index]:
            raise NoteTeamError("promotion_idは x-01 / x-02 / x-03 をこの順で指定してください")
        for key in ("intent", "primary_text", "reply_text_template"):
            if not isinstance(variant[key], str) or not variant[key].strip():
                raise NoteTeamError(f"{promotion_id} の {key} が空です")
        primary = variant["primary_text"]
        reply_template = variant["reply_text_template"]
        if "[NOTE_URL]" in primary or URL_TOKEN_PATTERN.search(primary):
            raise NoteTeamError(f"{promotion_id} の本文にnote URLを入れないでください")
        if reply_template.count("[NOTE_URL]") != 1:
            raise NoteTeamError(f"{promotion_id} の1件目リプに [NOTE_URL] を1回だけ入れてください")
        if x_weighted_length(primary) > 280:
            raise NoteTeamError(f"{promotion_id} のX本文が重み付280文字を超えています")
        ids.append(promotion_id)
    return ids


def selected_promotion_variant(root: Path, state: dict[str, Any]) -> dict[str, Any]:
    selected_id = state.get("selected_promotion_id")
    if not isinstance(selected_id, str):
        raise NoteTeamError("X投稿に使うpromotion案が選択されていません")
    target = state["stages"]["promotion"]
    directory = run_dir(root, state["run_id"])
    verify_snapshot(directory, target)
    payload = load_json_with_expected_sha(
        resolve_inside(directory, target.get("artifact") or ""),
        target.get("artifact_sha256") or "",
        "promotion承認版",
    )
    validate_promotion_variants(resolve_inside(directory, target.get("artifact") or ""))
    for variant in payload["variants"]:
        if variant.get("promotion_id") == selected_id:
            return variant
    raise NoteTeamError("選択済みpromotion IDが承認版にありません")


def validate_analysis_binding(root: Path, path: Path) -> dict[str, str]:
    content, _ = read_safe_text(path, "analysis成果物")
    fields: dict[str, str] = {}
    for key in (
        "metrics_month",
        "note_csv_sha256",
        "x_csv_sha256",
        "metrics_snapshot_sha256",
    ):
        match = re.search(rf"(?mi)^{key}:\s*(\S+)\s*$", content)
        if not match:
            raise NoteTeamError(f"analysis成果物に {key}: がありません")
        fields[key] = match.group(1)
    result, _ = analyze_metrics(root, fields["metrics_month"])
    provenance = result["provenance"]
    if fields["note_csv_sha256"] != provenance["note_csv"]["sha256"]:
        raise NoteTeamError("analysisがnote_metrics.csvの現行SHA-256に紐づいていません")
    if fields["x_csv_sha256"] != provenance["x_csv"]["sha256"]:
        raise NoteTeamError("analysisがx_metrics.csvの現行SHA-256に紐づいていません")
    canonical_digest = metrics_snapshot_sha256(result)
    if fields["metrics_snapshot_sha256"] != canonical_digest:
        raise NoteTeamError("analysisが機械集計レポートのSHA-256に紐づいていません")
    narrative = content
    for key in fields:
        narrative = re.sub(rf"(?mi)^{key}:\s*\S+\s*$", "", narrative)
    if re.search(r"\d", narrative):
        raise NoteTeamError(
            "Analyst解釈本文に数値を再記載できません。数値は機械集計レポートだけを正本にしてください"
        )
    fields["metrics_snapshot_sha256"] = canonical_digest
    return fields


def count_manuscript_characters(content: str) -> int:
    """Count visible Japanese manuscript characters deterministically.

    Whitespace and Markdown control syntax/URLs are excluded; link and image alt
    text remain countable visible text.
    """
    visible = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", content)
    visible = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", visible)
    visible = re.sub(r"<[^>]+>", "", visible)
    visible = re.sub(r"(?m)^\s*```[^\n]*$", "", visible)
    visible = re.sub(r"[`#>*_~|-]", "", visible)
    return len(re.sub(r"\s+", "", visible))


def manuscript_character_range(
    root: Path, state: dict[str, Any]
) -> tuple[int, int]:
    config = load_config(root)
    if state.get("product_profile") == "paid-longform":
        values = config["product_profiles"]["paid-longform"]["word_count_target"]
    else:
        account, _ = get_account_theme(
            root, config, state["account_id"], state["theme_id"]
        )
        values = account.get("word_count_target")
    if (
        not isinstance(values, list)
        or len(values) != 2
        or any(isinstance(value, bool) or not isinstance(value, int) for value in values)
        or values[0] < 1
        or values[0] > values[1]
    ):
        raise NoteTeamError("原稿文字数の下限・上限設定が不正です")
    return values[0], values[1]


def validate_note_draft_record(
    root: Path,
    state: dict[str, Any],
    artifact_path: Path,
    preflight_payload: dict[str, Any] | None = None,
) -> None:
    payload = load_json(artifact_path)
    required = {
        "account_id",
        "expected_note_id",
        "observed_note_id",
        "draft_url",
        "editor_draft_id",
        "operation",
        "initial_content_empty_before_write",
        "saved_indicator",
        "published",
        "draft_saved_at",
        "checked_at",
        "image_status",
        "claim_id",
        "manuscript_sha256",
        "preflight_sha256",
    }
    if not isinstance(payload, dict) or required - set(payload):
        missing = sorted(required - set(payload if isinstance(payload, dict) else {}))
        raise NoteTeamError(f"note下書き確認記録の必須項目がありません: {', '.join(missing)}")
    config = load_config(root)
    account, _ = get_account_theme(root, config, state["account_id"], state["theme_id"])
    expected = account.get("note_id")
    if not expected:
        raise NoteTeamError("accounts.json に note_id がありません")
    if payload["account_id"] != state["account_id"]:
        raise NoteTeamError("note下書き確認記録の account_id がrunと一致しません")
    if payload["expected_note_id"] != expected or payload["observed_note_id"] != expected:
        raise NoteTeamError("予定note IDと画面上のnote IDが一致しません")
    if payload["saved_indicator"] is not True:
        raise NoteTeamError("note画面の下書き保存完了を確認できていません")
    if payload["published"] is not False:
        raise NoteTeamError("初期フローでは公開済み記録を受け付けません")
    if payload["operation"] != "create_new_draft":
        raise NoteTeamError("既存noteの上書き結果は受け付けません")
    if payload["initial_content_empty_before_write"] is not True:
        raise NoteTeamError("書き込み前が空の新規記事だったことを確認できていません")
    stage_data = state["stages"]["note_draft"]
    if payload["claim_id"] != stage_data.get("claim_id"):
        raise NoteTeamError("note下書き確認記録のclaim_idが現在の一回限り許可と一致しません")
    if payload["manuscript_sha256"] != state["stages"]["draft"].get("artifact_sha256"):
        raise NoteTeamError("note下書き確認記録の原稿SHA-256が承認版と一致しません")
    if payload["preflight_sha256"] != stage_data.get("preflight_sha256"):
        raise NoteTeamError("note下書き確認記録の事前確認SHA-256が一致しません")
    draft_url = payload["draft_url"]
    validate_editor_draft_url(
        draft_url, payload["editor_draft_id"], "note下書き確認記録"
    )
    if preflight_payload is None:
        preflight_path = resolve_inside(
            run_dir(root, state["run_id"]), stage_data.get("preflight_artifact") or ""
        )
        preflight_payload = load_json_with_expected_sha(
            preflight_path,
            stage_data.get("preflight_sha256") or "",
            "note事前確認固定版",
        )
    if (
        preflight_payload.get("operation") != "create_new_draft"
        or preflight_payload.get("initial_content_empty") is not True
    ):
        raise NoteTeamError("結果が承認済みの空の新規投稿画面に紐づいていません")
    image_status = payload["image_status"]
    if not isinstance(image_status, dict):
        raise NoteTeamError("image_status は画像反映確認のJSONオブジェクトで指定してください")
    image_required = {
        "mode",
        "heading_image_verified",
        "inline_images_expected",
        "inline_images_verified",
        "pending",
    }
    if image_required - set(image_status):
        raise NoteTeamError("image_status の必須項目が足りません")
    mode = image_status["mode"]
    heading_verified = image_status["heading_image_verified"]
    expected_images = image_status["inline_images_expected"]
    verified_images = image_status["inline_images_verified"]
    pending_images = image_status["pending"]
    if (
        isinstance(expected_images, bool)
        or isinstance(verified_images, bool)
        or not isinstance(expected_images, int)
        or not isinstance(verified_images, int)
        or expected_images < 0
        or verified_images < 0
        or not isinstance(pending_images, list)
    ):
        raise NoteTeamError("image_status の画像数またはpending形式が不正です")
    if mode == "image-free":
        if heading_verified is not False or expected_images != 0 or verified_images != 0 or pending_images:
            raise NoteTeamError("image-free は画像0件・見出し画像なし・pendingなしで記録してください")
    elif mode == "verified":
        if heading_verified is not True or verified_images != expected_images or pending_images:
            raise NoteTeamError("画像あり下書きは見出し画像と本文画像全件の反映確認が必要です")
    else:
        raise NoteTeamError("image_status.mode は image-free または verified です")
    draft_saved_at = parse_checked_at(
        payload["draft_saved_at"], "note下書き確認記録 draft_saved_at"
    )
    checked_at = require_recent_check(
        payload["checked_at"], "note下書き確認記録 checked_at"
    )
    authorization = next(
        (
            item
            for item in state.get("external_authorizations", [])
            if item.get("claim_id") == payload["claim_id"]
        ),
        None,
    )
    if not authorization or not authorization.get("claimed_at"):
        raise NoteTeamError("note下書き確認記録に対応するclaimがありません")
    claimed_at = parse_checked_at(authorization["claimed_at"], "claim日時")
    claim_expires_at = parse_checked_at(
        authorization.get("claim_expires_at"), "claim期限"
    )
    saved_jst = draft_saved_at.astimezone(now_jst().tzinfo)
    checked_jst = checked_at.astimezone(now_jst().tzinfo)
    if saved_jst < claimed_at.astimezone(now_jst().tzinfo):
        raise NoteTeamError("note下書き保存日時がclaimより前です")
    if saved_jst > claim_expires_at.astimezone(now_jst().tzinfo):
        raise NoteTeamError("note下書き保存がclaimの5分実行期限を超えています")
    if checked_jst < saved_jst:
        raise NoteTeamError("note下書きの現在確認日時が保存日時より前です")


def validate_note_preflight(
    root: Path,
    state: dict[str, Any],
    artifact_path: Path,
    expected_sha256: str | None = None,
    *,
    require_fresh: bool = True,
) -> dict[str, Any]:
    payload = (
        load_json_with_expected_sha(
            artifact_path, expected_sha256, "note事前確認固定版"
        )
        if expected_sha256
        else load_json(artifact_path)
    )
    required = {
        "account_id",
        "expected_note_id",
        "observed_note_id",
        "editor_ready",
        "operation",
        "editor_url",
        "initial_content_empty",
        "checked_at",
    }
    if not isinstance(payload, dict) or required - set(payload):
        missing = sorted(required - set(payload if isinstance(payload, dict) else {}))
        raise NoteTeamError(f"note事前確認記録の必須項目がありません: {', '.join(missing)}")
    config = load_config(root)
    account, _ = get_account_theme(root, config, state["account_id"], state["theme_id"])
    expected = account.get("note_id")
    if not isinstance(expected, str) or not expected.strip():
        raise NoteTeamError("accounts.json に有効な note_id がありません")
    if (
        payload["account_id"] != state["account_id"]
        or payload["expected_note_id"] != expected
        or payload["observed_note_id"] != expected
    ):
        raise NoteTeamError("予定note IDと事前確認画面のnote IDが一致しません")
    if payload["editor_ready"] is not True:
        raise NoteTeamError("noteエディタを書き込み前に確認できていません")
    if payload["operation"] != "create_new_draft":
        raise NoteTeamError("既存noteの編集は対象外です。operation=create_new_draft が必要です")
    if payload["initial_content_empty"] is not True:
        raise NoteTeamError("新規下書きの初期本文が空であることを確認できていません")
    validate_new_draft_url(payload["editor_url"])
    if require_fresh:
        require_recent_check(payload["checked_at"], "note事前確認 checked_at")
    else:
        parse_checked_at(payload["checked_at"], "note事前確認 checked_at")
    return payload


def load_stage_json(root: Path, state: dict[str, Any], stage: str) -> dict[str, Any]:
    target = state["stages"][stage]
    directory = run_dir(root, state["run_id"])
    verify_snapshot(directory, target)
    payload = load_json_with_expected_sha(
        resolve_inside(directory, target.get("artifact") or ""),
        target.get("artifact_sha256") or "",
        f"{stage}承認版",
    )
    if not isinstance(payload, dict):
        raise NoteTeamError(f"{stage}承認版はJSONオブジェクトである必要があります")
    return payload


def validate_note_publish_preflight(
    root: Path,
    state: dict[str, Any],
    artifact_path: Path,
    expected_sha256: str | None = None,
    *,
    require_fresh: bool = True,
) -> dict[str, Any]:
    payload = (
        load_json_with_expected_sha(artifact_path, expected_sha256, "note公開事前確認固定版")
        if expected_sha256
        else load_json(artifact_path)
    )
    required = {
        "account_id",
        "expected_note_id",
        "observed_note_id",
        "operation",
        "editor_ready",
        "editor_draft_id",
        "draft_url",
        "draft_record_sha256",
        "manuscript_sha256",
        "content_readback_verified",
        "publish_settings_verified",
        "publish_button_ready",
        "published",
        "checked_at",
    }
    if not isinstance(payload, dict) or required - set(payload):
        missing = sorted(required - set(payload if isinstance(payload, dict) else {}))
        raise NoteTeamError(f"note公開事前確認の必須項目がありません: {', '.join(missing)}")
    config = load_config(root)
    account, _ = get_account_theme(root, config, state["account_id"], state["theme_id"])
    expected_note_id = account.get("note_id")
    draft_record = load_stage_json(root, state, "note_draft")
    if (
        payload["account_id"] != state["account_id"]
        or payload["expected_note_id"] != expected_note_id
        or payload["observed_note_id"] != expected_note_id
    ):
        raise NoteTeamError("note公開事前確認のアカウントが予定と一致しません")
    if payload["operation"] != "publish_existing_draft":
        raise NoteTeamError("note公開は operation=publish_existing_draft に限定します")
    if payload["editor_ready"] is not True or payload["publish_button_ready"] is not True:
        raise NoteTeamError("noteの対象下書きと公開ボタンを確認できていません")
    if payload["published"] is not False:
        raise NoteTeamError("公開操作前の未公開下書きだけが対象です")
    if payload["content_readback_verified"] is not True:
        raise NoteTeamError("承認済み原稿とnoteエディタの本文照合が必要です")
    if payload["publish_settings_verified"] is not True:
        raise NoteTeamError("無料・有料、価格、タグ等の公開設定確認が必要です")
    if payload["editor_draft_id"] != draft_record.get("editor_draft_id"):
        raise NoteTeamError("公開対象のdraft IDが保存済み下書きと一致しません")
    if payload["draft_url"] != draft_record.get("draft_url"):
        raise NoteTeamError("公開対象の編集URLが保存済み下書きと一致しません")
    validate_editor_draft_url(payload["draft_url"], payload["editor_draft_id"], "note公開事前確認")
    if payload["draft_record_sha256"] != state["stages"]["note_draft"].get("artifact_sha256"):
        raise NoteTeamError("note公開事前確認が承認済み下書き結果に紐づいていません")
    if payload["manuscript_sha256"] != state["stages"]["draft"].get("artifact_sha256"):
        raise NoteTeamError("note公開事前確認の原稿SHA-256が承認版と一致しません")
    if require_fresh:
        require_recent_check(payload["checked_at"], "note公開事前確認 checked_at")
    else:
        parse_checked_at(payload["checked_at"], "note公開事前確認 checked_at")
    return payload


def validate_x_publish_preflight(
    root: Path,
    state: dict[str, Any],
    artifact_path: Path,
    expected_sha256: str | None = None,
    *,
    require_fresh: bool = True,
) -> dict[str, Any]:
    payload = (
        load_json_with_expected_sha(artifact_path, expected_sha256, "X投稿事前確認固定版")
        if expected_sha256
        else load_json(artifact_path)
    )
    required = {
        "platform",
        "operation",
        "expected_x_user_id",
        "observed_x_user_id",
        "expected_x_username",
        "observed_x_username",
        "selected_promotion_id",
        "primary_text",
        "reply_text",
        "primary_text_sha256",
        "reply_text_sha256",
        "note_public_url",
        "promotion_sha256",
        "note_publish_sha256",
        "dry_run_ready",
        "checked_at",
    }
    if not isinstance(payload, dict) or required - set(payload):
        missing = sorted(required - set(payload if isinstance(payload, dict) else {}))
        raise NoteTeamError(f"X投稿事前確認の必須項目がありません: {', '.join(missing)}")
    if payload["platform"] != "x" or payload["operation"] != "create_post_and_reply":
        raise NoteTeamError("X投稿事前確認のplatform/operationが不正です")
    if payload["dry_run_ready"] is not True:
        raise NoteTeamError("X投稿の事前検証が合格していません")
    for key in ("expected_x_user_id", "observed_x_user_id"):
        if not isinstance(payload[key], str) or not re.fullmatch(r"\d{3,30}", payload[key]):
            raise NoteTeamError(f"{key}の形式が不正です")
    for key in ("expected_x_username", "observed_x_username"):
        if not isinstance(payload[key], str) or not re.fullmatch(r"[A-Za-z0-9_]{1,15}", payload[key]):
            raise NoteTeamError(f"{key}の形式が不正です")
    if (
        payload["expected_x_user_id"] != payload["observed_x_user_id"]
        or payload["expected_x_username"].lower() != payload["observed_x_username"].lower()
    ):
        raise NoteTeamError("Xの予定アカウントとAPI認証アカウントが一致しません")
    configured_x = load_config(root).get("x_account", {})
    if configured_x:
        if (
            configured_x.get("user_id") != payload["expected_x_user_id"]
            or str(configured_x.get("username", "")).lower()
            != payload["expected_x_username"].lower()
        ):
            raise NoteTeamError("X投稿事前確認がteam.jsonの予定Xアカウントと一致しません")
    variant = selected_promotion_variant(root, state)
    note_publish_record = load_stage_json(root, state, "note_publish")
    public_url = note_publish_record.get("public_url")
    if payload["selected_promotion_id"] != state.get("selected_promotion_id"):
        raise NoteTeamError("X投稿案IDがオーナー選択と一致しません")
    expected_primary = variant["primary_text"]
    expected_reply = variant["reply_text_template"].replace("[NOTE_URL]", str(public_url))
    if payload["primary_text"] != expected_primary or payload["reply_text"] != expected_reply:
        raise NoteTeamError("X本文または1件目リプが承認済み案と公開note URLから決まる文面と一致しません")
    if payload["note_public_url"] != public_url:
        raise NoteTeamError("X投稿に埋め込むnote URLが公開確認済みURLと一致しません")
    if payload["promotion_sha256"] != state["stages"]["promotion"].get("artifact_sha256"):
        raise NoteTeamError("X投稿がpromotion承認版に紐づいていません")
    if payload["note_publish_sha256"] != state["stages"]["note_publish"].get("artifact_sha256"):
        raise NoteTeamError("X投稿がnote公開結果に紐づいていません")
    if payload["primary_text_sha256"] != sha256_bytes(expected_primary.encode("utf-8")):
        raise NoteTeamError("X本文のSHA-256が一致しません")
    if payload["reply_text_sha256"] != sha256_bytes(expected_reply.encode("utf-8")):
        raise NoteTeamError("Xリプ本文のSHA-256が一致しません")
    if x_weighted_length(expected_primary) > 280 or x_weighted_length(expected_reply) > 280:
        raise NoteTeamError("X本文またはリプが重み付280文字を超えています")
    if require_fresh:
        require_recent_check(payload["checked_at"], "X投稿事前確認 checked_at")
    else:
        parse_checked_at(payload["checked_at"], "X投稿事前確認 checked_at")
    return payload


def validate_external_preflight(
    root: Path,
    state: dict[str, Any],
    stage: str,
    artifact_path: Path,
    expected_sha256: str | None = None,
    *,
    require_fresh: bool = True,
) -> dict[str, Any]:
    validators = {
        "note_draft": validate_note_preflight,
        "note_publish": validate_note_publish_preflight,
        "x_publish": validate_x_publish_preflight,
    }
    try:
        validator = validators[stage]
    except KeyError as exc:
        raise NoteTeamError(f"事前確認の対象外工程です: {stage}") from exc
    return validator(
        root,
        state,
        artifact_path,
        expected_sha256,
        require_fresh=require_fresh,
    )


def validate_claim_timing(
    state: dict[str, Any],
    stage: str,
    claim_id: Any,
    mutated_at: Any,
    checked_at: Any,
    label: str,
) -> None:
    stage_data = state["stages"][stage]
    if claim_id != stage_data.get("claim_id"):
        raise NoteTeamError(f"{label}のclaim_idが現在の一回限り許可と一致しません")
    authorization = next(
        (
            item
            for item in state.get("external_authorizations", [])
            if item.get("stage") == stage and item.get("claim_id") == claim_id
        ),
        None,
    )
    if not authorization or not authorization.get("claimed_at"):
        raise NoteTeamError(f"{label}に対応するclaimがありません")
    claimed = parse_checked_at(authorization["claimed_at"], f"{label} claim日時")
    expires = parse_checked_at(authorization.get("claim_expires_at"), f"{label} claim期限")
    mutated = parse_checked_at(mutated_at, f"{label} 外部変更日時")
    checked = require_recent_check(checked_at, f"{label} checked_at")
    tz = now_jst().tzinfo
    if mutated.astimezone(tz) < claimed.astimezone(tz):
        raise NoteTeamError(f"{label}の外部変更日時がclaimより前です")
    if mutated.astimezone(tz) > expires.astimezone(tz):
        raise NoteTeamError(f"{label}の外部変更がclaimの5分期限を超えています")
    if checked.astimezone(tz) < mutated.astimezone(tz):
        raise NoteTeamError(f"{label}の確認日時が外部変更日時より前です")


def validate_note_publish_record(
    root: Path,
    state: dict[str, Any],
    artifact_path: Path,
    preflight_payload: dict[str, Any] | None = None,
) -> None:
    payload = load_json(artifact_path)
    required = {
        "account_id",
        "expected_note_id",
        "observed_note_id",
        "operation",
        "editor_draft_id",
        "draft_url",
        "public_url",
        "published",
        "content_readback_verified",
        "publish_settings_verified",
        "published_at",
        "checked_at",
        "claim_id",
        "manuscript_sha256",
        "draft_record_sha256",
        "preflight_sha256",
    }
    if not isinstance(payload, dict) or required - set(payload):
        missing = sorted(required - set(payload if isinstance(payload, dict) else {}))
        raise NoteTeamError(f"note公開結果の必須項目がありません: {', '.join(missing)}")
    config = load_config(root)
    account, _ = get_account_theme(root, config, state["account_id"], state["theme_id"])
    expected_note_id = account.get("note_id")
    draft_record = load_stage_json(root, state, "note_draft")
    stage_data = state["stages"]["note_publish"]
    if (
        payload["account_id"] != state["account_id"]
        or payload["expected_note_id"] != expected_note_id
        or payload["observed_note_id"] != expected_note_id
    ):
        raise NoteTeamError("note公開結果のアカウントが予定と一致しません")
    if payload["operation"] != "publish_existing_draft" or payload["published"] is not True:
        raise NoteTeamError("保存済み下書きの公開完了結果だけを受け付けます")
    if payload["content_readback_verified"] is not True or payload["publish_settings_verified"] is not True:
        raise NoteTeamError("note公開ページの本文と公開設定の読み戻し確認が必要です")
    if (
        payload["editor_draft_id"] != draft_record.get("editor_draft_id")
        or payload["draft_url"] != draft_record.get("draft_url")
    ):
        raise NoteTeamError("note公開結果が承認済み下書きと一致しません")
    validate_editor_draft_url(payload["draft_url"], payload["editor_draft_id"], "note公開結果")
    validate_note_public_url(
        payload["public_url"],
        expected_note_id,
        "note公開結果",
        payload["editor_draft_id"],
    )
    if payload["manuscript_sha256"] != state["stages"]["draft"].get("artifact_sha256"):
        raise NoteTeamError("note公開結果の原稿SHA-256が承認版と一致しません")
    if payload["draft_record_sha256"] != state["stages"]["note_draft"].get("artifact_sha256"):
        raise NoteTeamError("note公開結果が承認済み下書き結果に紐づいていません")
    if payload["preflight_sha256"] != stage_data.get("preflight_sha256"):
        raise NoteTeamError("note公開結果の事前確認SHA-256が一致しません")
    if preflight_payload is None:
        preflight_payload = validate_note_publish_preflight(
            root,
            state,
            resolve_inside(run_dir(root, state["run_id"]), stage_data.get("preflight_artifact") or ""),
            stage_data.get("preflight_sha256"),
            require_fresh=False,
        )
    if payload["editor_draft_id"] != preflight_payload.get("editor_draft_id"):
        raise NoteTeamError("note公開結果が事前確認したdraft IDと一致しません")
    validate_claim_timing(
        state,
        "note_publish",
        payload["claim_id"],
        payload["published_at"],
        payload["checked_at"],
        "note公開結果",
    )


def validate_x_publish_record(
    root: Path,
    state: dict[str, Any],
    artifact_path: Path,
    preflight_payload: dict[str, Any] | None = None,
) -> None:
    payload = load_json(artifact_path)
    required = {
        "platform",
        "operation",
        "expected_x_user_id",
        "observed_x_user_id",
        "expected_x_username",
        "observed_x_username",
        "selected_promotion_id",
        "note_public_url",
        "primary_text_sha256",
        "reply_text_sha256",
        "promotion_sha256",
        "note_publish_sha256",
        "primary_tweet_id",
        "primary_tweet_url",
        "primary_author_id",
        "reply_tweet_id",
        "reply_tweet_url",
        "reply_author_id",
        "reply_to_tweet_id",
        "api_readback_verified",
        "posted_at",
        "reply_posted_at",
        "checked_at",
        "claim_id",
        "preflight_sha256",
    }
    if not isinstance(payload, dict) or required - set(payload):
        missing = sorted(required - set(payload if isinstance(payload, dict) else {}))
        raise NoteTeamError(f"X投稿結果の必須項目がありません: {', '.join(missing)}")
    stage_data = state["stages"]["x_publish"]
    if preflight_payload is None:
        preflight_payload = validate_x_publish_preflight(
            root,
            state,
            resolve_inside(run_dir(root, state["run_id"]), stage_data.get("preflight_artifact") or ""),
            stage_data.get("preflight_sha256"),
            require_fresh=False,
        )
    identity_fields = (
        "expected_x_user_id",
        "observed_x_user_id",
        "expected_x_username",
        "observed_x_username",
        "selected_promotion_id",
        "note_public_url",
        "primary_text_sha256",
        "reply_text_sha256",
        "promotion_sha256",
        "note_publish_sha256",
    )
    if payload["platform"] != "x" or payload["operation"] != "create_post_and_reply":
        raise NoteTeamError("X投稿結果のplatform/operationが不正です")
    if any(payload[key] != preflight_payload.get(key) for key in identity_fields):
        raise NoteTeamError("X投稿結果が承認済み事前確認と一致しません")
    if payload["preflight_sha256"] != stage_data.get("preflight_sha256"):
        raise NoteTeamError("X投稿結果の事前確認SHA-256が一致しません")
    if payload["api_readback_verified"] is not True:
        raise NoteTeamError("X APIで本文、投稿者、返信先を読み戻し確認できていません")
    expected_user_id = payload["expected_x_user_id"]
    if payload["primary_author_id"] != expected_user_id or payload["reply_author_id"] != expected_user_id:
        raise NoteTeamError("X投稿結果のauthor IDが予定アカウントと一致しません")
    if payload["reply_to_tweet_id"] != payload["primary_tweet_id"]:
        raise NoteTeamError("Xリプの返信先が本投稿と一致しません")
    components = stage_data.get("components")
    if not isinstance(components, dict):
        raise NoteTeamError("X投稿のcomponent台帳がありません")
    for component, id_key, url_key in (
        ("main", "primary_tweet_id", "primary_tweet_url"),
        ("reply", "reply_tweet_id", "reply_tweet_url"),
    ):
        entry = components.get(component, {})
        if (
            entry.get("status") != "posted"
            or entry.get("tweet_id") != payload[id_key]
            or entry.get("tweet_url") != payload[url_key]
        ):
            raise NoteTeamError(f"X {component} 結果がPOST直後に固定したcomponent台帳と一致しません")
    username = payload["expected_x_username"]
    validate_x_status_url(payload["primary_tweet_url"], username, payload["primary_tweet_id"], "X本投稿結果")
    validate_x_status_url(payload["reply_tweet_url"], username, payload["reply_tweet_id"], "Xリプ結果")
    validate_claim_timing(
        state,
        "x_publish",
        payload["claim_id"],
        payload["posted_at"],
        payload["checked_at"],
        "X本投稿結果",
    )
    reply_at = parse_checked_at(payload["reply_posted_at"], "Xリプ投稿日時")
    primary_at = parse_checked_at(payload["posted_at"], "X本投稿日時")
    expires = parse_checked_at(stage_data.get("claim_expires_at"), "X claim期限")
    if reply_at < primary_at or reply_at > expires:
        raise NoteTeamError("Xリプの投稿日時が本投稿後かつclaim期限内ではありません")


@locked_run_mutation
def set_units(root: Path, run_id_value: str, stage: str, units: Iterable[str]) -> dict[str, Any]:
    if stage != "draft":
        raise NoteTeamError("初期版の単位承認は draft 工程だけ対応します")
    state = load_state(root, run_id_value)
    stage_data = active_stage(state, stage)
    if stage_data["status"] != "awaiting_output":
        raise NoteTeamError("単位登録は draft の awaiting_output 時だけ可能です")
    clean_units: list[str] = []
    for unit in units:
        clean = slugify(unit)
        if clean != unit or not clean:
            raise NoteTeamError(f"unit名が不正です: {unit}")
        if clean in WINDOWS_RESERVED_NAMES:
            raise NoteTeamError(f"unit名にOS予約名は使えません: {unit}")
        if clean not in clean_units:
            clean_units.append(clean)
    if not clean_units:
        raise NoteTeamError("1つ以上のunitを指定してください")
    config = load_config(root)
    profile = config["product_profiles"].get(state.get("product_profile"), {})
    chapter_range = profile.get("chapter_range")
    if (
        not isinstance(chapter_range, list)
        or len(chapter_range) != 2
        or any(isinstance(value, bool) or not isinstance(value, int) for value in chapter_range)
    ):
        raise NoteTeamError("product_profile のchapter_range設定が不正です")
    minimum, maximum = chapter_range
    if not minimum <= len(clean_units) <= maximum:
        raise NoteTeamError(
            f"{state.get('product_profile')} の章数は {minimum}〜{maximum}章です（指定: {len(clean_units)}章）"
        )
    stage_data["units"] = {
        unit: {
            "status": "awaiting_output",
            "attempts": 0,
            "artifact": None,
            "artifact_sha256": None,
            "director_qa": None,
        }
        for unit in clean_units
    }
    stage_data["status"] = "unit_cycle"
    save_state(
        root,
        state,
        {"action": "set_units", "actor": "orchestrator", "stage": stage, "units": clean_units},
    )
    return state


@locked_run_mutation
def submit_preflight(
    root: Path,
    run_id_value: str,
    artifact: str,
    actor: str = "note-article-publisher",
    stage: str = "note_draft",
) -> dict[str, Any]:
    """Freeze read-only identity/payload checks before an external mutation."""
    assert_no_secret(actor, "actor")
    state = load_state(root, run_id_value)
    if stage not in EXTERNAL_AUTH_STAGES:
        raise NoteTeamError(f"事前確認の対象外工程です: {stage}")
    stage_data = active_stage(state, stage)
    if stage_data["status"] != "authorization_required":
        raise NoteTeamError("事前確認は authorization_required 状態だけできます")
    directory = run_dir(root, run_id_value)
    relative = artifact_relative(directory, artifact)
    attempt = int(stage_data.get("preflight_attempts", 0)) + 1
    snapshot, digest = snapshot_text(directory, relative, f"{stage}/preflight", attempt)
    try:
        validate_external_preflight(root, state, stage, directory / snapshot, digest)
    except NoteTeamError:
        discard_snapshots(directory, [snapshot])
        raise
    stage_data.update(
        {
            "preflight_attempts": attempt,
            "preflight_source": relative,
            "preflight_artifact": snapshot,
            "preflight_sha256": digest,
            "status": "authorization_ready",
        }
    )
    save_state(
        root,
        state,
        {
            "action": "submit_preflight",
            "actor": actor,
            "stage": stage,
            "artifact": snapshot,
            "artifact_sha256": digest,
        },
    )
    return state


@locked_run_mutation
def submit_artifact(
    root: Path,
    run_id_value: str,
    stage: str,
    artifact: str,
    actor: str,
    unit: str | None = None,
    qa_artifact: str | None = None,
) -> dict[str, Any]:
    assert_no_secret(actor, "actor")
    state = load_state(root, run_id_value)
    if stage == "draft":
        verify_style_corpus(root)
    if (
        state.get("product_profile") == "paid-longform"
        and stage != "plan"
    ):
        verify_fact_pack(root, state)
    stage_data = active_stage(state, stage)
    directory = run_dir(root, run_id_value)
    relative = artifact_relative(directory, artifact)

    if unit:
        if stage_data["status"] != "unit_cycle" or unit not in stage_data["units"]:
            raise NoteTeamError(f"未登録のunitです: {unit}")
        target = stage_data["units"][unit]
        if target["status"] not in {"awaiting_output", "revision_requested"}:
            raise NoteTeamError(f"unit={unit} は submit できる状態ではありません")
    else:
        if stage == "draft" and not stage_data.get("units"):
            raise NoteTeamError("draftはset-unitsで章単位を登録し、全章を個別承認する必要があります")
        if stage == "draft" and stage_data.get("units"):
            all_units_approved = all(
                item.get("status") == "approved"
                for item in stage_data["units"].values()
            )
            if (
                stage_data["status"] not in {"awaiting_final_output", "revision_requested"}
                or not all_units_approved
            ):
                raise NoteTeamError("全章承認後に最終原稿をsubmitしてください")
        elif stage in EXTERNAL_AUTH_STAGES:
            if stage_data["status"] not in {
                "external_in_progress",
                "reconciliation_required",
            }:
                raise NoteTeamError(f"claim済みの{stage}結果を記録できる状態ではありません")
        elif stage_data["status"] not in {"awaiting_output", "revision_requested"}:
            raise NoteTeamError(f"stage={stage} は submit できる状態ではありません")
        target = stage_data

    attempt = int(target.get("attempts", 0)) + 1
    if attempt > 5:
        target["status"] = "owner_escalation"
        save_state(
            root,
            state,
            {
                "action": "quality_loop_limit_reached",
                "actor": actor,
                "stage": stage,
                "unit": unit,
                "attempts": target.get("attempts"),
            },
        )
        raise NoteTeamError("同じ工程の品質ループ5回を超えられません。承認画面で停止または追加ループをオーナー判断してください")
    snapshot, artifact_digest = snapshot_text(
        directory, relative, f"{stage}/{unit or 'final'}", attempt
    )
    snapshot_path = directory / snapshot

    qa_record: dict[str, Any] | None = None
    qa_snapshot: str | None = None
    qa_digest: str | None = None
    claimed_authorization: dict[str, Any] | None = None
    proposal_ids: list[str] | None = None
    promotion_ids: list[str] | None = None
    metrics_binding: dict[str, str] | None = None
    manuscript_characters: int | None = None
    try:
        if stage == "plan":
            proposal_ids = validate_plan_proposals(snapshot_path)
        if stage == "promotion":
            promotion_ids = validate_promotion_variants(snapshot_path)
        if stage == "analysis":
            metrics_binding = validate_analysis_binding(root, snapshot_path)
        if stage == "draft" and unit is None:
            manuscript_content, _ = read_safe_text(snapshot_path, "最終原稿")
            manuscript_characters = count_manuscript_characters(manuscript_content)
            minimum, maximum = manuscript_character_range(root, state)
            if not minimum <= manuscript_characters <= maximum:
                raise NoteTeamError(
                    f"最終原稿の可視文字数は {minimum}〜{maximum}字が必要です（現在 {manuscript_characters}字）"
                )
        if stage not in EXTERNAL_AUTH_STAGES:
            if not qa_artifact:
                raise NoteTeamError("Director QA記録の --qa-artifact が必須です")
            qa_relative = artifact_relative(directory, qa_artifact)
            qa_snapshot, qa_digest = snapshot_text(
                directory, qa_relative, f"qa/{stage}/{unit or 'final'}", attempt
            )
            qa_record = validate_director_qa(
                root, stage, unit, artifact_digest, directory / qa_snapshot
            )

        if stage in EXTERNAL_AUTH_STAGES:
            current_bound_inputs = verify_external_inputs(
                root, state, stage, require_fresh=False
            )
            preflight_target = {
                "artifact": stage_data.get("preflight_artifact"),
                "artifact_sha256": stage_data.get("preflight_sha256"),
            }
            verify_snapshot(directory, preflight_target)
            preflight_payload = validate_external_preflight(
                root,
                state,
                stage,
                resolve_inside(directory, preflight_target["artifact"] or ""),
                preflight_target["artifact_sha256"],
                require_fresh=False,
            )
            result_validators = {
                "note_draft": validate_note_draft_record,
                "note_publish": validate_note_publish_record,
                "x_publish": validate_x_publish_record,
            }
            result_validators[stage](root, state, snapshot_path, preflight_payload)
            authorization_id = stage_data.get("authorization_id")
            claimed_authorization = next(
                (
                    item
                    for item in state.get("external_authorizations", [])
                    if item.get("id") == authorization_id
                    and item.get("consumed_at") is not None
                    and item.get("claim_id") == stage_data.get("claim_id")
                ),
                None,
            )
            if not claimed_authorization:
                raise NoteTeamError(f"claim済みの{stage}許可がありません")
            if claimed_authorization.get("bound_inputs") != current_bound_inputs:
                raise NoteTeamError("許可後に外部操作の入力または事前確認が変わりました")
    except NoteTeamError as exc:
        target["attempts"] = attempt
        failure_record: dict[str, Any] = {
            "attempt": attempt,
            "at": iso_now(),
            "artifact": snapshot,
            "artifact_sha256": artifact_digest,
            "qa_artifact": qa_snapshot,
            "qa_sha256": qa_digest,
            "error_type": type(exc).__name__,
        }
        target.setdefault("quality_failures", []).append(failure_record)
        if isinstance(exc, FatalQualityError):
            target["status"] = "fatal_violation"
            state["status"] = "rejected"
        elif attempt >= 5:
            target["status"] = "owner_escalation"
            if stage in EXTERNAL_AUTH_STAGES:
                target["reconciliation"] = {
                    "at": iso_now(),
                    "actor": actor,
                    "claim_id": target.get("claim_id"),
                    "reason": f"{stage}結果の検証失敗",
                    "error_type": type(exc).__name__,
                }
        elif stage in EXTERNAL_AUTH_STAGES:
            target["status"] = "reconciliation_required"
            target["reconciliation"] = {
                "at": iso_now(),
                "actor": actor,
                "claim_id": target.get("claim_id"),
                "reason": f"{stage}結果の検証失敗",
                "error_type": type(exc).__name__,
            }
        save_state(
            root,
            state,
            {
                "action": "quality_gate_failed",
                "actor": actor,
                "stage": stage,
                "unit": unit,
                "attempt": attempt,
                "error_type": type(exc).__name__,
                "failed_artifact": snapshot,
                "failed_artifact_sha256": artifact_digest,
                "failed_qa_artifact": qa_snapshot,
                "failed_qa_sha256": qa_digest,
            },
        )
        if attempt >= 5 and not isinstance(exc, FatalQualityError):
            raise NoteTeamError(f"{exc} 同じ工程の品質ループが5回に達したためオーナー判断で停止しました") from exc
        raise

    target["source_artifact"] = relative
    target["artifact"] = snapshot
    target["artifact_sha256"] = artifact_digest
    target["attempts"] = attempt
    if proposal_ids is not None:
        target["proposal_ids"] = proposal_ids
        state["selected_plan_id"] = None
    if promotion_ids is not None:
        target["promotion_ids"] = promotion_ids
        state["selected_promotion_id"] = None
    if metrics_binding is not None:
        target["metrics_binding"] = metrics_binding
    if manuscript_characters is not None:
        target["manuscript_characters"] = manuscript_characters
    target["director_qa"] = (
        {
            "artifact": qa_snapshot,
            "sha256": qa_digest,
            "score": qa_record["score"],
            "verdict": qa_record["verdict"],
            "checked_at": qa_record["checked_at"],
            "reviewer": qa_record["reviewer"],
        }
        if qa_record
        else None
    )
    target["status"] = "review"
    save_state(
        root,
        state,
        {
            "action": "submit",
            "actor": actor,
            "stage": stage,
            "unit": unit,
            "artifact": snapshot,
            "artifact_sha256": artifact_digest,
            "director_score": qa_record["score"] if qa_record else None,
            "attempt": attempt,
        },
    )
    return state


def _record_decision(
    state: dict[str, Any],
    action: str,
    stage: str,
    actor: str,
    comment: str,
    unit: str | None,
    target: dict[str, Any] | None = None,
) -> None:
    assert_no_secret(actor, "actor")
    assert_no_secret(comment, "コメント")
    state["approvals"].append(
        {
            "at": iso_now(),
            "action": action,
            "stage": stage,
            "unit": unit,
            "actor": actor,
            "comment": comment,
            "artifact_sha256": target.get("artifact_sha256") if target else None,
            "director_score": (target.get("director_qa") or {}).get("score") if target else None,
        }
    )


def _unlock_next_stage(state: dict[str, Any], completed_stage: str) -> None:
    index = STAGES.index(completed_stage)
    state["stages"][completed_stage]["status"] = "approved"
    if index == len(STAGES) - 1:
        state["status"] = "completed"
        return
    next_stage = STAGES[index + 1]
    state["current_stage"] = next_stage
    next_status = "authorization_required" if next_stage in EXTERNAL_AUTH_STAGES else "awaiting_output"
    state["stages"][next_stage]["status"] = next_status


@locked_run_mutation
def select_plan(
    root: Path,
    run_id_value: str,
    plan_id: str,
    actor: str = "owner",
    *,
    owner_session_confirmed: bool = False,
) -> dict[str, Any]:
    if not owner_session_confirmed:
        raise NoteTeamError("企画選択はローカル承認画面から実行してください")
    assert_no_secret(actor, "actor")
    state = load_state(root, run_id_value)
    stage_data = active_stage(state, "plan")
    if stage_data["status"] != "review":
        raise NoteTeamError("planはreview状態ではありません")
    if plan_id not in stage_data.get("proposal_ids", []):
        raise NoteTeamError(f"未登録の企画IDです: {plan_id}")
    directory = run_dir(root, run_id_value)
    verify_snapshot(directory, stage_data)
    verify_director_qa_snapshot(root, directory, "plan", None, stage_data)
    state["selected_plan_id"] = plan_id
    save_state(
        root,
        state,
        {
            "action": "select_plan",
            "actor": actor,
            "stage": "plan",
            "plan_id": plan_id,
            "artifact_sha256": stage_data.get("artifact_sha256"),
        },
    )
    return state


@locked_run_mutation
def select_promotion(
    root: Path,
    run_id_value: str,
    promotion_id: str,
    actor: str = "owner",
    *,
    owner_session_confirmed: bool = False,
) -> dict[str, Any]:
    if not owner_session_confirmed:
        raise NoteTeamError("X投稿案の選択はローカル承認画面から実行してください")
    assert_no_secret(actor, "actor")
    state = load_state(root, run_id_value)
    stage_data = active_stage(state, "promotion")
    if stage_data["status"] != "review":
        raise NoteTeamError("promotionはreview状態ではありません")
    if promotion_id not in stage_data.get("promotion_ids", []):
        raise NoteTeamError(f"未登録のX投稿案IDです: {promotion_id}")
    directory = run_dir(root, run_id_value)
    verify_snapshot(directory, stage_data)
    verify_director_qa_snapshot(root, directory, "promotion", None, stage_data)
    state["selected_promotion_id"] = promotion_id
    save_state(
        root,
        state,
        {
            "action": "select_promotion",
            "actor": actor,
            "stage": "promotion",
            "promotion_id": promotion_id,
            "artifact_sha256": stage_data.get("artifact_sha256"),
        },
    )
    return state


@locked_run_mutation
def extend_quality_loop(
    root: Path,
    run_id_value: str,
    stage: str,
    unit: str | None = None,
    actor: str = "owner",
    *,
    owner_session_confirmed: bool = False,
) -> dict[str, Any]:
    if not owner_session_confirmed:
        raise NoteTeamError("追加品質ループはローカル承認画面から明示許可してください")
    assert_no_secret(actor, "actor")
    state = load_state(root, run_id_value)
    stage_data = active_stage(state, stage)
    target = stage_data.get("units", {}).get(unit) if unit else stage_data
    if not target or target.get("status") != "owner_escalation":
        raise NoteTeamError("オーナー判断待ちの工程またはunitではありません")
    target["attempts"] = 0
    target["cycle_extensions"] = int(target.get("cycle_extensions", 0)) + 1
    if stage in EXTERNAL_AUTH_STAGES and unit is None:
        if not target.get("claim_id") or not target.get("authorization_id"):
            raise NoteTeamError("note下書き照合のclaim記録がないため追加ループを開けません")
        target["status"] = "reconciliation_required"
    else:
        target["status"] = "revision_requested"
    _record_decision(
        state,
        "extend_quality_loop",
        stage,
        actor,
        "5回上限後の追加ループをオーナーが明示許可",
        unit,
        target,
    )
    save_state(
        root,
        state,
        {
            "action": "extend_quality_loop",
            "actor": actor,
            "stage": stage,
            "unit": unit,
            "extension": target["cycle_extensions"],
        },
    )
    return state


@locked_run_mutation
def approve(
    root: Path,
    run_id_value: str,
    stage: str,
    actor: str = "owner",
    comment: str = "",
    unit: str | None = None,
    *,
    owner_session_confirmed: bool = False,
) -> dict[str, Any]:
    if not owner_session_confirmed:
        raise NoteTeamError("承認はローカル承認画面から行ってください")
    state = load_state(root, run_id_value)
    stage_data = active_stage(state, stage)
    if unit:
        target = stage_data.get("units", {}).get(unit)
        if not target or target["status"] != "review":
            raise NoteTeamError(f"unit={unit} はreview状態ではありません")
        directory = run_dir(root, run_id_value)
        verify_snapshot(directory, target)
        verify_director_qa_snapshot(root, directory, stage, unit, target)
        target["status"] = "approved"
        _record_decision(state, "approve", stage, actor, comment, unit, target)
        if all(item["status"] == "approved" for item in stage_data["units"].values()):
            stage_data["status"] = "awaiting_final_output"
    else:
        if stage_data["status"] != "review":
            raise NoteTeamError(f"stage={stage} はreview状態ではありません")
        if stage == "plan" and not state.get("selected_plan_id"):
            raise NoteTeamError("企画3案から1案を承認画面で選択してください")
        if stage == "promotion" and not state.get("selected_promotion_id"):
            raise NoteTeamError("X投稿3案から1案を承認画面で選択してください")
        if (
            stage == "plan"
            and state.get("product_profile") == "paid-longform"
        ):
            verify_fact_pack(root, state)
        directory = run_dir(root, run_id_value)
        verify_snapshot(directory, stage_data)
        if stage not in EXTERNAL_AUTH_STAGES:
            verify_director_qa_snapshot(root, directory, stage, None, stage_data)
        if stage == "analysis":
            validate_analysis_binding(
                root,
                resolve_inside(
                    run_dir(root, run_id_value), stage_data.get("artifact") or ""
                ),
            )
        _record_decision(state, "approve", stage, actor, comment, None, stage_data)
        _unlock_next_stage(state, stage)
    save_state(
        root,
        state,
        {"action": "approve", "actor": actor, "stage": stage, "unit": unit, "comment": comment},
    )
    return state


@locked_run_mutation
def request_revision(
    root: Path,
    run_id_value: str,
    stage: str,
    comment: str,
    actor: str = "owner",
    unit: str | None = None,
    *,
    owner_session_confirmed: bool = False,
) -> dict[str, Any]:
    if not owner_session_confirmed:
        raise NoteTeamError("修正指示はローカル承認画面から行ってください")
    if not comment.strip():
        raise NoteTeamError("修正指示にはコメントが必要です")
    state = load_state(root, run_id_value)
    stage_data = active_stage(state, stage)
    target = stage_data.get("units", {}).get(unit) if unit else stage_data
    if not target or target["status"] != "review":
        raise NoteTeamError("review状態の工程またはunitだけ修正依頼できます")
    if stage in EXTERNAL_AUTH_STAGES and unit is None:
        raise NoteTeamError(
            "外部操作後の内容修正は重複作成防止のためこの画面では行えません。承認または停止を選んでください"
        )
    verify_snapshot(run_dir(root, run_id_value), target)
    target["status"] = "revision_requested"
    if stage == "plan" and unit is None:
        state["selected_plan_id"] = None
    if stage == "promotion" and unit is None:
        state["selected_promotion_id"] = None
    _record_decision(state, "revise", stage, actor, comment, unit, target)
    save_state(
        root,
        state,
        {"action": "revise", "actor": actor, "stage": stage, "unit": unit, "comment": comment},
    )
    return state


@locked_run_mutation
def reject(
    root: Path,
    run_id_value: str,
    stage: str,
    comment: str,
    actor: str = "owner",
    unit: str | None = None,
    *,
    owner_session_confirmed: bool = False,
) -> dict[str, Any]:
    if not owner_session_confirmed:
        raise NoteTeamError("却下・停止はローカル承認画面から行ってください")
    if not comment.strip():
        raise NoteTeamError("却下理由が必要です")
    state = load_state(root, run_id_value)
    active_stage(state, stage)
    _record_decision(state, "reject", stage, actor, comment, unit)
    state["status"] = "rejected"
    save_state(
        root,
        state,
        {"action": "reject", "actor": actor, "stage": stage, "unit": unit, "comment": comment},
    )
    return state


def reset_external_gate(stage_data: dict[str, Any]) -> None:
    stage_data["status"] = "authorization_required"
    stage_data["authorization_id"] = None
    stage_data["authorization_consumed"] = True
    stage_data["claim_id"] = None
    stage_data["claim_expires_at"] = None
    stage_data.pop("reconciliation", None)
    stage_data.pop("components", None)
    for key in ("preflight_artifact", "preflight_sha256", "preflight_source"):
        stage_data[key] = None


def external_bound_inputs(state: dict[str, Any], stage: str) -> dict[str, Any]:
    base: dict[str, Any] = {
        "run_id": state["run_id"],
        "account_id": state["account_id"],
        "stage": stage,
        "preflight_sha256": state["stages"][stage].get("preflight_sha256"),
    }
    if stage == "note_draft":
        base["manuscript_sha256"] = state["stages"]["draft"].get("artifact_sha256")
    elif stage == "note_publish":
        base.update(
            {
                "manuscript_sha256": state["stages"]["draft"].get("artifact_sha256"),
                "note_draft_sha256": state["stages"]["note_draft"].get("artifact_sha256"),
            }
        )
    elif stage == "x_publish":
        base.update(
            {
                "selected_promotion_id": state.get("selected_promotion_id"),
                "promotion_sha256": state["stages"]["promotion"].get("artifact_sha256"),
                "note_publish_sha256": state["stages"]["note_publish"].get("artifact_sha256"),
            }
        )
    else:
        raise NoteTeamError(f"外部操作の対象外工程です: {stage}")
    if any(value in {None, ""} for value in base.values()):
        raise NoteTeamError(f"{stage}の許可に必要な承認済み入力が足りません")
    return base


def verify_external_inputs(
    root: Path,
    state: dict[str, Any],
    stage: str,
    *,
    require_fresh: bool = True,
) -> dict[str, Any]:
    directory = run_dir(root, state["run_id"])
    source_stages = {
        "note_draft": ("draft",),
        "note_publish": ("draft", "note_draft"),
        "x_publish": ("promotion", "note_publish"),
    }[stage]
    for source_stage in source_stages:
        verify_snapshot(directory, state["stages"][source_stage])
    if stage == "x_publish":
        selected_promotion_variant(root, state)
    stage_data = state["stages"][stage]
    preflight_target = {
        "artifact": stage_data.get("preflight_artifact"),
        "artifact_sha256": stage_data.get("preflight_sha256"),
    }
    verify_snapshot(directory, preflight_target)
    validate_external_preflight(
        root,
        state,
        stage,
        resolve_inside(directory, preflight_target["artifact"] or ""),
        preflight_target["artifact_sha256"],
        require_fresh=require_fresh,
    )
    return external_bound_inputs(state, stage)


@locked_run_mutation
def authorize_external(
    root: Path,
    run_id_value: str,
    stage: str,
    actor: str = "owner",
    comment: str = "表示された対象の外部操作を1回限り許可",
    *,
    owner_session_confirmed: bool = False,
) -> dict[str, Any]:
    if stage not in EXTERNAL_AUTH_STAGES:
        raise NoteTeamError(f"外部操作の許可対象ではありません: {stage}")
    state = load_state(root, run_id_value)
    stage_data = active_stage(state, stage)
    if stage_data["status"] != "authorization_ready":
        raise NoteTeamError("対象アカウントと入力の事前確認後だけ許可できます")
    if not owner_session_confirmed:
        raise NoteTeamError("外部操作許可はローカル承認画面から実行してください")
    assert_no_secret(actor, "actor")
    assert_no_secret(comment, "コメント")
    try:
        bound_inputs = verify_external_inputs(root, state, stage)
    except NoteTeamError as exc:
        reset_external_gate(stage_data)
        save_state(
            root,
            state,
            {
                "action": "authorization_preflight_invalid",
                "actor": actor,
                "stage": stage,
                "error_type": type(exc).__name__,
            },
        )
        raise
    operation_key = sha256_bytes(
        json.dumps(bound_inputs, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )
    scopes = {
        "note_draft": "create-new-draft",
        "note_publish": "publish-existing-draft",
        "x_publish": "create-selected-post-and-first-reply",
    }
    authorization = {
        "id": secrets.token_urlsafe(18),
        "at": iso_now(),
        "expires_at": (now_jst() + timedelta(minutes=AUTH_TTL_MINUTES)).isoformat(timespec="seconds"),
        "stage": stage,
        "actor": actor,
        "scope": scopes[stage],
        "operation_key": operation_key,
        "comment": comment,
        "bound_inputs": bound_inputs,
        "consumed_at": None,
    }
    state["external_authorizations"].append(authorization)
    stage_data["authorization_id"] = authorization["id"]
    stage_data["authorization_consumed"] = False
    stage_data["status"] = "authorized"
    save_state(root, state, {"action": "authorize_external", **authorization})
    return state


@locked_run_mutation
def claim_external(
    root: Path,
    run_id_value: str,
    stage: str,
    actor: str = "note-article-publisher",
) -> dict[str, Any]:
    """Consume one owner authorization immediately before browser mutation."""
    assert_no_secret(actor, "actor")
    state = load_state(root, run_id_value)
    stage_data = active_stage(state, stage)
    if stage not in EXTERNAL_AUTH_STAGES or stage_data["status"] != "authorized":
        raise NoteTeamError("未使用の外部操作許可がありません")
    authorization = next(
        (
            item
            for item in state.get("external_authorizations", [])
            if item.get("id") == stage_data.get("authorization_id")
            and item.get("consumed_at") is None
        ),
        None,
    )
    if not authorization:
        raise NoteTeamError("許可は使用済みまたは無効です")
    if now_jst() > parse_checked_at(authorization.get("expires_at"), "許可期限"):
        reset_external_gate(stage_data)
        save_state(
            root,
            state,
            {"action": "authorization_expired", "actor": actor, "stage": stage},
        )
        raise NoteTeamError(f"{stage}許可の10分間の期限が切れました。事前確認からやり直してください")
    try:
        if authorization.get("bound_inputs") != verify_external_inputs(root, state, stage):
            raise NoteTeamError("オーナー許可後に承認入力または事前確認が変わりました")
    except NoteTeamError as exc:
        reset_external_gate(stage_data)
        save_state(
            root,
            state,
            {
                "action": "claim_preflight_invalid",
                "actor": actor,
                "stage": stage,
                "error_type": type(exc).__name__,
            },
        )
        raise
    claim_id = secrets.token_urlsafe(18)
    claimed_datetime = now_jst()
    claimed_at = claimed_datetime.isoformat(timespec="seconds")
    claim_expires_datetime = min(
        parse_checked_at(authorization["expires_at"], "許可期限"),
        claimed_datetime + timedelta(minutes=CLAIM_TTL_MINUTES),
    )
    claim_expires_at = claim_expires_datetime.isoformat(timespec="seconds")
    authorization["consumed_at"] = claimed_at
    authorization["claimed_at"] = claimed_at
    authorization["claimed_by"] = actor
    authorization["claim_id"] = claim_id
    authorization["claim_expires_at"] = claim_expires_at
    stage_data["authorization_consumed"] = True
    stage_data["claim_id"] = claim_id
    stage_data["claim_expires_at"] = claim_expires_at
    stage_data["operation_key"] = authorization.get("operation_key")
    if stage == "x_publish":
        stage_data["components"] = {
            "main": {"status": "pending", "tweet_id": None, "tweet_url": None},
            "reply": {"status": "pending", "tweet_id": None, "tweet_url": None},
        }
    stage_data["status"] = "external_in_progress"
    save_state(
        root,
        state,
        {
            "action": "claim_external",
            "actor": actor,
            "stage": stage,
            "authorization_id": authorization["id"],
            "claim_id": claim_id,
            "claim_expires_at": claim_expires_at,
        },
    )
    return state


def require_active_external_claim(
    state: dict[str, Any], stage: str, label: str
) -> dict[str, Any]:
    """Refuse a new external mutation once the consumed claim window expired."""
    stage_data = active_stage(state, stage)
    if stage not in EXTERNAL_AUTH_STAGES or stage_data.get("status") != "external_in_progress":
        raise NoteTeamError(f"{label}の実行中claimがありません")
    claim_id = stage_data.get("claim_id")
    expires_at = stage_data.get("claim_expires_at")
    if not claim_id or not expires_at:
        raise NoteTeamError(f"{label}のclaim IDまたは期限がありません")
    if now_jst() > parse_checked_at(expires_at, f"{label} claim期限"):
        raise NoteTeamError(f"{label}のclaim期限が切れました。新規の外部操作は実行できません")
    return stage_data


@locked_run_mutation
def record_external_component(
    root: Path,
    run_id_value: str,
    stage: str,
    component: str,
    object_id: str,
    object_url: str,
    actor: str = "x-publish-worker",
) -> dict[str, Any]:
    """Persist a confirmed component before a multi-call external saga continues."""
    assert_no_secret(actor, "actor")
    state = load_state(root, run_id_value)
    stage_data = active_stage(state, stage)
    if stage != "x_publish" or stage_data.get("status") != "external_in_progress":
        raise NoteTeamError("X投稿の実行中だけcomponent結果を記録できます")
    require_active_external_claim(state, stage, f"X {component} component")
    if component not in {"main", "reply"}:
        raise NoteTeamError("X投稿componentは main または reply です")
    components = stage_data.get("components")
    if not isinstance(components, dict) or component not in components:
        raise NoteTeamError("X投稿component台帳が初期化されていません")
    target = components[component]
    if target.get("status") == "posted":
        if target.get("tweet_id") == object_id and target.get("tweet_url") == object_url:
            return state
        raise NoteTeamError("同じX componentに別のtweetを記録できません")
    if component == "reply" and components["main"].get("status") != "posted":
        raise NoteTeamError("X本投稿のIDを固定する前にリプ結果を記録できません")
    preflight = validate_x_publish_preflight(
        root,
        state,
        resolve_inside(
            run_dir(root, run_id_value), stage_data.get("preflight_artifact") or ""
        ),
        stage_data.get("preflight_sha256"),
        require_fresh=False,
    )
    validate_x_status_url(
        object_url,
        preflight["expected_x_username"],
        object_id,
        f"X {component} component",
    )
    target.update(
        {
            "status": "posted",
            "tweet_id": object_id,
            "tweet_url": object_url,
            "recorded_at": iso_now(),
        }
    )
    save_state(
        root,
        state,
        {
            "action": "record_external_component",
            "actor": actor,
            "stage": stage,
            "component": component,
            "object_id": object_id,
            "object_url": object_url,
            "claim_id": stage_data.get("claim_id"),
        },
    )
    return state


@locked_run_mutation
def record_external_failure(
    root: Path,
    run_id_value: str,
    stage: str,
    comment: str,
    actor: str = "note-article-publisher",
) -> dict[str, Any]:
    if not comment.strip():
        raise NoteTeamError("外部操作失敗の理由が必要です")
    assert_no_secret(comment, "失敗理由")
    assert_no_secret(actor, "actor")
    state = load_state(root, run_id_value)
    stage_data = active_stage(state, stage)
    if stage not in EXTERNAL_AUTH_STAGES or stage_data["status"] != "external_in_progress":
        raise NoteTeamError("実行中の外部操作はありません")
    stage_data["status"] = "reconciliation_required"
    stage_data["reconciliation"] = {
        "at": iso_now(),
        "actor": actor,
        "claim_id": stage_data.get("claim_id"),
        "reason": comment,
    }
    save_state(
        root,
        state,
        {
            "action": "external_failure",
            "actor": actor,
            "stage": stage,
            "comment": comment,
        },
    )
    return state


@locked_run_mutation
def confirm_no_external_result(
    root: Path,
    run_id_value: str,
    stage: str,
    comment: str,
    actor: str = "owner",
    *,
    owner_session_confirmed: bool = False,
) -> dict[str, Any]:
    """Reset a consumed claim only after the owner confirms no mutation exists."""
    if not owner_session_confirmed:
        raise NoteTeamError("外部操作結果の不存在確認はローカル承認画面から行ってください")
    if not comment.strip():
        raise NoteTeamError("対象媒体の一覧やAPIで確認した内容を入力してください")
    assert_no_secret(comment, "確認内容")
    assert_no_secret(actor, "actor")
    state = load_state(root, run_id_value)
    stage_data = active_stage(state, stage)
    if stage not in EXTERNAL_AUTH_STAGES or stage_data.get("status") != "reconciliation_required":
        raise NoteTeamError("外部結果の照合待ちではありません")
    claim_id = stage_data.get("claim_id")
    authorization_id = stage_data.get("authorization_id")
    if not claim_id or not authorization_id:
        raise NoteTeamError("照合対象のclaimまたは許可記録がありません")
    if stage == "x_publish":
        components = stage_data.get("components")
        main = components.get("main", {}) if isinstance(components, dict) else {}
        if main.get("status") == "posted":
            reply = components.get("reply", {})
            resolution = (
                "リプIDも台帳に固定済みのため、同じclaimの読み戻し結果をsubmitしてください"
                if reply.get("status") == "posted"
                else "リプIDが台帳に固定されていないため、本投稿を保護してrunを停止してください"
            )
            raise NoteTeamError(
                "X本投稿は既に確定済みのため、component台帳を消して再許可できません。"
                + resolution
            )
    _record_decision(
        state,
        "confirm_no_external_result",
        stage,
        actor,
        comment,
        None,
        stage_data,
    )
    reset_external_gate(stage_data)
    save_state(
        root,
        state,
        {
            "action": "confirm_no_external_result",
            "actor": actor,
            "stage": stage,
            "claim_id": claim_id,
            "authorization_id": authorization_id,
            "comment": comment,
        },
    )
    return state


def confirm_no_external_draft(
    root: Path,
    run_id_value: str,
    stage: str,
    comment: str,
    actor: str = "owner",
    *,
    owner_session_confirmed: bool = False,
) -> dict[str, Any]:
    """Backward-compatible alias for existing callers."""
    return confirm_no_external_result(
        root,
        run_id_value,
        stage,
        comment,
        actor,
        owner_session_confirmed=owner_session_confirmed,
    )


def list_states(root: Path) -> list[dict[str, Any]]:
    runs = ensure_private_directory(root.resolve(), RUNS_REL)
    result = []
    for path in sorted(runs.glob("*/state.json"), reverse=True):
        if path.is_symlink():
            raise NoteTeamError(f"state.jsonにシンボリックリンクは使えません: {path}")
        state = load_json(path)
        validate_state(state)
        if state.get("run_id") != path.parent.name:
            raise NoteTeamError(f"{path} のrun_idがディレクトリ名と一致しません")
        result.append(state)
    return result


def parse_nonnegative_int(value: Any, field: str, row_number: int) -> int | None:
    if not isinstance(value, str):
        raise NoteTeamError(f"{field} が欠落しています（CSV {row_number}行目）")
    stripped = value.strip()
    if value != stripped:
        raise NoteTeamError(f"{field} の前後に空白があります（CSV {row_number}行目）")
    value = stripped
    if value.upper() == "N/A":
        return None
    if value == "":
        raise NoteTeamError(f"{field} が空です（CSV {row_number}行目）")
    if not re.fullmatch(r"[0-9]+", value):
        raise NoteTeamError(f"{field} は0以上の整数で指定してください（CSV {row_number}行目）")
    maximum = str(MAX_METRIC_INTEGER)
    canonical = value.lstrip("0") or "0"
    if len(canonical) > len(maximum) or (
        len(canonical) == len(maximum) and canonical > maximum
    ):
        raise NoteTeamError(
            f"{field} は {MAX_METRIC_INTEGER} 以下で指定してください（CSV {row_number}行目）"
        )
    result = int(canonical)
    return result


def load_metric_snapshot(
    path: Path, required: set[str]
) -> tuple[list[dict[str, str]], str]:
    try:
        payload = path.read_bytes()
    except FileNotFoundError as exc:
        raise NoteTeamError(f"実績CSVがありません: {path}") from exc
    except OSError as exc:
        raise NoteTeamError(f"実績CSVを読み込めません: {path}") from exc
    if len(payload) > MAX_METRIC_BYTES:
        raise NoteTeamError(f"実績CSVは{MAX_METRIC_BYTES}バイト以下にしてください: {path}")
    try:
        content = payload.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise NoteTeamError(f"実績CSVはUTF-8で保存してください: {path}") from exc
    reader = csv.DictReader(io.StringIO(content, newline=""))
    fieldnames = reader.fieldnames or []
    if not fieldnames or any(not isinstance(field, str) or not field for field in fieldnames):
        raise NoteTeamError(f"{path} のヘッダーが不正です")
    if len(fieldnames) != len(set(fieldnames)):
        raise NoteTeamError(f"{path} に重複ヘッダーがあります")
    if any(field != field.strip() for field in fieldnames):
        raise NoteTeamError(f"{path} のヘッダー前後に空白があります")
    fields = set(fieldnames)
    missing = sorted(required - fields)
    if missing:
        raise NoteTeamError(f"{path} に列がありません: {', '.join(missing)}")
    try:
        rows = [dict(row) for row in reader]
    except csv.Error as exc:
        raise NoteTeamError(f"{path} のCSV構文が不正です") from exc
    if len(rows) > MAX_METRIC_ROWS:
        raise NoteTeamError(f"実績CSVは{MAX_METRIC_ROWS}行以下にしてください: {path}")
    for row_number, row in enumerate(rows, start=2):
        if None in row:
            raise NoteTeamError(f"CSV {row_number}行目にヘッダーより多い列があります: {path}")
        if any(value is None for value in row.values()):
            raise NoteTeamError(f"CSV {row_number}行目に欠落列があります: {path}")
    return rows, sha256_bytes(payload)


def load_metric_rows(path: Path, required: set[str]) -> list[dict[str, str]]:
    return load_metric_snapshot(path, required)[0]


def validate_metric_rows(
    rows: list[dict[str, str]], key_fields: tuple[str, ...], label: str
) -> None:
    seen: set[tuple[str, ...]] = set()
    for row_number, row in enumerate(rows, start=2):
        raw_date = row.get("date") or ""
        date_value = raw_date.strip()
        if raw_date != date_value:
            raise NoteTeamError(f"{label}のdateの前後に空白があります（CSV {row_number}行目）")
        try:
            parsed = datetime.strptime(date_value, "%Y-%m-%d")
        except ValueError as exc:
            raise NoteTeamError(f"{label}のdateが YYYY-MM-DD ではありません（CSV {row_number}行目）") from exc
        if parsed.strftime("%Y-%m-%d") != date_value:
            raise NoteTeamError(f"{label}のdateが YYYY-MM-DD ではありません（CSV {row_number}行目）")
        raw_key = tuple(row.get(field) or "" for field in key_fields)
        key = tuple(value.strip() for value in raw_key)
        if raw_key != key:
            raise NoteTeamError(f"{label}の一意キー前後に空白があります（CSV {row_number}行目）")
        if any(not value for value in key):
            raise NoteTeamError(f"{label}の一意キーに空値があります（CSV {row_number}行目）")
        if key in seen:
            raise NoteTeamError(f"{label}に重複行があります: {' / '.join(key)}")
        seen.add(key)


def validate_constant_fields(
    rows: list[dict[str, str]], key_field: str, fields: tuple[str, ...], label: str
) -> None:
    """Require stable article identity across daily-delta observations."""
    identities: dict[str, tuple[str, ...]] = {}
    for row_number, row in enumerate(rows, start=2):
        key_value = row.get(key_field) or ""
        raw_values = tuple(row.get(field) or "" for field in fields)
        values = tuple(value.strip() for value in raw_values)
        if raw_values != values:
            raise NoteTeamError(
                f"{label}の{', '.join(fields)}前後に空白があります（CSV {row_number}行目）"
            )
        if any(not value for value in values):
            raise NoteTeamError(
                f"{label}の{', '.join(fields)}に空値があります（CSV {row_number}行目）"
            )
        previous = identities.setdefault(key_value, values)
        if previous != values:
            raise NoteTeamError(
                f"{label}の{key_field}={key_value}で{', '.join(fields)}が一致しません"
            )


def validate_required_text_fields(
    rows: list[dict[str, str]], fields: tuple[str, ...], label: str
) -> None:
    for row_number, row in enumerate(rows, start=2):
        for field in fields:
            raw_value = row.get(field) or ""
            value = raw_value.strip()
            if raw_value != value:
                raise NoteTeamError(
                    f"{label}の{field}前後に空白があります（CSV {row_number}行目）"
                )
            if not value:
                raise NoteTeamError(
                    f"{label}の{field}に空値があります（CSV {row_number}行目）"
                )


def percent(numerator: int | None, denominator: int | None) -> str:
    if numerator is None or denominator in {None, 0}:
        return "N/A"
    return f"{numerator / denominator * 100:.2f}%"


def total_or_na(rows: list[dict[str, Any]], field: str) -> int | None:
    if not rows:
        return None
    values = [row[field] for row in rows]
    if any(value is None for value in values):
        return None
    return sum(values)


def analyze_metrics(root: Path, month: str | None = None) -> tuple[dict[str, Any], str]:
    if month:
        try:
            parsed_month = datetime.strptime(month, "%Y-%m")
        except ValueError as exc:
            raise NoteTeamError("month は実在する YYYY-MM 形式です") from exc
        if parsed_month.strftime("%Y-%m") != month:
            raise NoteTeamError("month は実在する YYYY-MM 形式です")
    config = load_config(root)
    if config["metrics"].get("aggregation_mode") != "daily_delta":
        raise NoteTeamError("metrics.aggregation_mode は daily_delta に固定してください")
    note_path = resolve_inside(root, config["metrics"]["note_csv"])
    x_path = resolve_inside(root, config["metrics"]["x_csv"])
    note_required = {
        "date",
        "run_id",
        "account_id",
        "title",
        "pv",
        "likes",
        "sales_count",
        "revenue_yen",
        "price_yen",
    }
    x_required = {"date", "run_id", "variant", "impressions", "engagements", "link_clicks"}
    raw_note, note_csv_digest = load_metric_snapshot(note_path, note_required)
    raw_x, x_csv_digest = load_metric_snapshot(x_path, x_required)
    raw_note_count = len(raw_note)
    raw_x_count = len(raw_x)
    validate_metric_rows(raw_note, ("date", "run_id"), "note_metrics")
    validate_metric_rows(raw_x, ("date", "run_id", "variant"), "x_metrics")
    validate_constant_fields(raw_note, "run_id", ("account_id",), "note_metrics")
    validate_required_text_fields(raw_note, ("title",), "note_metrics")
    indexed_note = list(enumerate(raw_note, start=2))
    indexed_x = list(enumerate(raw_x, start=2))
    if month:
        indexed_note = [item for item in indexed_note if item[1]["date"].startswith(month)]
        indexed_x = [item for item in indexed_x if item[1]["date"].startswith(month)]

    note_rows: list[dict[str, Any]] = []
    for index, row in indexed_note:
        parsed = dict(row)
        for field in ("pv", "likes", "sales_count", "revenue_yen", "price_yen"):
            parsed[field] = parse_nonnegative_int(row[field], field, index)
        if (
            parsed["sales_count"] is not None
            and parsed["pv"] is not None
            and parsed["sales_count"] > parsed["pv"]
        ):
            raise NoteTeamError(f"sales_count が pv を超えています（CSV {index}行目）")
        if parsed["price_yen"] == 0 and (
            (parsed["sales_count"] or 0) > 0 or (parsed["revenue_yen"] or 0) > 0
        ):
            raise NoteTeamError(
                f"無料記事（price_yen=0）に売上部数または売上金額があります（CSV {index}行目）"
            )
        if (
            parsed["sales_count"] is not None
            and parsed["revenue_yen"] is not None
            and ((parsed["sales_count"] == 0) != (parsed["revenue_yen"] == 0))
        ):
            raise NoteTeamError(
                f"売上部数と売上金額のゼロ・非ゼロが一致しません（CSV {index}行目）"
            )
        note_rows.append(parsed)

    x_rows: list[dict[str, Any]] = []
    for index, row in indexed_x:
        parsed = dict(row)
        for field in ("impressions", "engagements", "link_clicks"):
            parsed[field] = parse_nonnegative_int(row[field], field, index)
        if (
            parsed["link_clicks"] is not None
            and parsed["impressions"] is not None
            and parsed["link_clicks"] > parsed["impressions"]
        ):
            raise NoteTeamError(f"link_clicks が impressions を超えています（CSV {index}行目）")
        x_rows.append(parsed)

    paid_rows = [row for row in note_rows if row["price_yen"] is not None and row["price_yen"] > 0]
    free_rows = [row for row in note_rows if row["price_yen"] == 0]
    unknown_price_rows = [row for row in note_rows if row["price_yen"] is None]
    note_totals = {
        "articles": len({row["run_id"] for row in note_rows}),
        "pv": total_or_na(note_rows, "pv"),
        "likes": total_or_na(note_rows, "likes"),
        "sales_count": total_or_na(note_rows, "sales_count"),
        "revenue_yen": total_or_na(note_rows, "revenue_yen"),
        "paid_articles": len({row["run_id"] for row in paid_rows}),
        "paid_pv": total_or_na(paid_rows, "pv"),
        "paid_sales_count": total_or_na(paid_rows, "sales_count"),
        "free_articles": len({row["run_id"] for row in free_rows}),
        "unknown_price_rows": len(unknown_price_rows),
    }
    x_totals = {
        "posts": len({(row["run_id"], row["variant"]) for row in x_rows}),
        "impressions": total_or_na(x_rows, "impressions"),
        "engagements": total_or_na(x_rows, "engagements"),
        "link_clicks": total_or_na(x_rows, "link_clicks"),
    }

    rows_by_run: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in note_rows:
        rows_by_run[row["run_id"]].append(row)
    article_rows: list[dict[str, Any]] = []
    for run_id_value, rows in rows_by_run.items():
        price_unknown = any(row["price_yen"] is None for row in rows)
        paid_period_rows = [row for row in rows if row["price_yen"] is not None and row["price_yen"] > 0]
        if price_unknown:
            classification = "unknown"
            comparison_rows = rows
        elif paid_period_rows:
            paid_sales = total_or_na(paid_period_rows, "sales_count")
            classification = (
                "unknown"
                if paid_sales is None
                else ("sold" if paid_sales > 0 else "unsold")
            )
            comparison_rows = paid_period_rows
        else:
            classification = "free"
            comparison_rows = rows
        article_rows.append(
            {
                "run_id": run_id_value,
                "pv": total_or_na(comparison_rows, "pv"),
                "likes": total_or_na(comparison_rows, "likes"),
                "classification": classification,
            }
        )

    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in article_rows:
        groups[row["classification"]].append(row)

    def group_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
        if not rows:
            return {"articles": 0, "avg_pv": None, "avg_likes": None}
        pv_values = [row["pv"] for row in rows]
        like_values = [row["likes"] for row in rows]
        return {
            "articles": len(rows),
            "avg_pv": None if any(value is None for value in pv_values) else sum(pv_values) / len(rows),
            "avg_likes": None
            if any(value is None for value in like_values)
            else sum(like_values) / len(rows),
        }

    result = {
        "month": month or "all",
        "provenance": {
            "generated_at": iso_now(),
            "tool_schema_version": 1,
            "aggregation_mode": "daily_delta",
            "note_csv": {
                "path": note_path.resolve().relative_to(root.resolve()).as_posix(),
                "sha256": note_csv_digest,
                "raw_rows": raw_note_count,
                "filtered_rows": len(note_rows),
            },
            "x_csv": {
                "path": x_path.resolve().relative_to(root.resolve()).as_posix(),
                "sha256": x_csv_digest,
                "raw_rows": raw_x_count,
                "filtered_rows": len(x_rows),
            },
        },
        "note": {
            **note_totals,
            "like_rate": percent(note_totals["likes"], note_totals["pv"]),
            "paid_conversion_rate": (
                "N/A"
                if note_totals["unknown_price_rows"]
                else percent(note_totals["paid_sales_count"], note_totals["paid_pv"])
            ),
        },
        "x": {
            **x_totals,
            "engagement_rate": percent(x_totals["engagements"], x_totals["impressions"]),
            "click_rate": percent(x_totals["link_clicks"], x_totals["impressions"]),
        },
        "comparison": {
            "sold": group_summary(groups["sold"]),
            "unsold": group_summary(groups["unsold"]),
            "free": group_summary(groups["free"]),
            "unknown": group_summary(groups["unknown"]),
        },
    }
    result["provenance"]["metrics_snapshot_sha256"] = metrics_snapshot_sha256(result)
    markdown = render_metrics_markdown(result)
    return result, markdown


def metrics_snapshot_sha256(result: dict[str, Any]) -> str:
    """Hash only deterministic metric values; exclude report rendering time."""
    canonical = json.loads(json.dumps(result, ensure_ascii=False))
    provenance = canonical.get("provenance", {})
    provenance.pop("generated_at", None)
    provenance.pop("metrics_snapshot_sha256", None)
    payload = json.dumps(
        canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return sha256_bytes(payload)


def format_optional(value: float | None) -> str:
    return "N/A" if value is None else f"{value:.2f}"


def display_metric(value: Any) -> str:
    return "N/A" if value is None else str(value)


def render_metrics_markdown(result: dict[str, Any]) -> str:
    note = result["note"]
    x = result["x"]
    sold = result["comparison"]["sold"]
    unsold = result["comparison"]["unsold"]
    free = result["comparison"]["free"]
    unknown = result["comparison"]["unknown"]
    provenance = result["provenance"]
    revenue = "N/A" if note["revenue_yen"] is None else f"{note['revenue_yen']}円"
    return f"""# note・X 実績集計 {result['month']}

> 入力CSVの実値だけを集計。欠損値の推測は行っていません。

- 生成日時: {provenance['generated_at']}
- 集計スナップショットSHA-256: `{provenance['metrics_snapshot_sha256']}`
- note CSV: `{provenance['note_csv']['path']}` / SHA-256 `{provenance['note_csv']['sha256']}` / 対象 {provenance['note_csv']['filtered_rows']} 行（全 {provenance['note_csv']['raw_rows']} 行）
- X CSV: `{provenance['x_csv']['path']}` / SHA-256 `{provenance['x_csv']['sha256']}` / 対象 {provenance['x_csv']['filtered_rows']} 行（全 {provenance['x_csv']['raw_rows']} 行）

## note

- 記事数: {note['articles']}
- PV: {display_metric(note['pv'])}
- スキ数: {display_metric(note['likes'])}
- 売上部数: {display_metric(note['sales_count'])}
- 売上金額: {revenue}
- スキ率: {note['like_rate']}
- 有料記事PV: {display_metric(note['paid_pv'])}
- 有料記事売上部数: {display_metric(note['paid_sales_count'])}
- 有料転換率（有料期間の売上部数 / 有料期間のPV）: {note['paid_conversion_rate']}
- 価格不明行: {note['unknown_price_rows']}

## X

- 実投稿数（run ID + 告知案IDの重複除外）: {x['posts']}
- インプレッション: {display_metric(x['impressions'])}
- エンゲージメント: {display_metric(x['engagements'])}
- リンククリック: {display_metric(x['link_clicks'])}
- エンゲージメント率: {x['engagement_rate']}
- クリック率: {x['click_rate']}

## 売れた記事と売れなかった記事

| 区分 | 記事数 | 平均PV | 平均スキ数 |
|---|---:|---:|---:|
| 有料・売上あり | {sold['articles']} | {format_optional(sold['avg_pv'])} | {format_optional(sold['avg_likes'])} |
| 有料・売上なし | {unsold['articles']} | {format_optional(unsold['avg_pv'])} | {format_optional(unsold['avg_likes'])} |
| 無料記事 | {free['articles']} | {format_optional(free['avg_pv'])} | {format_optional(free['avg_likes'])} |
| 価格または売上不明 | {unknown['articles']} | {format_optional(unknown['avg_pv'])} | {format_optional(unknown['avg_likes'])} |

## Analystへの入力条件

この集計値と記事本文・企画メモを照合して、「続けること」「やめる・変えること」「次テーマ」を各1つ提案する。CSVにない数字は使わない。
"""


def validate_installation(root: Path) -> list[str]:
    config = load_config(root)
    issues: list[str] = []
    for key in ("note_publish_enabled", "x_publish_enabled"):
        if config["safety"].get(key) is not True:
            issues.append(f"safety.{key} は true が必要です")
    for key in ("line_send_enabled", "scheduled_runs_enabled"):
        if config["safety"].get(key) is not False:
            issues.append(f"safety.{key} は false が必要です")
    for key in (
        "note_draft_requires_explicit_approval",
        "note_publish_requires_explicit_approval",
        "x_publish_requires_explicit_approval",
        "require_director_qa",
    ):
        if config["safety"].get(key) is not True:
            issues.append(f"safety.{key} は true が必要です")
    if config["safety"].get("store_credentials") is not False:
        issues.append("safety.store_credentials は false が必要です")
    if config["safety"].get("unknown_metrics_policy") != "N/A":
        issues.append("safety.unknown_metrics_policy は N/A が必要です")
    if config["article_defaults"].get("quality_gate") != 85:
        issues.append("article_defaults.quality_gate は 85 が必要です")
    if config["metrics"].get("aggregation_mode") != "daily_delta":
        issues.append("metrics.aggregation_mode は daily_delta が必要です")
    x_account = config.get("x_account")
    if not isinstance(x_account, dict):
        issues.append("x_publishを有効にする場合はx_accountの固定が必要です")
    else:
        if not isinstance(x_account.get("user_id"), str) or not re.fullmatch(
            r"\d{3,30}", x_account["user_id"]
        ):
            issues.append("x_account.user_id の形式が不正です")
        if not isinstance(x_account.get("username"), str) or not re.fullmatch(
            r"[A-Za-z0-9_]{1,15}", x_account["username"]
        ):
            issues.append("x_account.username の形式が不正です")
    try:
        accounts, themes = get_accounts(root, config)
        active_accounts = [item for item in accounts if item.get("status") == "active"]
        if len(active_accounts) < 1:
            issues.append("activeなnoteアカウントがありません")
        for account in active_accounts:
            if not isinstance(account.get("note_id"), str) or not account["note_id"].strip():
                issues.append(f"activeアカウント {account.get('account_id')} に有効なnote_idがありません")
        if not themes:
            issues.append("テーマがありません")
        get_account_theme(root, config, config["default_account_id"], config["default_theme_id"])
    except NoteTeamError as exc:
        issues.append(str(exc))
    history = load_json(resolve_inside(root, config["legacy_history_path"]))
    if not isinstance(history, list):
        issues.append("history.json は配列である必要があります")
    for metric_key, required in (
        ("note_csv", {"date", "run_id", "pv", "sales_count", "revenue_yen"}),
        ("x_csv", {"date", "run_id", "impressions", "link_clicks"}),
    ):
        path = resolve_inside(root, config["metrics"][metric_key])
        try:
            load_metric_rows(path, required)
        except NoteTeamError as exc:
            issues.append(str(exc))
    try:
        verify_style_corpus(root, config)
    except NoteTeamError as exc:
        issues.append(f"style corpusエラー: {exc}")
    try:
        states = list_states(root)
    except NoteTeamError as exc:
        issues.append(f"run状態エラー: {exc}")
        states = []
    for state in states:
        try:
            validate_state(state)
        except NoteTeamError as exc:
            issues.append(f"{state.get('run_id', 'unknown')}: {exc}")
    return issues


def state_summary(state: dict[str, Any]) -> str:
    stage = state["current_stage"]
    stage_data = state["stages"][stage]
    return (
        f"{state['run_id']} | {state['status']} | {stage}:{stage_data['status']} | "
        f"{state['account_id']} / {state['theme_id']}"
    )


def resolve_report_output(root: Path, requested: Path | None, month: str | None) -> Path:
    if not month:
        raise NoteTeamError("月次分析は month=YYYY-MM が必須です")
    report_root = ensure_private_directory(root.resolve(), REPORTS_REL)
    if requested is None:
        candidate = report_root / f"{month}.md"
    else:
        raw_candidate = requested if requested.is_absolute() else root.resolve() / requested
        candidate = Path(os.path.abspath(raw_candidate))
    try:
        relative = candidate.relative_to(report_root)
    except ValueError as exc:
        raise NoteTeamError(f"分析出力は {REPORTS_REL} 配下だけに保存できます") from exc
    parent = ensure_private_directory(report_root, relative.parent)
    candidate = parent / relative.name
    if candidate.is_symlink():
        raise NoteTeamError(f"分析出力にシンボリックリンクは使えません: {candidate}")
    if candidate.suffix.lower() != ".md":
        raise NoteTeamError("分析出力は .md ファイルにしてください")
    return candidate


def write_report(path: Path, payload: bytes, force: bool) -> None:
    if force:
        if path.is_symlink():
            raise NoteTeamError("分析出力にシンボリックリンクは使えません")
        atomic_write_bytes(path, payload)
        return
    try:
        fd = open_private_regular_file(
            path, os.O_CREAT | os.O_EXCL | os.O_WRONLY
        )
    except FileExistsError as exc:
        raise NoteTeamError("分析レポートは既に存在します。更新する場合は --force を指定してください") from exc
    except OSError as exc:
        raise NoteTeamError(f"分析レポートを安全に作成できません: {path}") from exc
    with os.fdopen(fd, "wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())


def artifact_preview(root: Path, state: dict[str, Any], target: dict[str, Any]) -> str:
    relative = target.get("artifact")
    if not relative:
        return ""
    try:
        path = resolve_inside(run_dir(root, state["run_id"]), relative)
        content = path.read_text(encoding="utf-8")
    except (NoteTeamError, OSError, UnicodeDecodeError):
        return "<p>成果物を表示できません。</p>"
    truncated = len(content) > 30_000
    content = content[:30_000]
    suffix = "\n\n[表示は30,000文字で省略]" if truncated else ""
    return (
        "<details open><summary>レビュー対象: "
        + html.escape(relative)
        + "</summary><pre>"
        + html.escape(content + suffix)
        + "</pre></details>"
    )


def qa_badge(target: dict[str, Any]) -> str:
    qa = target.get("director_qa")
    if not isinstance(qa, dict):
        return ""
    return (
        "<p><strong>Director QA:</strong> "
        + html.escape(str(qa.get("score")))
        + " / 100, "
        + html.escape(str(qa.get("verdict")))
        + "</p>"
    )


def render_style_candidate(
    root: Path, candidate: dict[str, Any], *, source_type: str
) -> str:
    metrics_payload = candidate.get("metrics", {})
    if source_type == "x" and isinstance(metrics_payload, dict):
        metrics_payload = metrics_payload.get("public_metrics", {})
    metrics = json.dumps(metrics_payload, ensure_ascii=False, sort_keys=True)
    constraints = candidate.get("constraints", [])
    constraint_items = "".join(
        f"<li>{html.escape(str(item))}</li>" for item in constraints
    )
    source_url = str(candidate.get("source_url", ""))
    extra = ""
    full_text = ""
    if source_type == "note":
        try:
            _, content, _ = read_repo_text_file(
                root,
                str(candidate.get("source_path", "")),
                "style note source",
                reject_secrets=True,
            )
            truncated = len(content) > 30_000
            content = content[:30_000]
            if truncated:
                content += "\n\n[表示は30,000文字で省略]"
            full_text = (
                "<details><summary>承認対象のnote本文を全文確認</summary>"
                f"<pre>{html.escape(content)}</pre></details>"
            )
        except NoteTeamError as exc:
            full_text = (
                "<p><strong>note本文を表示できません: "
                + html.escape(str(exc))
                + "</strong></p>"
            )
        extra = (
            "<p><strong>参照元:</strong> <code>"
            + html.escape(str(candidate.get("source_path", "")))
            + "</code></p>"
            "<p><strong>公開日:</strong> "
            + html.escape(str(candidate.get("published_at", "")))
            + " / <strong>公開確認日:</strong> "
            + html.escape(str(candidate.get("public_verified_at", "")))
            + " ("
            + html.escape(str(candidate.get("verification_precision", "")))
            + ")</p><p><strong>本文SHA-256:</strong> <code>"
            + html.escape(str(candidate.get("file_sha256", "")))
            + "</code></p>"
        )
    else:
        full_text = (
            "<details><summary>承認対象のX本文を全文確認</summary>"
            f"<pre>{html.escape(str(candidate.get('text', '')))}</pre></details>"
        )
        extra = (
            "<p><strong>tweet ID:</strong> <code>"
            + html.escape(str(candidate.get("tweet_id", "")))
            + "</code></p><p><strong>投稿者:</strong> @"
            + html.escape(str(candidate.get("author_username", "")))
            + " / <code>"
            + html.escape(str(candidate.get("author_id", "")))
            + "</code></p><p><strong>投稿日時:</strong> "
            + html.escape(str(candidate.get("posted_at", "")))
            + " / <strong>指標基準日:</strong> "
            + html.escape(str(candidate.get("metrics_as_of", "")))
            + "</p><p><strong>本文SHA-256:</strong> <code>"
            + html.escape(str(candidate.get("text_sha256", "")))
            + "</code></p><p><strong>追跡元:</strong> <code>"
            + html.escape(str(candidate.get("source_queue", "")))
            + "</code> / <code>"
            + html.escape(str(candidate.get("source_ledger", "")))
            + "</code></p>"
        )
    return (
        "<article class='candidate'>"
        f"<h4>{html.escape(str(candidate.get('title', '')))}</h4>"
        f"<p><code>{html.escape(str(candidate.get('candidate_id', '')))}</code></p>"
        f"<pre>{html.escape(str(candidate.get('preview', '')))}</pre>"
        f"{full_text}"
        f'<p><a href="{html.escape(source_url, quote=True)}" target="_blank" rel="noopener noreferrer">'
        f"{html.escape(source_url)}</a></p>"
        f"{extra}<p><strong>metrics:</strong> <code>{html.escape(metrics)}</code></p>"
        f"<p><strong>制約:</strong></p><ul>{constraint_items}</ul></article>"
    )


def render_style_corpus_card(root: Path, csrf_token: str) -> str:
    try:
        config = load_config(root)
        candidate_pack, pack_sha, manifest, selection_sha = load_style_candidate_pack(
            root, config
        )
    except NoteTeamError as exc:
        return (
            "<section class='card style-corpus'><h2>文体学習元のオーナー承認</h2>"
            "<p><strong>候補packは準備中、または検証に失敗しました。"
            "承認ボタンは表示しません。</strong></p>"
            f"<p>{html.escape(str(exc))}</p></section>"
        )

    notes = "".join(
        render_style_candidate(root, candidate, source_type="note")
        for candidate in candidate_pack["note_candidates"]
    )
    x_posts = "".join(
        render_style_candidate(root, candidate, source_type="x")
        for candidate in candidate_pack["x_candidates"]
    )
    limitations = "".join(
        f"<li>{html.escape(str(item))}</li>"
        for item in candidate_pack.get("limitations", [])
    )
    candidate_listing = (
        "<p><strong>共通制約:</strong> 売上不明 / X反応は小規模 / "
        "本人手書きとは未確定。AI素案を含むブランド文体候補です。</p>"
        f"<p><strong>候補pack SHA-256:</strong> <code>{html.escape(pack_sha)}</code><br>"
        f"<strong>選択SHA-256:</strong> <code>{html.escape(selection_sha)}</code></p>"
        f"<ul>{limitations}</ul>"
        f"<h3>公開確認済みnote（3本）</h3><div class='style-grid'>{notes}</div>"
        f"<h3>実投稿確認済みX（20本）</h3><div class='style-grid'>{x_posts}</div>"
    )

    try:
        registry, registry_sha = load_style_registry_raw(root)
    except NoteTeamError as exc:
        status_html = (
            "<p><strong>style corpus registryを安全に読み込めないため承認できません。</strong></p>"
            f"<p>{html.escape(str(exc))}</p>"
        )
    else:
        if registry.get("status") == "approved":
            try:
                validate_approved_style_registry(
                    registry, candidate_pack, pack_sha, manifest, selection_sha
                )
            except NoteTeamError as exc:
                status_html = (
                    "<p><strong>承認済みregistryまたは参照元が改変されています。"
                    "新規run作成とdraft submitは停止します。</strong></p>"
                    f"<p>{html.escape(str(exc))}</p>"
                )
            else:
                status_html = (
                    "<p class='approved-status'><strong>固定候補はオーナー承認済みです。</strong></p>"
                    f"<p>承認日時: {html.escape(str(registry.get('approved_at')))} / "
                    f"selection SHA-256: <code>{html.escape(selection_sha)}</code></p>"
                )
        elif registry.get("status") in {"setup-required", "owner-approval-required"}:
            fields = (
                f'<input type="hidden" name="csrf" value="{html.escape(csrf_token, quote=True)}">'
                '<input type="hidden" name="action" value="approve_style_corpus">'
                f'<input type="hidden" name="candidate_pack_sha256" value="{html.escape(pack_sha, quote=True)}">'
                f'<input type="hidden" name="registry_sha256" value="{html.escape(registry_sha, quote=True)}">'
            )
            status_html = (
                "<p><strong>上の固定セットだけを文体学習元として承認します。"
                "売上実績や本人手書きの認定ではありません。</strong></p>"
                f'<form method="post" action="/action">{fields}'
                '<button class="authorize">固定note 3本＋X 20本を承認</button></form>'
            )
        else:
            status_html = (
                "<p><strong>style corpus registryが承認可能な状態ではありません:</strong> "
                + html.escape(str(registry.get("status")))
                + "</p>"
            )
    return (
        "<section class='card style-corpus'><h2>文体学習元のオーナー承認</h2>"
        f"{candidate_listing}{status_html}</section>"
    )


def render_dashboard(
    root: Path, states: list[dict[str, Any]], csrf_token: str, message: str = ""
) -> str:
    style_card = render_style_corpus_card(root, csrf_token)
    cards: list[str] = []
    for state in states:
        stage = state["current_stage"]
        stage_data = state["stages"][stage]
        controls = ""
        if stage_data["status"] == "review":
            if stage == "plan":
                selection = plan_selection_controls(
                    state["run_id"],
                    csrf_token,
                    stage_data.get("proposal_ids", []),
                    state.get("selected_plan_id"),
                )
            elif stage == "promotion":
                selection = promotion_selection_controls(
                    state["run_id"],
                    csrf_token,
                    stage_data.get("promotion_ids", []),
                    state.get("selected_promotion_id"),
                )
            else:
                selection = ""
            fact_pack = (
                fact_pack_controls(root, state, csrf_token)
                if stage == "plan" and state.get("product_profile") == "paid-longform"
                else ""
            )
            controls = fact_pack + selection + (
                external_review_controls(state["run_id"], stage, csrf_token)
                if stage in EXTERNAL_AUTH_STAGES
                else action_controls(state["run_id"], stage, csrf_token)
            )
        elif stage_data["status"] == "owner_escalation":
            controls = (
                external_escalation_controls(state["run_id"], stage, csrf_token)
                if stage in EXTERNAL_AUTH_STAGES
                else escalation_controls(state["run_id"], stage, csrf_token)
            )
        elif stage_data["status"] == "authorization_ready":
            preflight_target = {
                "artifact": stage_data.get("preflight_artifact"),
                "artifact_sha256": stage_data.get("preflight_sha256"),
            }
            try:
                verify_snapshot(run_dir(root, state["run_id"]), preflight_target)
                controls = (
                    artifact_preview(root, state, preflight_target)
                    + external_controls(state["run_id"], stage, csrf_token)
                )
            except NoteTeamError:
                controls = "<p><strong>外部操作の事前確認記録が変更されたため許可できません。</strong></p>"
        elif stage_data["status"] == "authorization_required":
            controls = f"<p><strong>{html.escape(stage)} の読み取り専用事前確認待ちです。まだ外部操作は許可できません。</strong></p>"
        elif stage_data["status"] == "authorized":
            controls = f"<p><strong>10分間・1回限りの{html.escape(stage)}許可済みです。外部操作直前のclaim待ちです。</strong></p>"
        elif stage_data["status"] == "external_in_progress":
            controls = f"<p><strong>{html.escape(stage)}を実行中です。許可はすでに使用済みです。</strong></p>"
        elif stage_data["status"] == "reconciliation_required":
            controls = reconciliation_controls(
                state["run_id"],
                stage,
                csrf_token,
                str(stage_data.get("claim_id") or ""),
                stage_data,
            )
        unit_rows = []
        for unit, unit_data in stage_data.get("units", {}).items():
            if unit_data["status"] == "review":
                unit_control = action_controls(state["run_id"], stage, csrf_token, unit)
            elif unit_data["status"] == "owner_escalation":
                unit_control = escalation_controls(state["run_id"], stage, csrf_token, unit)
            else:
                unit_control = ""
            unit_rows.append(
                f"<li><code>{html.escape(unit)}</code>: {html.escape(unit_data['status'])}"
                f"{qa_badge(unit_data)}{artifact_preview(root, state, unit_data)}{unit_control}</li>"
            )
        cards.append(
            "<section class='card'>"
            f"<h2>{html.escape(state['run_id'])}</h2>"
            f"<p>{html.escape(state['account_id'])} / {html.escape(state['theme_id'])}</p>"
            f"<p>工程: <strong>{html.escape(stage)}</strong> / {html.escape(stage_data['status'])}</p>"
            f"<p>run状態: {html.escape(state['status'])}</p>"
            f"{qa_badge(stage_data)}{artifact_preview(root, state, stage_data)}{controls}<ul>{''.join(unit_rows)}</ul></section>"
        )
    notice = f"<p class='notice'>{html.escape(message)}</p>" if message else ""
    return f"""<!doctype html>
<html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>note販売AIチーム 承認画面</title>
<style>
body{{font-family:-apple-system,BlinkMacSystemFont,'Hiragino Sans',sans-serif;background:#f5f4ef;color:#252525;margin:0;padding:24px}}
main{{max-width:900px;margin:auto}}.card{{background:#fff;border:1px solid #ddd8cc;border-radius:14px;padding:20px;margin:16px 0;box-shadow:0 3px 16px #0000000d}}
form{{display:inline-block;margin:6px 8px 6px 0}}button{{border:0;border-radius:9px;padding:10px 14px;font-weight:700;cursor:pointer}}
.approve{{background:#17865d;color:white}}.revise{{background:#e2a628;color:#222}}.reject{{background:#b53d3d;color:white}}.authorize{{background:#315da8;color:white}}
input[type=text]{{max-width:260px;padding:9px;border:1px solid #bbb;border-radius:8px}}.notice{{background:#fff4bf;padding:12px;border-radius:8px}}code{{background:#eee;padding:2px 5px;border-radius:5px}}
pre{{white-space:pre-wrap;overflow-wrap:anywhere;background:#f7f7f7;border:1px solid #e1e1e1;border-radius:8px;padding:14px;max-height:55vh;overflow:auto}}details{{margin:12px 0}}summary{{cursor:pointer;font-weight:700}}
.style-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:12px}}.candidate{{border:1px solid #e1e1e1;border-radius:10px;padding:12px;min-width:0}}.candidate pre{{max-height:180px}}.candidate a{{overflow-wrap:anywhere}}.approved-status{{color:#087346}}
</style></head><body><main><h1>note販売AIチーム 承認画面</h1>
<p>この画面は127.0.0.1だけで動作します。note公開とX投稿は、表示内容の個別許可後にだけworkerが実行します。</p>{notice}{style_card}{''.join(cards) or '<p>runはまだありません。</p>'}</main></body></html>"""


def hidden_fields(run_id_value: str, stage: str, token: str, action: str, unit: str | None) -> str:
    unit_field = f'<input type="hidden" name="unit" value="{html.escape(unit)}">' if unit else ""
    return (
        f'<input type="hidden" name="csrf" value="{html.escape(token)}">'
        f'<input type="hidden" name="run_id" value="{html.escape(run_id_value)}">'
        f'<input type="hidden" name="stage" value="{html.escape(stage)}">'
        f'<input type="hidden" name="action" value="{html.escape(action)}">{unit_field}'
    )


def action_controls(run_id_value: str, stage: str, token: str, unit: str | None = None) -> str:
    base = hidden_fields(run_id_value, stage, token, "approve", unit)
    revise = hidden_fields(run_id_value, stage, token, "revise", unit)
    reject_fields = hidden_fields(run_id_value, stage, token, "reject", unit)
    return (
        f'<form method="post" action="/action">{base}<button class="approve">承認</button></form>'
        f'<form method="post" action="/action">{revise}<input name="comment" type="text" required placeholder="修正内容">'
        '<button class="revise">修正</button></form>'
        f'<form method="post" action="/action">{reject_fields}<input name="comment" type="text" required placeholder="却下理由">'
        '<button class="reject">却下</button></form>'
    )


def external_review_controls(run_id_value: str, stage: str, token: str) -> str:
    approve_fields = hidden_fields(run_id_value, stage, token, "approve", None)
    reject_fields = hidden_fields(run_id_value, stage, token, "reject", None)
    return (
        f"<p>{html.escape(stage)} の実行結果です。ここから同じ外部操作を再実行しません。</p>"
        f'<form method="post" action="/action">{approve_fields}<button class="approve">{html.escape(stage)}結果を承認</button></form>'
        f'<form method="post" action="/action">{reject_fields}<input name="comment" type="text" required placeholder="停止理由">'
        '<button class="reject">runを停止</button></form>'
    )


def reconciliation_controls(
    run_id_value: str,
    stage: str,
    token: str,
    claim_id: str,
    stage_data: dict[str, Any],
) -> str:
    absent_fields = hidden_fields(
        run_id_value, stage, token, "confirm_no_external_result", None
    )
    reject_fields = hidden_fields(run_id_value, stage, token, "reject", None)
    components = stage_data.get("components") if stage == "x_publish" else None
    main = components.get("main", {}) if isinstance(components, dict) else {}
    if main.get("status") == "posted":
        main_id = html.escape(str(main.get("tweet_id") or ""))
        main_url = html.escape(str(main.get("tweet_url") or ""), quote=True)
        reply = components.get("reply", {}) if isinstance(components, dict) else {}
        if reply.get("status") == "posted":
            next_step = "リプIDも台帳に固定済みです。同じclaim IDの読み戻し結果JSONをsubmitします。"
        else:
            next_step = "リプIDは台帳に固定されていません。後付けで別tweetを同じclaimへ帰属せず、本投稿を保護してrunを停止します。"
        resolution = (
            "<p><strong>X本投稿は確定済みです。重複防止のため台帳のリセットと本投稿の再POSTはできません。</strong></p>"
            f'<p>main: <a href="{main_url}" target="_blank" rel="noopener noreferrer">{main_id}</a></p>'
            f"<p>{html.escape(next_step)}</p>"
        )
    else:
        resolution = (
            "<p>外部結果が見つかった場合は、同じclaim IDの結果JSONをsubmitします。"
            "作成・公開・投稿が無いことを対象媒体で確認した場合だけ、以下で再許可待ちへ戻します。</p>"
            f'<form method="post" action="/action">{absent_fields}<input name="comment" type="text" required placeholder="確認したアカウントと一覧/API結果">'
            '<button class="authorize">結果不存在を確認し、再許可待ちへ戻す</button></form>'
        )
    return (
        "<p><strong>外部操作の結果が不明です。自動再試行は停止しています。</strong></p>"
        f"<p>claim ID: <code>{html.escape(claim_id)}</code></p>"
        f"{resolution}"
        f'<form method="post" action="/action">{reject_fields}<input name="comment" type="text" required placeholder="停止理由">'
        '<button class="reject">runを停止</button></form>'
    )


def plan_selection_controls(
    run_id_value: str,
    csrf_token: str,
    proposal_ids: Iterable[str],
    selected_plan_id: str | None,
) -> str:
    buttons: list[str] = []
    for plan_id in proposal_ids:
        selected = " 選択中" if plan_id == selected_plan_id else ""
        fields = hidden_fields(run_id_value, "plan", csrf_token, "select_plan", None)
        buttons.append(
            f'<form method="post" action="/action">{fields}'
            f'<input type="hidden" name="plan_id" value="{html.escape(plan_id)}">'
            f'<button class="authorize">{html.escape(plan_id)}{selected}</button></form>'
        )
    return "<p><strong>構成へ進める企画を1案選択:</strong></p>" + "".join(buttons)


def promotion_selection_controls(
    run_id_value: str,
    csrf_token: str,
    promotion_ids: Iterable[str],
    selected_promotion_id: str | None,
) -> str:
    buttons: list[str] = []
    for promotion_id in promotion_ids:
        selected = " 選択中" if promotion_id == selected_promotion_id else ""
        fields = hidden_fields(
            run_id_value, "promotion", csrf_token, "select_promotion", None
        )
        buttons.append(
            f'<form method="post" action="/action">{fields}'
            f'<input type="hidden" name="promotion_id" value="{html.escape(promotion_id)}">'
            f'<button class="authorize">{html.escape(promotion_id)}{selected}</button></form>'
        )
    return "<p><strong>Xに自動投稿する案を1案選択:</strong></p>" + "".join(buttons)


def fact_pack_controls(root: Path, state: dict[str, Any], token: str) -> str:
    record = state.get("inputs", {}).get("fact_pack")
    if not isinstance(record, dict):
        return "<p><strong>paid-longformのfact pack固定待ちです。</strong></p>"
    try:
        verify_fact_pack(root, state, require_owner_approval=False)
    except NoteTeamError as exc:
        return f"<p><strong>fact packエラー: {html.escape(str(exc))}</strong></p>"
    preview = artifact_preview(root, state, record)
    if record.get("owner_approved_at") and record.get("owner_approved_by") == "owner":
        return preview + "<p><strong>fact packはオーナー承認済みです。</strong></p>"
    fields = hidden_fields(state["run_id"], "plan", token, "approve_fact_pack", None)
    return (
        preview
        + "<p><strong>本文で使ってよい事実・体験・数値かを確認してください。</strong></p>"
        + f'<form method="post" action="/action">{fields}<button class="authorize">fact packを承認</button></form>'
    )


def external_controls(run_id_value: str, stage: str, token: str) -> str:
    authorize = hidden_fields(run_id_value, stage, token, "authorize", None)
    reject_fields = hidden_fields(run_id_value, stage, token, "reject", None)
    labels = {
        "note_draft": ("note新規下書き保存", "公開操作は含みません"),
        "note_publish": ("noteの対象下書き公開", "X投稿は含みません"),
        "x_publish": ("X本投稿と1件目リプ投稿", "note公開許可とは別です"),
    }
    action_label, boundary = labels[stage]
    return (
        f'<p><strong>外部操作:</strong> {html.escape(action_label)}のみを1回限り許可します。{html.escape(boundary)}。</p>'
        f'<form method="post" action="/action">{authorize}<button class="authorize">{html.escape(action_label)}を許可</button></form>'
        f'<form method="post" action="/action">{reject_fields}<input name="comment" type="text" required placeholder="停止理由">'
        '<button class="reject">停止</button></form>'
    )


def escalation_controls(
    run_id_value: str, stage: str, csrf_token: str, unit: str | None = None
) -> str:
    extend = hidden_fields(run_id_value, stage, csrf_token, "extend_quality_loop", unit)
    reject_fields = hidden_fields(run_id_value, stage, csrf_token, "reject", unit)
    return (
        "<p><strong>品質ループが5回に達しました。自動では続行しません。</strong></p>"
        f'<form method="post" action="/action">{extend}<button class="authorize">追加1ループを明示許可</button></form>'
        f'<form method="post" action="/action">{reject_fields}<input name="comment" type="text" required placeholder="停止理由">'
        '<button class="reject">runを却下・停止</button></form>'
    )


def external_escalation_controls(
    run_id_value: str, stage: str, csrf_token: str
) -> str:
    extend = hidden_fields(
        run_id_value, stage, csrf_token, "extend_quality_loop", None
    )
    reject_fields = hidden_fields(run_id_value, stage, csrf_token, "reject", None)
    return (
        f"<p><strong>{html.escape(stage)}結果の照合が5回失敗し、停止しました。外部操作の自動再試行はしません。</strong></p>"
        f'<form method="post" action="/action">{extend}<button class="authorize">同じclaimの照合だけ追加許可</button></form>'
        f'<form method="post" action="/action">{reject_fields}<input name="comment" type="text" required placeholder="停止理由">'
        '<button class="reject">runを却下・停止</button></form>'
    )


def make_handler(root: Path, bootstrap_token: str):
    session_token = secrets.token_urlsafe(32)
    csrf_token = secrets.token_urlsafe(24)
    bootstrap_lock = threading.Lock()
    bootstrap_used = False

    class ApprovalHandler(BaseHTTPRequestHandler):
        server_version = "NoteTeamApproval/1.0"

        def _session_authorized(self) -> bool:
            cookies: dict[str, str] = {}
            for item in self.headers.get("Cookie", "").split(";"):
                if "=" in item:
                    key, value = item.strip().split("=", 1)
                    cookies[key] = value
            return secrets.compare_digest(cookies.get("note_session", ""), session_token)

        def _host_allowed(self) -> bool:
            host = self.headers.get("Host", "").lower()
            return host in {
                f"127.0.0.1:{self.server.server_address[1]}",
                f"localhost:{self.server.server_address[1]}",
            }

        def _origin_kind(self) -> str:
            origin = self.headers.get("Origin")
            if origin is None:
                return "missing"
            if origin == "null":
                return "null"
            try:
                parsed = urllib.parse.urlparse(origin)
                origin_port = parsed.port
            except ValueError:
                return "foreign"
            if (
                parsed.scheme == "http"
                and parsed.hostname in {"127.0.0.1", "localhost"}
                and origin_port == self.server.server_address[1]
                and parsed.username is None
                and parsed.password is None
                and parsed.path in {"", "/"}
                and not parsed.query
                and not parsed.fragment
            ):
                return "loopback"
            return "foreign"

        def _same_origin(self) -> bool:
            return self._host_allowed() and self._origin_kind() in {
                "missing",
                "loopback",
            }

        def _security_headers(self) -> None:
            self.send_header("Cache-Control", "no-store")
            self.send_header("Pragma", "no-cache")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")

        def do_GET(self) -> None:  # noqa: N802
            nonlocal bootstrap_used
            parsed = urllib.parse.urlparse(self.path)
            values = urllib.parse.parse_qs(parsed.query)
            if parsed.path != "/" or not self._same_origin():
                self.send_error(HTTPStatus.FORBIDDEN)
                return
            presented = (values.get("token") or [""])[0]
            if presented:
                with bootstrap_lock:
                    valid_bootstrap = not bootstrap_used and secrets.compare_digest(
                        presented, bootstrap_token
                    )
                    if valid_bootstrap:
                        bootstrap_used = True
                if not valid_bootstrap and not self._session_authorized():
                    self.send_error(HTTPStatus.FORBIDDEN)
                    return
                if valid_bootstrap:
                    self.send_response(HTTPStatus.SEE_OTHER)
                    self._security_headers()
                    self.send_header(
                        "Set-Cookie",
                        f"note_session={session_token}; HttpOnly; SameSite=Strict; Path=/",
                    )
                    self.send_header("Location", "/")
                    self.end_headers()
                    return
            if not self._session_authorized():
                self.send_error(HTTPStatus.FORBIDDEN)
                return
            body = render_dashboard(root, list_states(root), csrf_token).encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'")
            self._security_headers()
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self) -> None:  # noqa: N802
            path_allowed = self.path == "/action"
            host_allowed = self._host_allowed()
            session_allowed = self._session_authorized()
            origin_kind = self._origin_kind()
            if not path_allowed or not host_allowed or not session_allowed:
                fetch_site = self.headers.get("Sec-Fetch-Site", "")[:32]
                sys.stderr.write(
                    "approval-ui: POST gate denied "
                    f"path={path_allowed} host={host_allowed} "
                    f"session={session_allowed} origin={origin_kind} "
                    f"fetch_site={fetch_site!r}\n"
                )
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                self.send_error(HTTPStatus.BAD_REQUEST)
                return
            if length <= 0 or length > 16_384:
                self.send_error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
                return
            values = urllib.parse.parse_qs(self.rfile.read(length).decode("utf-8"))
            csrf_allowed = secrets.compare_digest(
                (values.get("csrf") or [""])[0], csrf_token
            )
            if not csrf_allowed:
                self.send_error(HTTPStatus.FORBIDDEN)
                return
            if origin_kind not in {"missing", "loopback", "null"}:
                sys.stderr.write(
                    "approval-ui: POST gate denied "
                    f"path={path_allowed} host={host_allowed} "
                    f"session={session_allowed} origin={origin_kind} csrf=True\n"
                )
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            run_id_value = (values.get("run_id") or [""])[0]
            stage = (values.get("stage") or [""])[0]
            action = (values.get("action") or [""])[0]
            unit = (values.get("unit") or [None])[0]
            comment = (values.get("comment") or [""])[0]
            plan_id = (values.get("plan_id") or [""])[0]
            promotion_id = (values.get("promotion_id") or [""])[0]
            candidate_pack_sha256 = (
                values.get("candidate_pack_sha256") or [""]
            )[0]
            registry_sha256 = (values.get("registry_sha256") or [""])[0]
            try:
                if action == "approve_style_corpus":
                    approve_style_corpus(
                        root,
                        candidate_pack_sha256,
                        registry_sha256,
                        owner_session_confirmed=True,
                    )
                elif action == "approve":
                    approve(
                        root,
                        run_id_value,
                        stage,
                        comment=comment,
                        unit=unit,
                        owner_session_confirmed=True,
                    )
                elif action == "revise":
                    request_revision(
                        root,
                        run_id_value,
                        stage,
                        comment=comment,
                        unit=unit,
                        owner_session_confirmed=True,
                    )
                elif action == "reject":
                    reject(
                        root,
                        run_id_value,
                        stage,
                        comment=comment,
                        unit=unit,
                        owner_session_confirmed=True,
                    )
                elif action == "authorize":
                    authorize_external(
                        root,
                        run_id_value,
                        stage,
                        owner_session_confirmed=True,
                    )
                elif action == "select_plan":
                    select_plan(
                        root,
                        run_id_value,
                        plan_id,
                        owner_session_confirmed=True,
                    )
                elif action == "select_promotion":
                    select_promotion(
                        root,
                        run_id_value,
                        promotion_id,
                        owner_session_confirmed=True,
                    )
                elif action == "approve_fact_pack":
                    approve_fact_pack(
                        root,
                        run_id_value,
                        owner_session_confirmed=True,
                    )
                elif action == "extend_quality_loop":
                    extend_quality_loop(
                        root,
                        run_id_value,
                        stage,
                        unit,
                        owner_session_confirmed=True,
                    )
                elif action in {"confirm_no_external_result", "confirm_no_external_draft"}:
                    confirm_no_external_result(
                        root,
                        run_id_value,
                        stage,
                        comment,
                        owner_session_confirmed=True,
                    )
                else:
                    raise NoteTeamError("不正な操作です")
            except NoteTeamError as exc:
                body = render_dashboard(root, list_states(root), csrf_token, str(exc)).encode("utf-8")
                self.send_response(HTTPStatus.CONFLICT)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self._security_headers()
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            self.send_response(HTTPStatus.SEE_OTHER)
            self._security_headers()
            self.send_header("Location", "/")
            self.end_headers()

        def log_message(self, fmt: str, *args: Any) -> None:
            status = args[-1] if args else ""
            sys.stderr.write(f"approval-ui: {self.command} {self.path.split('?', 1)[0]} {status}\n")

    return ApprovalHandler


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="note販売AIチームのローカル制御")
    parser.add_argument("--root", type=Path, help="リポジトリルート（通常は自動検出）")
    sub = parser.add_subparsers(dest="command", required=True)

    create = sub.add_parser("create", help="新しい記事runを作る")
    create.add_argument("--account", default=None)
    create.add_argument("--theme", default=None)
    create.add_argument("--slug", required=True)
    create.add_argument("--title")
    create.add_argument("--profile", choices=("free-standard", "paid-longform"), default="free-standard")
    create.add_argument("--run-id")
    create.add_argument("--fact-pack", type=Path)

    sub.add_parser("list", help="run一覧")
    status = sub.add_parser("status", help="run状態")
    status.add_argument("run_id")

    units = sub.add_parser("set-units", help="章などの承認単位を登録")
    units.add_argument("run_id")
    units.add_argument("stage", choices=STAGES)
    units.add_argument("units", nargs="+")

    submit = sub.add_parser("submit", help="成果物をレビューへ出す")
    submit.add_argument("run_id")
    submit.add_argument("stage", choices=STAGES)
    submit.add_argument("artifact")
    submit.add_argument("--actor", default="agent")
    submit.add_argument("--unit")
    submit.add_argument("--qa-artifact")

    preflight = sub.add_parser("preflight", help="外部操作前のアカウント・入力一致を記録")
    preflight.add_argument("run_id")
    preflight.add_argument("artifact")
    preflight.add_argument("--stage", choices=tuple(sorted(EXTERNAL_AUTH_STAGES)), default="note_draft")
    preflight.add_argument("--actor", default="note-article-publisher")

    attach = sub.add_parser("attach-fact-pack", help="オーナー承認済みの事実資料をrunに固定")
    attach.add_argument("run_id")
    attach.add_argument("fact_pack", type=Path)
    attach.add_argument("--actor", default="owner")

    claim = sub.add_parser("claim-external", help="承認済み外部操作をブラウザ書き込み直前に1回限りclaim")
    claim.add_argument("run_id")
    claim.add_argument("stage", choices=STAGES)
    claim.add_argument("--actor", default="note-article-publisher")

    failure = sub.add_parser(
        "external-failure",
        help="外部操作失敗を記録し、手動照合待ちで自動再試行を止める",
    )
    failure.add_argument("run_id")
    failure.add_argument("stage", choices=STAGES)
    failure.add_argument("--comment", required=True)
    failure.add_argument("--actor", default="note-article-publisher")

    component = sub.add_parser(
        "record-external-component",
        help="X本投稿/リプのPOST成功を次のAPI呼び出し前に固定",
    )
    component.add_argument("run_id")
    component.add_argument("stage", choices=("x_publish",))
    component.add_argument("component", choices=("main", "reply"))
    component.add_argument("object_id")
    component.add_argument("object_url")
    component.add_argument("--actor", default="x-publish-worker")

    analyze = sub.add_parser("analyze", help="実値CSVを集計")
    analyze.add_argument("--month", required=True)
    analyze.add_argument("--output", type=Path)
    analyze.add_argument("--force", action="store_true", help="既存の月次レポートを明示的に更新")

    sub.add_parser("validate", help="設定と状態を検証")
    serve = sub.add_parser("serve", help="ローカル承認画面を起動")
    serve.add_argument("--port", type=int, default=8767)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        root = (args.root.resolve() if args.root else repo_root())
        if args.command == "create":
            config = load_config(root)
            state, existed = create_run(
                root,
                args.account or config["default_account_id"],
                args.theme or config["default_theme_id"],
                args.slug,
                args.title,
                args.profile,
                args.run_id,
                args.fact_pack,
            )
            print(("EXISTING " if existed else "CREATED ") + state_summary(state))
        elif args.command == "list":
            states = list_states(root)
            print("\n".join(state_summary(state) for state in states) or "runはありません")
        elif args.command == "status":
            print(json.dumps(load_state(root, args.run_id), ensure_ascii=False, indent=2))
        elif args.command == "set-units":
            print(state_summary(set_units(root, args.run_id, args.stage, args.units)))
        elif args.command == "submit":
            print(
                state_summary(
                    submit_artifact(
                        root,
                        args.run_id,
                        args.stage,
                        args.artifact,
                        args.actor,
                        args.unit,
                        args.qa_artifact,
                    )
                )
            )
        elif args.command == "preflight":
            print(
                state_summary(
                    submit_preflight(
                        root, args.run_id, args.artifact, args.actor, args.stage
                    )
                )
            )
        elif args.command == "attach-fact-pack":
            print(
                state_summary(
                    attach_fact_pack(root, args.run_id, args.fact_pack, args.actor)
                )
            )
        elif args.command == "claim-external":
            print(
                state_summary(
                    claim_external(root, args.run_id, args.stage, args.actor)
                )
            )
        elif args.command == "external-failure":
            print(
                state_summary(
                    record_external_failure(
                        root, args.run_id, args.stage, args.comment, args.actor
                    )
                )
            )
        elif args.command == "record-external-component":
            print(
                state_summary(
                    record_external_component(
                        root,
                        args.run_id,
                        args.stage,
                        args.component,
                        args.object_id,
                        args.object_url,
                        args.actor,
                    )
                )
            )
        elif args.command == "analyze":
            result, markdown = analyze_metrics(root, args.month)
            output = resolve_report_output(root, args.output, args.month)
            write_report(output, markdown.encode("utf-8"), args.force)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            print(f"REPORT {output.relative_to(root)}")
        elif args.command == "validate":
            issues = validate_installation(root)
            if issues:
                print("VALIDATION FAILED")
                for issue in issues:
                    print(f"- {issue}")
                return 1
            print("VALIDATION PASSED")
        elif args.command == "serve":
            if not (1 <= args.port <= 65535):
                raise NoteTeamError("portは1〜65535で指定してください")
            token = secrets.token_urlsafe(24)
            server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(root, token))
            print(f"http://127.0.0.1:{args.port}/?token={token}", flush=True)
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                pass
            finally:
                server.server_close()
        return 0
    except NoteTeamError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
