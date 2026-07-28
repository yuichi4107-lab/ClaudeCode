#!/usr/bin/env python3
"""Daily commit, push, then pull routine for the local YNFactory Git clone."""

from __future__ import annotations

import argparse
import datetime as dt
import os
import platform
import re
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Iterable
from zoneinfo import ZoneInfo


JST = ZoneInfo("Asia/Tokyo")
MAX_STAGED_FILE_BYTES = 50 * 1024 * 1024
LOG_TRIM_CHARS = 12000
SECRET_PATTERNS: list[tuple[str, re.Pattern[bytes]]] = [
    ("private key", re.compile(rb"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("Stripe secret", re.compile(rb"\b(sk_(live|test)|whsec)_[A-Za-z0-9]{16,}")),
    ("Google OAuth secret", re.compile(rb"\bGOCSPX-[A-Za-z0-9_-]{10,}")),
    ("GitHub token", re.compile(rb"\bgh[pousr]_[A-Za-z0-9_]{20,}")),
    ("OpenAI key", re.compile(rb"\b(sk-proj-[A-Za-z0-9_-]{20,}|sk-[A-Za-z0-9]{32,})")),
    ("Slack token", re.compile(rb"\bxox[baprs]-[A-Za-z0-9-]{20,}")),
    ("Telegram bot token", re.compile(rb"\b\d{7,12}:[A-Za-z0-9_-]{30,}\b")),
    ("AWS access key", re.compile(rb"\bAKIA[0-9A-Z]{16}\b")),
]
DANGEROUS_PATH_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"(^|/)\.env($|[./])"),
    re.compile(r"(^|/)credentials\.json$"),
    re.compile(r"(^|/)secrets?(/|$)"),
    re.compile(r"(^|/)\.company/engineering/sns-credentials(/|$)"),
    re.compile(r"\.(pem|key|p12|pfx)$", re.IGNORECASE),
]


class CommandError(RuntimeError):
    pass


class Logger:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._fh = path.open("a", encoding="utf-8")

    def close(self) -> None:
        self._fh.close()

    def line(self, message: str = "") -> None:
        print(message)
        self._fh.write(message + "\n")
        self._fh.flush()


def default_log_dir() -> Path:
    if platform.system() == "Darwin":
        return Path.home() / "Library" / "Logs" / "ynfactory-daily-git-sync"
    return Path.home() / ".ynfactory" / "logs" / "daily-git-sync"


def trim_output(value: str) -> str:
    if len(value) <= LOG_TRIM_CHARS:
        return value.rstrip()
    return value[:LOG_TRIM_CHARS].rstrip() + "\n...[trimmed]"


