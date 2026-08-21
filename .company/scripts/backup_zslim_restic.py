#!/usr/bin/env python3
"""Back up the Drive-side YNFactory-cc workspace to ZSlim with restic."""

from __future__ import annotations

import argparse
import os
import secrets
import shlex
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path


DEFAULT_DRIVE_ROOT = (
    Path.home()
    / "Library"
    / "CloudStorage"
    / "GoogleDrive-yuichi4107@gmail.com"
    / "マイドライブ"
    / "YNFactory-cc"
)
DEFAULT_REPO = Path("/Volumes/ZSlim/YNFactory-backups/restic")
DEFAULT_PASSWORD_FILE = Path.home() / ".ynfactory" / "restic-zslim-password"
RESTIC_SOURCE_READ_WARNING_CODE = 3

EXCLUDES = [
    ".git",
    ".git_drivebackup",
    ".DS_Store",
    ".company/.venvs",
    ".playwright-mcp",
    "**/__pycache__",
    "**/.pytest_cache",
    "**/.mypy_cache",
    "**/.ruff_cache",
    "**/node_modules",
    "**/.venv",
    "**/venv",
    "**/logs",
    "**/tmp",
    "**/temp",
    ".company/secretary/inbox/2026-06-16.md",
    "**/ai-trade-system/results/**/charts/*.png",
    "**/keiba-unified/win5/data/cache/*.html",
    "**/*.tmp.drivedownload",
    "**/*.tmp.driveupload",
]


class CommandError(RuntimeError):
    def __init__(self, returncode: int, command: list[str]) -> None:
        self.returncode = returncode
        self.command = command
        super().__init__(f"command failed ({returncode}): {shlex.join(command)}")


def require_restic() -> str:
    restic = shutil.which("restic")
    if restic:
        return restic
    raise SystemExit(
        "restic is not installed. Install it with: brew install restic"
    )


def run_result(
    args: list[str], env: dict[str, str], cwd: Path | None = None
) -> subprocess.CompletedProcess[str]:
    print("$ " + shlex.join(args))
    return subprocess.run(args, cwd=cwd, env=env, text=True)


def run(args: list[str], env: dict[str, str], cwd: Path | None = None) -> None:
    result = run_result(args, env=env, cwd=cwd)
    if result.returncode != 0:
        raise CommandError(result.returncode, args)


def run_backup_with_retry(
    command: list[str], env: dict[str, str], retries: int, retry_delay_seconds: int
) -> None:
    for attempt in range(retries + 1):
        result = run_result(command, env=env)
        if result.returncode == 0:
            return

        can_retry = (
            result.returncode == RESTIC_SOURCE_READ_WARNING_CODE
            and attempt < retries
        )
        if can_retry:
            print(
                "restic backup reported unreadable source files; "
                f"retrying in {retry_delay_seconds} seconds "
                f"({attempt + 1}/{retries})"
            )
            time.sleep(retry_delay_seconds)
            continue

        raise CommandError(result.returncode, command)


