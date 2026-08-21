#!/usr/bin/env python3
"""Sync selected files between the Drive worktree and the local Git worktree."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path


DEFAULT_DRIVE_ROOT_CANDIDATES = [
    Path.home()
    / "Library"
    / "CloudStorage"
    / "GoogleDrive-yuichi4107@gmail.com"
    / "マイドライブ"
    / "YNFactory-cc",
    Path("G:/マイドライブ/YNFactory-cc"),
    Path("G:/My Drive/YNFactory-cc"),
]


def run_git(local_root: Path, args: list[str], capture: bool = True) -> list[str]:
    result = subprocess.run(
        ["git", *args],
        cwd=local_root,
        check=True,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
    )
    if not capture:
        return []
    return [line for line in result.stdout.splitlines() if line.strip()]


def detect_local_root() -> Path:
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return Path(result.stdout.strip()).resolve()


def detect_drive_root(value: str | None) -> Path:
    if value:
        root = Path(value).expanduser()
        if root.exists():
            return root.resolve()
        raise SystemExit(f"Drive root does not exist: {root}")

    env_value = os.environ.get("YNFACTORY_DRIVE_ROOT")
    if env_value:
        root = Path(env_value).expanduser()
        if root.exists():
            return root.resolve()
        raise SystemExit(f"YNFACTORY_DRIVE_ROOT does not exist: {root}")

    for candidate in DEFAULT_DRIVE_ROOT_CANDIDATES:
        if candidate.exists():
            return candidate.resolve()

    raise SystemExit(
        "Drive root not found. Set YNFACTORY_DRIVE_ROOT or pass --drive-root."
    )


def normalize_path_list(paths: list[str | Path]) -> list[Path]:
    raw_paths = [Path(path) for path in paths]
    seen: set[str] = set()
    result: list[Path] = []
    for path in raw_paths:
        if path.is_absolute():
            raise SystemExit(f"Use repo-relative paths only: {path}")
        clean = Path(os.path.normpath(str(path)))
        if str(clean) in (".", "") or str(clean).startswith(".."):
            raise SystemExit(f"Invalid path: {path}")
        if ".git" in clean.parts:
            raise SystemExit(f"Refusing to sync .git paths: {path}")
        key = clean.as_posix()
        if key not in seen:
            seen.add(key)
            result.append(clean)
    return result


def normalized_paths(args: argparse.Namespace, local_root: Path) -> list[Path]:
    paths = [Path(path) for path in args.paths]

    if args.from_last_commit:
        paths.extend(Path(path) for path in run_git(local_root, ["diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD"]))

    if args.from_last_pull:
        paths.extend(Path(path) for path in run_git(local_root, ["diff", "--name-only", "ORIG_HEAD..HEAD"]))

    result = normalize_path_list(paths)

    if not result:
        raise SystemExit("No paths selected. Pass paths or use --from-last-commit/--from-last-pull.")

    return result


def changed_paths_between(local_root: Path, before: str, after: str) -> list[Path]:
    if before == after:
        return []
    paths = run_git(local_root, ["diff", "--name-only", f"{before}..{after}"])
    return normalize_path_list(paths)


def ensure_no_uncommitted_target_changes(local_root: Path, paths: list[Path]) -> None:
    changed = set(run_git(local_root, ["status", "--porcelain", "--", *[path.as_posix() for path in paths]]))
    if changed:
        print("warning: target paths already have local Git changes before sync:")
        for line in sorted(changed):
            print(f"  {line}")


def remove_destination(dst: Path, dry_run: bool) -> None:
    if not dst.exists() and not dst.is_symlink():
        return
    print(f"remove: {dst}")
    if dry_run:
        return
    if dst.is_dir() and not dst.is_symlink():
        shutil.rmtree(dst)
    else:
        dst.unlink()


def copy_path(src: Path, dst: Path, dry_run: bool, delete_missing: bool) -> None:
    if not src.exists() and not src.is_symlink():
        if delete_missing:
            remove_destination(dst, dry_run)
            return
        print(f"missing source, skipped: {src}")
        return

    print(f"copy: {src} -> {dst}")
    if dry_run:
        return

    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists() or dst.is_symlink():
        remove_destination(dst, dry_run=False)

    if src.is_dir() and not src.is_symlink():
        shutil.copytree(
            src,
            dst,
            symlinks=True,
            ignore=shutil.ignore_patterns(".git", "__pycache__", ".DS_Store"),
        )
    else:
        shutil.copy2(src, dst, follow_symlinks=False)


def sync_paths(
    direction: str,
    paths: list[Path],
    local_root: Path,
    drive_root: Path,
    dry_run: bool,
    delete_missing: bool,
) -> None:
    if direction == "drive-to-local":
        source_root, destination_root = drive_root, local_root
    else:
        source_root, destination_root = local_root, drive_root

    print(f"direction: {direction}")
    print(f"local:    {local_root}")
    print(f"drive:    {drive_root}")
    print(f"dry-run:  {dry_run}")

    for rel_path in paths:
        copy_path(
            source_root / rel_path,
            destination_root / rel_path,
            dry_run=dry_run,
            delete_missing=delete_missing,
        )


def commit_and_push(
    args: argparse.Namespace,
    paths: list[Path],
    local_root: Path,
    drive_root: Path,
) -> None:
    if not args.message:
        raise SystemExit("commit-push requires --message.")
    ensure_no_uncommitted_target_changes(local_root, paths)
    sync_paths(
        "drive-to-local",
        paths,
        local_root,
        drive_root,
        dry_run=args.dry_run,
        delete_missing=args.delete_missing,
    )
    if args.dry_run:
        print("dry-run: skipped git add/commit/push")
        return

    path_args = [path.as_posix() for path in paths]
    run_git(local_root, ["add", "--", *path_args])
    staged = run_git(local_root, ["diff", "--cached", "--name-only", "--", *path_args])
    if not staged:
        print("No staged changes after Drive sync. Skipped commit and push.")
        return

    print("staged:")
    for path in staged:
        print(f"  {path}")
    run_git(local_root, ["commit", "-m", args.message], capture=False)
    run_git(local_root, ["push", args.remote, args.branch], capture=False)


def pull_and_sync(args: argparse.Namespace, local_root: Path, drive_root: Path) -> None:
    before = run_git(local_root, ["rev-parse", "HEAD"])[0]
    print(f"pull: {args.remote} {args.branch}")
    if args.dry_run:
        print("dry-run: skipped git pull and Drive sync")
        return

    run_git(local_root, ["pull", "--ff-only", args.remote, args.branch], capture=False)
    after = run_git(local_root, ["rev-parse", "HEAD"])[0]
    paths = changed_paths_between(local_root, before, after)
    if not paths:
        print("No GitHub updates to sync to Drive.")
        return

    sync_paths(
        "local-to-drive",
        paths,
        local_root,
        drive_root,
        dry_run=False,
        delete_missing=True,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Sync selected repo-relative paths between Drive and local Git."
    )
    parser.add_argument(
        "direction",
        choices=["drive-to-local", "local-to-drive", "commit-push", "pull-sync"],
        help=(
            "drive-to-local/local-to-drive only sync paths. "
            "commit-push syncs Drive paths to local Git, commits, and pushes. "
            "pull-sync pulls from GitHub and syncs pulled paths to Drive."
        ),
    )
    parser.add_argument("paths", nargs="*", help="Repo-relative file or directory paths.")
    parser.add_argument("--drive-root", help="Google Drive YNFactory-cc root.")
    parser.add_argument("--local-root", help="Local Git YNFactory-cc root. Defaults to current Git root.")
    parser.add_argument("-m", "--message", help="Commit message for commit-push.")
    parser.add_argument("--remote", default="origin", help="Git remote for commit-push/pull-sync.")
    parser.add_argument("--branch", default="main", help="Git branch for commit-push/pull-sync.")
    parser.add_argument("--dry-run", action="store_true", help="Show actions without copying.")
    parser.add_argument("--delete-missing", action="store_true", help="Delete destination paths when source paths are missing.")
    parser.add_argument("--from-last-commit", action="store_true", help="Use paths changed in HEAD.")
    parser.add_argument("--from-last-pull", action="store_true", help="Use paths changed by the last pull, based on ORIG_HEAD..HEAD.")
    if hasattr(parser, "parse_intermixed_args"):
        args = parser.parse_intermixed_args()
    else:
        args = parser.parse_args()

    local_root = Path(args.local_root).expanduser().resolve() if args.local_root else detect_local_root()
    drive_root = detect_drive_root(args.drive_root)

    if not (local_root / ".git").exists():
        raise SystemExit(f"Local root is not a Git worktree: {local_root}")
    if (drive_root / ".git").exists():
        print(
            f"warning: Drive root contains .git; do not run git commands there: {drive_root}",
            file=sys.stderr,
        )
    if local_root == drive_root:
        raise SystemExit("Local root and Drive root must be different directories.")

    if args.direction == "pull-sync":
        pull_and_sync(args, local_root, drive_root)
        return 0

    paths = normalized_paths(args, local_root)
    if args.direction == "commit-push":
        commit_and_push(args, paths, local_root, drive_root)
        return 0

    sync_paths(
        args.direction,
        paths,
        local_root,
        drive_root,
        dry_run=args.dry_run,
        delete_missing=args.delete_missing,
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())