def run(
    args: list[str],
    *,
    cwd: Path,
    log: Logger,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    log.line("$ " + shlex.join(args))
    result = subprocess.run(
        args,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.stdout:
        log.line(trim_output(result.stdout))
    if result.stderr:
        log.line(trim_output(result.stderr))
    if check and result.returncode != 0:
        raise CommandError(f"command failed ({result.returncode}): {shlex.join(args)}")
    return result


def git_output(args: list[str], *, cwd: Path, log: Logger) -> str:
    return run(["git", *args], cwd=cwd, log=log).stdout.strip()


def git_blob_from_index(rel_path: str, *, cwd: Path, log: Logger) -> bytes | None:
    log.line("$ " + shlex.join(["git", "show", f":{rel_path}"]) + " [captured for scan]")
    result = subprocess.run(
        ["git", "show", f":{rel_path}"],
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.stderr:
        log.line(trim_output(result.stderr.decode("utf-8", errors="replace")))
    if result.returncode != 0:
        return None
    return result.stdout


def detect_git_root(start: Path, log: Logger) -> Path:
    result = run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=start,
        log=log,
        check=True,
    )
    return Path(result.stdout.strip()).resolve()


def lock_or_exit(root: Path, log: Logger):
    lock_path = root / ".git" / "daily-git-sync.lock"
    lock_fh = lock_path.open("w", encoding="utf-8")
    try:
        if os.name == "posix":
            import fcntl

            fcntl.flock(lock_fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        lock_fh.write(f"pid={os.getpid()}\n")
        lock_fh.flush()
    except BlockingIOError as exc:
        raise SystemExit("daily git sync is already running") from exc
    return lock_fh


def ensure_clean_git_state(root: Path, log: Logger) -> None:
    branch = git_output(["rev-parse", "--abbrev-ref", "HEAD"], cwd=root, log=log)
    if branch != "main":
        raise CommandError(f"refusing to run outside main branch: {branch}")

    git_dir = Path(git_output(["rev-parse", "--git-dir"], cwd=root, log=log))
    if not git_dir.is_absolute():
        git_dir = (root / git_dir).resolve()
    blocked_markers = [
        "MERGE_HEAD",
        "CHERRY_PICK_HEAD",
        "REVERT_HEAD",
        "rebase-merge",
        "rebase-apply",
    ]
    for marker in blocked_markers:
        if (git_dir / marker).exists():
            raise CommandError(f"refusing to run while Git operation is in progress: {marker}")

    unmerged = run(
        ["git", "diff", "--name-only", "--diff-filter=U"],
        cwd=root,
        log=log,
    ).stdout.strip()
    if unmerged:
        raise CommandError("refusing to run with unresolved merge conflicts")


def split_z(value: str) -> list[str]:
    return [item for item in value.split("\0") if item]


def has_worktree_changes(root: Path, log: Logger) -> bool:
    status = run(["git", "status", "--porcelain=v1", "-z"], cwd=root, log=log).stdout
    return bool(status)


def staged_paths(root: Path, log: Logger) -> list[str]:
    output = run(
        ["git", "diff", "--cached", "--name-only", "-z", "--diff-filter=ACMRT"],
        cwd=root,
        log=log,
    ).stdout
    return split_z(output)


def all_staged_paths(root: Path, log: Logger) -> list[str]:
    output = run(
        ["git", "diff", "--cached", "--name-only", "-z"],
        cwd=root,
        log=log,
    ).stdout
    return split_z(output)


def validate_staged_paths(paths: Iterable[str], root: Path) -> list[str]:
    problems: list[str] = []
    for rel in paths:
        rel_posix = Path(rel).as_posix()
        for pattern in DANGEROUS_PATH_PATTERNS:
            if pattern.search(rel_posix):
                problems.append(f"dangerous path staged: {rel_posix}")
                break
        full = root / rel
        if full.exists() and full.is_file() and full.stat().st_size > MAX_STAGED_FILE_BYTES:
            size_mb = full.stat().st_size / 1024 / 1024
            problems.append(f"staged file too large ({size_mb:.1f} MB): {rel_posix}")
    return problems


def validate_staged_content(root: Path, log: Logger) -> list[str]:
    problems: list[str] = []
    for rel in staged_paths(root, log):
        blob = git_blob_from_index(rel, cwd=root, log=log)
        if blob is None:
            continue
        for name, pattern in SECRET_PATTERNS:
            if pattern.search(blob):
                problems.append(f"{name} pattern detected in staged file: {rel}")
    return problems


def unstage_all(root: Path, log: Logger) -> None:
    run(["git", "reset", "--mixed"], cwd=root, log=log, check=False)


def commit_if_needed(root: Path, log: Logger, message_prefix: str) -> bool:
    if not has_worktree_changes(root, log):
        log.line("No local changes to commit.")
        return False

    run(["git", "add", "-A"], cwd=root, log=log)
    paths = all_staged_paths(root, log)
    if not paths:
        log.line("No staged changes after git add.")
        return False

    problems = validate_staged_paths(paths, root)
    problems.extend(validate_staged_content(root, log))
    whitespace = run(["git", "diff", "--cached", "--check"], cwd=root, log=log, check=False)
    if whitespace.returncode != 0:
        problems.append("git diff --cached --check failed")

    if problems:
        log.line("Validation failed; leaving working tree uncommitted.")
        for problem in problems:
            log.line(f"- {problem}")
        unstage_all(root, log)
        raise CommandError("staged validation failed")

    today = dt.datetime.now(JST).strftime("%Y-%m-%d")
    message = f"{message_prefix} {today}"
    run(["git", "commit", "-m", message], cwd=root, log=log)
    return True


def ahead_behind(root: Path, log: Logger, branch: str) -> tuple[int, int]:
    output = git_output(
        ["rev-list", "--left-right", "--count", f"origin/{branch}...HEAD"],
        cwd=root,
        log=log,
    )
    behind, ahead = (int(part) for part in output.split())
    return ahead, behind


def pull_rebase_or_abort(root: Path, log: Logger, branch: str) -> None:
    result = run(["git", "pull", "--rebase", "origin", branch], cwd=root, log=log, check=False)
    if result.returncode == 0:
        return
    log.line("Rebase pull failed; aborting rebase to leave the worktree stable.")
    run(["git", "rebase", "--abort"], cwd=root, log=log, check=False)
    raise CommandError("pull --rebase failed")


def push_with_rebase_retry(root: Path, log: Logger, branch: str, retries: int) -> None:
    for attempt in range(1, retries + 1):
        result = run(["git", "push", "origin", branch], cwd=root, log=log, check=False)
        if result.returncode == 0:
            return
        if attempt == retries:
            raise CommandError("push failed after retries")
        log.line(f"Push failed on attempt {attempt}; pulling with rebase before retry.")
        pull_rebase_or_abort(root, log, branch)


def sync_pull_changes_to_drive(root: Path, before: str, after: str, log: Logger) -> None:
    if before == after:
        log.line("No new remote changes pulled; Drive sync skipped.")
        return
    output = run(
        ["git", "diff", "--name-only", "-z", f"{before}..{after}"],
        cwd=root,
        log=log,
    ).stdout
    paths = split_z(output)
    if not paths:
        log.line("Pull changed HEAD but no file paths were detected; Drive sync skipped.")
        return
    script = root / ".company" / "scripts" / "sync_drive_git.py"
    if not script.exists():
        raise CommandError("sync_drive_git.py not found; cannot mirror pulled paths to Drive")

    chunk_size = 80
    for index in range(0, len(paths), chunk_size):
        chunk = paths[index : index + chunk_size]
        run(["python3", str(script), "local-to-drive", *chunk], cwd=root, log=log)


def run_once(args: argparse.Namespace, log: Logger) -> None:
    start = Path(args.cwd).expanduser().resolve()
    root = detect_git_root(start, log)
    lock_fh = lock_or_exit(root, log)
    try:
        now = dt.datetime.now(JST)
        log.line("=" * 72)
        log.line(f"YNFactory daily Git sync: {now:%Y-%m-%d %A %H:%M:%S %Z}")
        log.line(f"root: {root}")
        ensure_clean_git_state(root, log)

        if args.dry_run:
            changed = has_worktree_changes(root, log)
            log.line(f"DRY RUN: local changes present: {changed}")
            log.line("DRY RUN: would stage, validate, commit, push, pull, and mirror pulled paths.")
            return

        branch = git_output(["rev-parse", "--abbrev-ref", "HEAD"], cwd=root, log=log)
        run(["git", "fetch", "origin", branch], cwd=root, log=log)

        made_commit = commit_if_needed(root, log, args.message_prefix)
        ahead, behind = ahead_behind(root, log, branch)
        log.line(f"ahead={ahead}, behind={behind}, made_commit={made_commit}")
        if ahead:
            push_with_rebase_retry(root, log, branch, args.push_retries)
        else:
            log.line("No local commits to push.")

        before_pull = git_output(["rev-parse", "HEAD"], cwd=root, log=log)
        run(["git", "pull", "--ff-only", "origin", branch], cwd=root, log=log)
        after_pull = git_output(["rev-parse", "HEAD"], cwd=root, log=log)
        if not args.no_drive_sync:
            sync_pull_changes_to_drive(root, before_pull, after_pull, log)

        run(["git", "status", "--short", "--branch"], cwd=root, log=log)
        log.line("Daily Git sync completed.")
    finally:
        lock_fh.close()


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cwd",
        default=os.environ.get("YNFACTORY_ROOT", "."),
        help="Path inside the local Git worktree. Defaults to YNFACTORY_ROOT or current directory.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Show intended work without changing Git state.")
    parser.add_argument("--no-drive-sync", action="store_true", help="Skip mirroring pulled paths to Drive.")
    parser.add_argument("--push-retries", type=int, default=2, help="Push attempts before failing.")
    parser.add_argument(
        "--message-prefix",
        default="chore(auto): daily git sync",
        help="Commit message prefix. The JST date is appended automatically.",
    )
    parser.add_argument(
        "--log-dir",
        default=str(default_log_dir()),
        help="Directory for daily run logs.",
    )
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    log_day = dt.datetime.now(JST).strftime("%Y-%m-%d")
    log = Logger(Path(args.log_dir).expanduser() / f"{log_day}.log")
    try:
        run_once(args, log)
        return 0
    except Exception as exc:
        log.line(f"ERROR: {exc}")
        return 1
    finally:
        log.close()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