def ensure_password_file(path: Path, create: bool) -> None:
    if path.exists():
        return
    if not create:
        raise SystemExit(
            f"Password file does not exist: {path}\n"
            "Run init first, or create this file manually outside the repository."
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(secrets.token_urlsafe(48) + "\n", encoding="utf-8")
    path.chmod(0o600)
    print(f"created password file outside the repo: {path}")


def restic_env(repo: Path, password_file: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["RESTIC_REPOSITORY"] = str(repo)
    env["RESTIC_PASSWORD_FILE"] = str(password_file)
    return env


def repo_initialized(repo: Path) -> bool:
    return (repo / "config").exists()


def restic_base(restic: str, repo: Path, password_file: Path) -> tuple[list[str], dict[str, str]]:
    return [restic], restic_env(repo, password_file)


def init_repo(args: argparse.Namespace) -> None:
    restic = require_restic()
    drive_root = Path(args.drive_root).expanduser().resolve()
    repo = Path(args.repo).expanduser()
    password_file = Path(args.password_file).expanduser()
    if not drive_root.exists():
        raise SystemExit(f"Drive root does not exist: {drive_root}")
    if not Path("/Volumes/ZSlim").exists():
        raise SystemExit("ZSlim is not mounted at /Volumes/ZSlim")
    repo.mkdir(parents=True, exist_ok=True)
    ensure_password_file(password_file, create=True)
    base, env = restic_base(restic, repo, password_file)
    if repo_initialized(repo):
        print(f"restic repo already initialized: {repo}")
        return
    run([*base, "init"], env=env)


def backup(args: argparse.Namespace) -> None:
    restic = require_restic()
    drive_root = Path(args.drive_root).expanduser().resolve()
    repo = Path(args.repo).expanduser()
    password_file = Path(args.password_file).expanduser()
    if not drive_root.exists():
        raise SystemExit(f"Drive root does not exist: {drive_root}")
    ensure_password_file(password_file, create=False)
    if not repo_initialized(repo):
        raise SystemExit(f"restic repo is not initialized: {repo}. Run init first.")
    base, env = restic_base(restic, repo, password_file)
    command = [
        *base,
        "backup",
        str(drive_root),
        "--one-file-system",
        "--tag",
        "ynfactory-cc",
        "--tag",
        socket.gethostname(),
    ]
    for pattern in EXCLUDES:
        command.extend(["--exclude", pattern])
    if args.dry_run:
        command.append("--dry-run")
    run_backup_with_retry(
        command,
        env=env,
        retries=args.backup_retries,
        retry_delay_seconds=args.backup_retry_delay_seconds,
    )


def forget(args: argparse.Namespace) -> None:
    restic = require_restic()
    repo = Path(args.repo).expanduser()
    password_file = Path(args.password_file).expanduser()
    ensure_password_file(password_file, create=False)
    base, env = restic_base(restic, repo, password_file)
    command = [
        *base,
        "forget",
        "--keep-daily",
        "7",
        "--keep-weekly",
        "8",
        "--keep-monthly",
        "12",
        "--tag",
        "ynfactory-cc",
    ]
    if not args.no_prune:
        command.append("--prune")
    run(command, env=env)


def check(args: argparse.Namespace) -> None:
    restic = require_restic()
    repo = Path(args.repo).expanduser()
    password_file = Path(args.password_file).expanduser()
    ensure_password_file(password_file, create=False)
    base, env = restic_base(restic, repo, password_file)
    run([*base, "check"], env=env)


def snapshots(args: argparse.Namespace, tag: str = "ynfactory-cc") -> None:
    restic = require_restic()
    repo = Path(args.repo).expanduser()
    password_file = Path(args.password_file).expanduser()
    ensure_password_file(password_file, create=False)
    base, env = restic_base(restic, repo, password_file)
    run([*base, "snapshots", "--tag", tag], env=env)


def restore_latest(args: argparse.Namespace) -> None:
    restic = require_restic()
    repo = Path(args.repo).expanduser()
    password_file = Path(args.password_file).expanduser()
    target = Path(args.target).expanduser().resolve()
    ensure_password_file(password_file, create=False)
    target.mkdir(parents=True, exist_ok=True)
    base, env = restic_base(restic, repo, password_file)
    run([*base, "restore", "latest", "--target", str(target), "--tag", "ynfactory-cc"], env=env)


def run_all(args: argparse.Namespace) -> None:
    backup(args)
    forget(args)
    check(args)


def smoke_test(args: argparse.Namespace) -> None:
    restic = require_restic()
    drive_root = Path(args.drive_root).expanduser().resolve()
    repo = Path(args.repo).expanduser()
    password_file = Path(args.password_file).expanduser()
    ensure_password_file(password_file, create=False)
    if not repo_initialized(repo):
        raise SystemExit(f"restic repo is not initialized: {repo}. Run init first.")

    source_files = [
        drive_root / "AGENTS.md",
        drive_root / "docs" / "backup-zslim.md",
    ]
    for source in source_files:
        if not source.exists():
            raise SystemExit(f"Smoke-test source does not exist: {source}")

    base, env = restic_base(restic, repo, password_file)
    run(
        [
            *base,
            "backup",
            *[str(path) for path in source_files],
            "--tag",
            "ynfactory-smoke",
        ],
        env=env,
    )

    target = (
        Path(args.target).expanduser().resolve()
        if args.target
        else Path("/tmp/ynfactory-zslim-smoke-restore")
    )
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True, exist_ok=True)
    run(
        [*base, "restore", "latest", "--target", str(target), "--tag", "ynfactory-smoke"],
        env=env,
    )

    restored = list(target.rglob("AGENTS.md"))
    if not restored:
        raise CommandError(f"smoke restore did not produce AGENTS.md under {target}")
    print(f"smoke restore OK: {restored[0]}")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=[
            "init",
            "backup",
            "forget",
            "check",
            "snapshots",
            "restore-latest",
            "run",
            "smoke-test",
        ],
    )
    parser.add_argument("--drive-root", default=str(DEFAULT_DRIVE_ROOT))
    parser.add_argument("--repo", default=str(DEFAULT_REPO))
    parser.add_argument("--password-file", default=str(DEFAULT_PASSWORD_FILE))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-prune", action="store_true")
    parser.add_argument(
        "--backup-retries",
        type=int,
        default=1,
        help=(
            "Retry restic backup this many times when it returns source-read "
            "warnings. Defaults to 1."
        ),
    )
    parser.add_argument(
        "--backup-retry-delay-seconds",
        type=int,
        default=120,
        help="Seconds to wait before retrying backup after source-read warnings.",
    )
    parser.add_argument("--target", help="Restore target for restore-latest.")
    args = parser.parse_args(argv)
    if args.backup_retries < 0:
        parser.error("--backup-retries must be 0 or greater")
    if args.backup_retry_delay_seconds < 0:
        parser.error("--backup-retry-delay-seconds must be 0 or greater")
    return args


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    try:
        if args.command == "init":
            init_repo(args)
        elif args.command == "backup":
            backup(args)
        elif args.command == "forget":
            forget(args)
        elif args.command == "check":
            check(args)
        elif args.command == "snapshots":
            snapshots(args)
        elif args.command == "restore-latest":
            if not args.target:
                raise SystemExit("restore-latest requires --target.")
            restore_latest(args)
        elif args.command == "run":
            run_all(args)
        elif args.command == "smoke-test":
            smoke_test(args)
        return 0
    except CommandError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
